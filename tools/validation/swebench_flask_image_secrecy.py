#!/usr/bin/env python3
"""Fail-closed image audit for locked Flask test/gold patch signatures.

The private official row is read by the caller. Patches and target paths reach
only a disposable, read-only Docker container over stdin, never argv, env, a
host mount, or the receipt. The container has no network and prints aggregate
booleans/counts only. This proves absence of those locked signatures in the
accessible image filesystem and Git object database, not absence of all
possible undisclosed secrets. This is a stage-zero gate, not a benchmark score.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, cast

if __package__:
    from . import swebench_flask_official_oracle as oracle
else:
    import swebench_flask_official_oracle as oracle


SCHEMA = "axrun.swebench-flask-image-secrecy@2"
IMAGE_HEAD = "966bb873e3a1e42d857362a17f5af2533dfd8f46"
MAX_PATCH_BYTES = 2 << 20
MAX_TARGETS = 64
MAX_AUDIT_OUTPUT = 16 << 10
AUDIT_TIMEOUT_SECONDS = 600
MIN_MEANINGFUL_ADDITION_BYTES = 24
_CONTAINER_ERROR_CODES = frozenset(
    {
        "additional_git_repository_unscanned",
        "filesystem_scan_failed",
        "filesystem_scan_unbounded",
        "git_object_scan_failed",
        "git_object_scan_invalid",
        "git_object_scan_unbounded",
        "git_read_failed",
        "image_git_invalid",
        "patch_history_unavailable",
        "patch_history_unbounded",
        "patch_id_unavailable",
        "request_shape_invalid",
        "scan_content_truncated",
        "signature_invalid",
        "signature_missing",
        "signatures_unbounded",
        "target_current_object_invalid",
        "target_current_unbounded",
        "target_history_object_invalid",
        "target_history_unavailable",
        "target_history_unbounded",
    }
)


class SecrecyError(RuntimeError):
    """Stable, non-sensitive audit failure."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_target(path: str) -> str:
    if not path or "\x00" in path or "\n" in path:
        raise SecrecyError("patch_target_invalid")
    parts = PurePosixPath(path).parts
    if path.startswith("/") or any(part in {"", ".", "..", ".git"} for part in parts):
        raise SecrecyError("patch_target_invalid")
    if str(PurePosixPath(path)) != path:
        raise SecrecyError("patch_target_noncanonical")
    return path


def _target_paths(patch: bytes) -> list[str]:
    result = subprocess.run(
        ["git", "apply", "--numstat", "-z", "-"],
        input=patch,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        env=oracle.safe_subprocess_env(),
    )
    if result.returncode != 0:
        raise SecrecyError("patch_numstat_invalid")
    records = result.stdout.split(b"\x00")
    if records[-1:] != [b""]:
        raise SecrecyError("patch_numstat_invalid")
    paths: list[str] = []
    for record in records[:-1]:
        parts = record.split(b"\t", 2)
        if len(parts) != 3 or not parts[2]:
            # Git's -z rename/copy encoding adds extra NUL-separated paths.
            # This one-instance audit deliberately refuses that grammar.
            raise SecrecyError("patch_rename_or_numstat_invalid")
        try:
            paths.append(_validate_target(parts[2].decode("utf-8")))
        except UnicodeDecodeError as exc:
            raise SecrecyError("patch_target_invalid_utf8") from exc
    if not paths or len(paths) > MAX_TARGETS or len(set(paths)) != len(paths):
        raise SecrecyError("patch_target_count_invalid")
    return paths


def _flush_added_group(group: list[bytes], encoded: list[str]) -> bool:
    if not group:
        return False
    payload = b"".join(group)
    meaningful = sum(1 for byte in payload if chr(byte).isalnum())
    group.clear()
    if len(payload.strip()) < MIN_MEANINGFUL_ADDITION_BYTES or meaningful < 12:
        return True
    encoded.append(base64.b64encode(payload).decode("ascii"))
    return False


def _patch_targets_and_hunks(patch: str) -> list[dict[str, Any]]:
    data = patch.encode("utf-8")
    if not data or len(data) > MAX_PATCH_BYTES or not data.startswith(b"diff --git "):
        raise SecrecyError("patch_shape_invalid")
    blocks = [
        b"diff --git " + block for block in data[len(b"diff --git ") :].split(b"\ndiff --git ")
    ]
    paths = _target_paths(data)
    if len(blocks) != len(paths):
        raise SecrecyError("patch_block_count_invalid")
    result: list[dict[str, Any]] = []
    for path, block in zip(paths, blocks, strict=True):
        header, separator, body = block.partition(b"\n@@ ")
        if not separator or b"GIT binary patch" in block or b"\nBinary files " in block:
            raise SecrecyError("patch_hunk_invalid")
        if any(marker in header for marker in (b"\nrename ", b"\ncopy ", b"\ndeleted file mode ")):
            raise SecrecyError("patch_operation_unsupported")
        operation = "added" if b"\nnew file mode " in header else "modified"
        if operation == "added" and b"\n--- /dev/null" not in header:
            raise SecrecyError("patch_added_header_invalid")
        if operation == "modified" and b"\n--- /dev/null" in header:
            raise SecrecyError("patch_modified_header_invalid")
        hunk_bodies = [b"@@ " + h for h in (b"@@ " + body).split(b"\n@@ ")]
        encoded_hunks: list[str] = []
        encoded_additions: list[str] = []
        unprovable_fragments = 0
        for hunk in hunk_bodies:
            lines = hunk.splitlines(keepends=True)
            if not lines or not lines[0].startswith(b"@@ "):
                raise SecrecyError("patch_hunk_invalid")
            after: list[bytes] = []
            additions = 0
            added_group: list[bytes] = []
            for line in lines[1:]:
                if line.startswith(b"+"):
                    after.append(line[1:])
                    added_group.append(line[1:])
                    additions += 1
                elif line.startswith(b" "):
                    unprovable_fragments += _flush_added_group(added_group, encoded_additions)
                    after.append(line[1:])
                elif line.startswith((b"-", b"\\ No newline at end of file")):
                    unprovable_fragments += _flush_added_group(added_group, encoded_additions)
                    continue
                else:
                    raise SecrecyError("patch_hunk_invalid")
            unprovable_fragments += _flush_added_group(added_group, encoded_additions)
            if additions:
                payload = b"".join(after)
                if not payload:
                    raise SecrecyError("patch_hunk_invalid")
                encoded_hunks.append(base64.b64encode(payload).decode("ascii"))
        if not encoded_hunks:
            raise SecrecyError("patch_has_no_added_content")
        result.append(
            {
                "path": path,
                "operation": operation,
                "after_hunks": encoded_hunks,
                "added_fragments": encoded_additions,
                "unprovable_fragments": unprovable_fragments,
            }
        )
    return result


# The entire audit body runs inside the pinned image. It emits no paths, hunks,
# patch bodies, or Git output. Every subprocess has a finite timeout and closed
# stderr. A missing Git tool, truncated history, or unexpected shape blocks.
_CONTAINER_CODE = r"""
import base64, binascii, json, os, pathlib, stat, subprocess, sys

MAX_FILESYSTEM_ENTRIES = 500000
MAX_FILESYSTEM_BYTES = 16 << 30
MAX_SINGLE_FILE_BYTES = 4 << 30
MAX_GIT_OBJECTS = 250000
MAX_GIT_OBJECT_BYTES = 8 << 30
MAX_SINGLE_GIT_OBJECT_BYTES = 1 << 30
SCAN_CHUNK_BYTES = 1 << 20

def fail(code):
    print(json.dumps({"error": code}, sort_keys=True))
    raise SystemExit(1)

def git(*args, input_bytes=None, timeout=30):
    try:
        return subprocess.run(["git", *args], cwd="/testbed", input=input_bytes,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout, check=False,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                   "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1",
                                   "GIT_CONFIG_GLOBAL": "/dev/null"})
    except (OSError, subprocess.TimeoutExpired):
        fail("git_read_failed")

def signatures(request):
    result = {}
    total_count = 0
    total_bytes = 0
    for prefix in ("test", "gold"):
        needles = set()
        for target in request[prefix + "_targets"]:
            for key in ("after_hunks", "added_fragments"):
                for encoded in target[key]:
                    try:
                        needle = base64.b64decode(encoded, validate=True)
                    except (ValueError, binascii.Error):
                        fail("signature_invalid")
                    if not needle:
                        fail("signature_invalid")
                    needles.add(needle)
        if not needles:
            fail("signature_missing")
        result[prefix] = tuple(sorted(needles))
        total_count += len(needles)
        total_bytes += sum(map(len, needles))
    if total_count > 4096 or total_bytes > 8 << 20:
        fail("signatures_unbounded")
    return result

def scan_stream(stream, length, needles):
    # Preserve the longest possible cross-chunk match without loading a file
    # or Git object into memory. Always consume the whole object, even after
    # both signatures have matched, so completion has a precise meaning.
    maximum = max(map(len, (*needles["test"], *needles["gold"])))
    tail = b""
    matches = {"test": False, "gold": False}
    remaining = length
    while remaining:
        chunk = stream.read(min(SCAN_CHUNK_BYTES, remaining))
        if not chunk:
            fail("scan_content_truncated")
        remaining -= len(chunk)
        window = tail + chunk
        for prefix in ("test", "gold"):
            if not matches[prefix] and any(item in window for item in needles[prefix]):
                matches[prefix] = True
        tail = window[-(maximum - 1):] if maximum > 1 else b""
    return matches

def scan_filesystem(needles, result):
    entries = 0
    regular_files = 0
    regular_bytes = 0
    matches = {"test": 0, "gold": 0}
    def walk_error(_error):
        fail("filesystem_scan_failed")
    try:
        for root, dirs, files in os.walk("/", topdown=True, followlinks=False,
                                         onerror=walk_error):
            if root == "/":
                dirs[:] = [name for name in dirs if name not in {"proc", "sys", "dev"}]
            dirs.sort()
            files.sort()
            kept_dirs = []
            for name in dirs:
                entries += 1
                if entries > MAX_FILESYSTEM_ENTRIES:
                    fail("filesystem_scan_unbounded")
                path = os.path.join(root, name)
                if name == ".git" and path != "/testbed/.git":
                    fail("additional_git_repository_unscanned")
                mode = os.lstat(path).st_mode
                if path == "/testbed/.git" and not stat.S_ISDIR(mode):
                    fail("image_git_invalid")
                if stat.S_ISDIR(mode):
                    kept_dirs.append(name)
                elif not stat.S_ISLNK(mode):
                    fail("filesystem_scan_failed")
            dirs[:] = kept_dirs
            for name in files:
                entries += 1
                if entries > MAX_FILESYSTEM_ENTRIES:
                    fail("filesystem_scan_unbounded")
                path = os.path.join(root, name)
                if name == ".git":
                    fail("additional_git_repository_unscanned")
                metadata = os.lstat(path)
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    continue
                size = metadata.st_size
                if (size < 0 or size > MAX_SINGLE_FILE_BYTES or
                        regular_bytes + size > MAX_FILESYSTEM_BYTES):
                    fail("filesystem_scan_unbounded")
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
                with os.fdopen(os.open(path, flags), "rb", closefd=True) as stream:
                    opened = os.fstat(stream.fileno())
                    if not stat.S_ISREG(opened.st_mode) or opened.st_size != size:
                        fail("filesystem_scan_failed")
                    found = scan_stream(stream, size, needles)
                    if stream.read(1):
                        fail("filesystem_scan_failed")
                regular_files += 1
                regular_bytes += size
                for prefix in matches:
                    matches[prefix] += int(found[prefix])
    except (OSError, OverflowError):
        fail("filesystem_scan_failed")
    result.update({
        "filesystem_scan_complete": True,
        "filesystem_entry_count": entries,
        "filesystem_regular_file_count": regular_files,
        "filesystem_regular_file_bytes": regular_bytes,
        "test_full_filesystem_match_count": matches["test"],
        "gold_full_filesystem_match_count": matches["gold"],
    })

def scan_git_objects(needles, result):
    # --batch-all-objects includes unreachable and dangling loose/packed
    # objects, unlike rev-list --all. Object content is streamed, not logged.
    command = ["git", "cat-file", "--batch-all-objects", "--batch"]
    try:
        process = subprocess.Popen(
            command, cwd="/testbed", stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null"},
        )
    except OSError:
        fail("git_object_scan_failed")
    objects = 0
    object_bytes = 0
    matches = {"test": 0, "gold": 0}
    try:
        if process.stdout is None:
            fail("git_object_scan_failed")
        while True:
            header = process.stdout.readline(256)
            if not header:
                break
            fields = header.removesuffix(b"\n").split(b" ")
            if not header.endswith(b"\n") or len(fields) != 3:
                fail("git_object_scan_invalid")
            oid, kind, raw_size = fields
            if (len(oid) not in (40, 64) or
                    kind not in (b"blob", b"tree", b"commit", b"tag") or
                    not raw_size.isdigit()):
                fail("git_object_scan_invalid")
            try:
                bytes.fromhex(oid.decode("ascii"))
                size = int(raw_size)
            except (ValueError, UnicodeDecodeError):
                fail("git_object_scan_invalid")
            objects += 1
            if (objects > MAX_GIT_OBJECTS or size > MAX_SINGLE_GIT_OBJECT_BYTES or
                    object_bytes + size > MAX_GIT_OBJECT_BYTES):
                fail("git_object_scan_unbounded")
            found = scan_stream(process.stdout, size, needles)
            if process.stdout.read(1) != b"\n":
                fail("git_object_scan_invalid")
            object_bytes += size
            for prefix in matches:
                matches[prefix] += int(found[prefix])
        if process.wait(timeout=10):
            fail("git_object_scan_failed")
    except (OSError, subprocess.TimeoutExpired):
        fail("git_object_scan_failed")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    result.update({
        "git_all_object_scan_complete": True,
        "git_all_object_count": objects,
        "git_all_object_bytes": object_bytes,
        "test_all_git_object_match_count": matches["test"],
        "gold_all_git_object_match_count": matches["gold"],
    })

request = json.load(sys.stdin)
if set(request) != {"gold_patch", "test_patch", "gold_targets", "test_targets"}:
    fail("request_shape_invalid")
needles = signatures(request)
head = git("rev-parse", "--verify", "HEAD")
dirty = git("status", "--porcelain=v1", "--untracked-files=all")
base = git("cat-file", "-e", "7ee9ceb71e868944a46e1ff00b506772a53a4f1d^{commit}")
if head.returncode or dirty.returncode:
    fail("image_git_invalid")
result = {
    "image_head": head.stdout.decode("ascii", "strict").strip(),
    "image_clean": not bool(dirty.stdout),
    "row_base_present": base.returncode == 0,
}

all_paths = []
history_bytes = 0
history_blobs = 0
for prefix in ("test", "gold"):
    patch = request[prefix + "_patch"].encode("utf-8")
    result[prefix + "_patch_forward_applies"] = (
        git("apply", "--check", "-", input_bytes=patch).returncode == 0
    )
    result[prefix + "_patch_reverse_applies"] = (
        git("apply", "--reverse", "--check", "-", input_bytes=patch).returncode == 0
    )
    targets = request[prefix + "_targets"]
    all_paths += [target["path"] for target in targets]
    result[prefix + "_target_count"] = len(targets)
    for key in ("added_hunk_current_match_count", "added_hunk_history_match_count",
                "added_fragment_current_match_count", "added_fragment_history_match_count",
                "unprovable_fragment_count"):
        result[prefix + "_" + key] = 0
    if prefix == "test":
        result["added_target_count"] = sum(t["operation"] == "added" for t in targets)
        result["modified_target_count"] = sum(t["operation"] == "modified" for t in targets)
        for key in ("added_current_count", "added_history_count",
                    "modified_current_count", "modified_history_count"):
            result[key] = 0
    for target in targets:
        path = target["path"]
        operation = target["operation"]
        current = os.path.lexists(os.path.join("/testbed", path))
        if prefix == "test" and current:
            result[operation + "_current_count"] += 1
        commits = git("log", "--all", "--format=%H", "--", path, timeout=60)
        if commits.returncode:
            fail("target_history_unavailable")
        commit_ids = [line for line in commits.stdout.splitlines() if line]
        if len(commit_ids) > 512:
            fail("target_history_unbounded")
        if prefix == "test" and commit_ids:
            result[operation + "_history_count"] += 1
        blob_ids = set()
        for commit in [b"HEAD", *commit_ids]:
            obj = git("rev-parse", "--verify", commit.decode() + ":" + path)
            if obj.returncode == 0:
                blob_ids.add(obj.stdout.strip().decode("ascii", "strict"))
        hunks = [base64.b64decode(h) for h in target["after_hunks"]]
        fragments = [base64.b64decode(h) for h in target["added_fragments"]]
        result[prefix + "_unprovable_fragment_count"] += target["unprovable_fragments"]
        current_hunk = False
        current_fragment = False
        history_hunk = False
        history_fragment = False
        for obj in blob_ids:
            typ = git("cat-file", "-t", obj)
            if typ.returncode or typ.stdout.strip() != b"blob":
                fail("target_history_object_invalid")
            size = git("cat-file", "-s", obj)
            if size.returncode or not size.stdout.strip().isdigit():
                fail("target_history_object_invalid")
            length = int(size.stdout.strip())
            if length > 2 << 20 or history_bytes + length > 64 << 20 or history_blobs >= 2048:
                fail("target_history_unbounded")
            history_bytes += length
            history_blobs += 1
            blob = git("cat-file", "blob", obj)
            if blob.returncode or len(blob.stdout) != length:
                fail("target_history_object_invalid")
            history_hunk |= any(h in blob.stdout for h in hunks)
            history_fragment |= any(h in blob.stdout for h in fragments)
        if current:
            current_path = pathlib.Path("/testbed") / path
            if current_path.is_symlink() or not current_path.is_file():
                fail("target_current_object_invalid")
            if current_path.stat().st_size > 2 << 20:
                fail("target_current_unbounded")
            content = current_path.read_bytes()
            current_hunk = any(h in content for h in hunks)
            current_fragment = any(h in content for h in fragments)
        result[prefix + "_added_hunk_current_match_count"] += int(current_hunk)
        result[prefix + "_added_hunk_history_match_count"] += int(history_hunk)
        result[prefix + "_added_fragment_current_match_count"] += int(current_fragment)
        result[prefix + "_added_fragment_history_match_count"] += int(history_fragment)

result["history_blob_count"] = history_blobs
result["history_blob_bytes"] = history_bytes

paths = sorted(set(all_paths))
history = git("log", "--all", "--format=commit %H", "-p", "--no-ext-diff",
              "--", *paths, timeout=90)
if history.returncode or len(history.stdout) > 64 << 20:
    fail("patch_history_unbounded")
patch_ids = git("patch-id", "--stable", input_bytes=history.stdout, timeout=60)
if patch_ids.returncode:
    fail("patch_history_unavailable")
historic_ids = {line.split()[0] for line in patch_ids.stdout.splitlines() if line.split()}
result["history_patch_count"] = len(historic_ids)
for prefix in ("test", "gold"):
    patch_id = git("patch-id", "--stable", input_bytes=request[prefix + "_patch"].encode("utf-8"))
    if patch_id.returncode or not patch_id.stdout.strip():
        fail("patch_id_unavailable")
    result[prefix + "_patch_id_in_history"] = patch_id.stdout.split()[0] in historic_ids
scan_filesystem(needles, result)
scan_git_objects(needles, result)
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
"""


_AUDIT_FIELDS = frozenset(
    {
        "image_head",
        "image_clean",
        "row_base_present",
        "test_patch_forward_applies",
        "test_patch_reverse_applies",
        "gold_patch_forward_applies",
        "gold_patch_reverse_applies",
        "test_target_count",
        "gold_target_count",
        "added_target_count",
        "modified_target_count",
        "added_current_count",
        "added_history_count",
        "modified_current_count",
        "modified_history_count",
        "test_added_hunk_current_match_count",
        "test_added_hunk_history_match_count",
        "test_added_fragment_current_match_count",
        "test_added_fragment_history_match_count",
        "test_unprovable_fragment_count",
        "gold_added_hunk_current_match_count",
        "gold_added_hunk_history_match_count",
        "gold_added_fragment_current_match_count",
        "gold_added_fragment_history_match_count",
        "gold_unprovable_fragment_count",
        "history_blob_count",
        "history_blob_bytes",
        "history_patch_count",
        "test_patch_id_in_history",
        "gold_patch_id_in_history",
        "filesystem_scan_complete",
        "filesystem_entry_count",
        "filesystem_regular_file_count",
        "filesystem_regular_file_bytes",
        "test_full_filesystem_match_count",
        "gold_full_filesystem_match_count",
        "git_all_object_scan_complete",
        "git_all_object_count",
        "git_all_object_bytes",
        "test_all_git_object_match_count",
        "gold_all_git_object_match_count",
    }
)
_BOOL_FIELDS = frozenset(
    {
        "image_clean",
        "row_base_present",
        "test_patch_forward_applies",
        "test_patch_reverse_applies",
        "gold_patch_forward_applies",
        "gold_patch_reverse_applies",
        "test_patch_id_in_history",
        "gold_patch_id_in_history",
        "filesystem_scan_complete",
        "git_all_object_scan_complete",
    }
)


def _check_audit(value: object, target_count: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SecrecyError("image_audit_shape_invalid")
    audit = cast(dict[str, Any], value)
    if set(audit.keys()) != set(_AUDIT_FIELDS):
        raise SecrecyError("image_audit_shape_invalid")
    if audit["image_head"] != IMAGE_HEAD:
        raise SecrecyError("image_head_invalid")
    if any(type(audit[key]) is not bool for key in _BOOL_FIELDS):
        raise SecrecyError("image_audit_boolean_invalid")
    counts = _AUDIT_FIELDS - _BOOL_FIELDS - {"image_head"}
    if any(type(audit[key]) is not int or audit[key] < 0 for key in counts):
        raise SecrecyError("image_audit_count_invalid")
    if audit["test_target_count"] != target_count or (
        audit["added_target_count"] + audit["modified_target_count"] != target_count
    ):
        raise SecrecyError("image_audit_target_count_invalid")
    return audit


def _status(audit: dict[str, Any]) -> tuple[str, str]:
    if not audit["image_clean"] or not audit["row_base_present"]:
        return "blocked", "image_git_contract_invalid"
    if not audit["filesystem_scan_complete"] or not audit["git_all_object_scan_complete"]:
        return "blocked", "full_image_scan_incomplete"
    if audit["test_full_filesystem_match_count"] or audit["test_all_git_object_match_count"]:
        return "blocked", "test_added_content_reachable"
    if audit["gold_full_filesystem_match_count"] or audit["gold_all_git_object_match_count"]:
        return "blocked", "gold_added_content_reachable"
    if audit["test_unprovable_fragment_count"] or audit["gold_unprovable_fragment_count"]:
        return "blocked", "patch_content_history_unproven"
    if audit["added_current_count"] or audit["added_history_count"]:
        return "blocked", "new_test_target_reachable"
    for prefix in ("test", "gold"):
        for suffix in (
            "added_hunk_current_match_count",
            "added_hunk_history_match_count",
            "added_fragment_current_match_count",
            "added_fragment_history_match_count",
        ):
            if audit[f"{prefix}_{suffix}"]:
                return "blocked", f"{prefix}_added_content_reachable"
    if audit["test_patch_reverse_applies"] or audit["test_patch_id_in_history"]:
        return "blocked", "test_patch_reachable"
    if audit["gold_patch_reverse_applies"] or audit["gold_patch_id_in_history"]:
        return "blocked", "gold_patch_reachable"
    if not audit["gold_patch_forward_applies"] or not audit["test_patch_forward_applies"]:
        return "blocked", "locked_patch_not_applicable_to_image"
    return "passed", "no_locked_patch_signatures_reachable"


def _docker_audit(image_id: str, row: dict[str, Any]) -> dict[str, Any]:
    test_targets = _patch_targets_and_hunks(row["test_patch"])
    gold_targets = _patch_targets_and_hunks(row["patch"])
    request = {
        "gold_patch": row["patch"],
        "test_patch": row["test_patch"],
        "gold_targets": gold_targets,
        "test_targets": test_targets,
    }
    container_name = f"axrun-sweb-flask-secrecy-{uuid.uuid4().hex[:16]}"
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--pull",
        "never",
        "--platform",
        "linux/amd64",
        "--read-only",
        "--user",
        "0:0",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--cpus",
        "1",
        "--memory",
        "2g",
        "--pids-limit",
        "128",
        "--log-driver",
        "none",
        "--workdir",
        "/testbed",
        "--entrypoint",
        "/opt/miniconda3/bin/python",
        "-i",
        image_id,
        "-c",
        _CONTAINER_CODE,
    ]
    try:
        with tempfile.TemporaryFile() as output:
            completed = subprocess.run(
                command,
                input=json.dumps(request, sort_keys=True).encode("utf-8"),
                stdout=output,
                stderr=subprocess.DEVNULL,
                env=oracle.safe_subprocess_env(),
                timeout=AUDIT_TIMEOUT_SECONDS,
                check=False,
            )
            output.seek(0)
            payload = output.read(MAX_AUDIT_OUTPUT + 1)
    except subprocess.TimeoutExpired as exc:
        raise SecrecyError("image_audit_timed_out") from exc
    finally:
        _ensure_removed(container_name)
    if len(payload) > MAX_AUDIT_OUTPUT:
        raise SecrecyError("image_audit_output_unbounded")
    if completed.returncode:
        try:
            failed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            failed = None
        if (
            isinstance(failed, dict)
            and set(failed) == {"error"}
            and isinstance(failed["error"], str)
            and failed["error"] in _CONTAINER_ERROR_CODES
        ):
            raise SecrecyError(failed["error"])
        raise SecrecyError("image_audit_failed_closed")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecrecyError("image_audit_output_invalid") from exc
    return _check_audit(value, len(test_targets))


def _ensure_removed(container_name: str) -> None:
    # `--rm` handles normal exit; this exact-name cleanup also covers a Docker
    # client timeout without touching any other task's container.
    if re.fullmatch(r"axrun-sweb-flask-secrecy-[0-9a-f]{16}", container_name) is None:
        raise SecrecyError("image_audit_cleanup_name_invalid")
    try:
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            env=oracle.safe_subprocess_env(),
        )
        remaining = subprocess.run(
            [
                "docker",
                "ps",
                "--all",
                "--filter",
                f"name=^/{container_name}$",
                "--format",
                "{{.Names}}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            env=oracle.safe_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SecrecyError("image_audit_cleanup_unconfirmed") from None
    if remaining.returncode != 0 or remaining.stdout.strip():
        raise SecrecyError("image_audit_cleanup_unconfirmed")


def audit(row_path: Path) -> dict[str, Any]:
    oracle.check_native_linux()
    row = oracle.load_locked_row(row_path)
    image_id = oracle.check_local_image(oracle.IMAGE)
    image_audit = _docker_audit(image_id, row)
    status, reason_code = _status(image_audit)
    return {
        "schema_version": SCHEMA,
        "instance_id": oracle.INSTANCE_ID,
        "row_sha256": oracle.ROW_SHA256,
        "source_image": oracle.IMAGE,
        "image_id": image_id,
        "test_patch_sha256": _sha256(row["test_patch"].encode()),
        "gold_patch_sha256": _sha256(row["patch"].encode()),
        **image_audit,
        "status": status,
        "reason_code": reason_code,
    }


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    if path.is_symlink() or path.exists() or not path.parent.is_dir():
        raise SecrecyError("receipt_path_invalid")
    if path.parent.is_symlink() or not stat.S_ISDIR(path.parent.stat().st_mode):
        raise SecrecyError("receipt_parent_invalid")
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(payload)


def _config_paths(config: Path) -> tuple[Path, Path]:
    if config.is_symlink() or not config.is_file() or config.stat().st_size > 16 << 10:
        raise SecrecyError("config_file_invalid")

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise SecrecyError("config_duplicate_key")
            value[key] = item
        return value

    try:
        raw_data = json.loads(config.read_bytes(), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecrecyError("config_json_invalid") from exc
    if not isinstance(raw_data, dict):
        raise SecrecyError("config_shape_invalid")
    data = cast(dict[str, Any], raw_data)
    if set(data.keys()) != {"row", "receipt"}:
        raise SecrecyError("config_shape_invalid")
    if any(not isinstance(value, str) or not value for value in data.values()):
        raise SecrecyError("config_path_invalid")
    return Path(data["row"]), Path(data["receipt"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--row", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.config is not None:
            if args.row is not None or args.receipt is not None:
                raise SecrecyError("config_and_flags_conflict")
            row_path, receipt_path = _config_paths(args.config)
        elif args.row is not None and args.receipt is not None:
            row_path, receipt_path = args.row, args.receipt
        else:
            raise SecrecyError("input_paths_missing")
        receipt = audit(row_path)
        _write_receipt(receipt_path, receipt)
        summary = {
            "schema_version": SCHEMA,
            "status": receipt["status"],
            "reason_code": receipt["reason_code"],
            "receipt_sha256": _sha256(receipt_path.read_bytes()),
            "source_image": receipt["source_image"],
            "image_id": receipt["image_id"],
            "test_target_count": receipt["test_target_count"],
        }
        print(json.dumps(summary, sort_keys=True))
        return 0 if receipt["status"] == "passed" else 1
    except (SecrecyError, oracle.OracleError, OSError, ValueError) as exc:
        code = str(exc)
        if not code.isidentifier() or not code.islower():
            code = "image_secrecy_error"
        print(f"image_secrecy_failed_closed: {code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
