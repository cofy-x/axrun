"""Bounded, benchmark-owned Flask image admission scanner.

This implementation is shared by the model-free Docker source audit and Axern
runtime audit. It never logs private patch bodies, signatures, or target paths.
A clean result only proves absence of the locked signatures, not all secrets.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, cast


def _safe_subprocess_env() -> dict[str, str]:
    allowed = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SSL_CERT_FILE",
        "UV_CACHE_DIR",
        "XDG_CACHE_HOME",
    )
    env = {key: value for key in allowed if (value := os.environ.get(key)) is not None}
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


SCHEMA = "axrun.swebench-flask-image-secrecy@2"
IMAGE_HEAD = "966bb873e3a1e42d857362a17f5af2533dfd8f46"
MAX_PATCH_BYTES = 2 << 20
MAX_TARGETS = 64
MAX_AUDIT_OUTPUT = 16 << 10
AUDIT_TIMEOUT_SECONDS = 600
MIN_MEANINGFUL_ADDITION_BYTES = 24
REQUEST_PATH = "/run/axrun/flask-audit-request.json"
OUTPUT_PATH = "/outputs/flask-image-audit.json"
MAX_REQUEST_BYTES = 16 << 20
_CONTAINER_ERROR_CODES = frozenset(
    {
        "additional_git_repository_unscanned",
        "filesystem_scan_failed",
        "filesystem_walk_failed",
        "filesystem_walk_permission_denied",
        "filesystem_entry_invalid",
        "filesystem_size_changed",
        "filesystem_permission_denied",
        "filesystem_io_failed",
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
        env=_safe_subprocess_env(),
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
import base64, binascii, errno, json, os, pathlib, stat, subprocess, sys

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
    def walk_error(error):
        if error.errno in (errno.EACCES, errno.EPERM):
            fail("filesystem_walk_permission_denied")
        fail("filesystem_walk_failed")
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
                    fail("filesystem_entry_invalid")
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
                        fail("filesystem_size_changed")
                    found = scan_stream(stream, size, needles)
                    if stream.read(1):
                        fail("filesystem_size_changed")
                regular_files += 1
                regular_bytes += size
                for prefix in matches:
                    matches[prefix] += int(found[prefix])
    except PermissionError:
        fail("filesystem_permission_denied")
    except (OSError, OverflowError):
        fail("filesystem_io_failed")
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


def build_request(checked_row: dict[str, Any]) -> bytes:
    """Derive private scanner inputs from a resolver-validated official row.

    This is not a second dataset parser. Only the explicit resolver validates
    the row identity; no original row or patch is written to audit evidence.
    """
    gold = checked_row.get("patch")
    tests = checked_row.get("test_patch")
    if not isinstance(gold, str) or not isinstance(tests, str):
        raise SecrecyError("patch_shape_invalid")
    request = {
        "gold_patch": gold,
        "test_patch": tests,
        "gold_targets": _patch_targets_and_hunks(gold),
        "test_targets": _patch_targets_and_hunks(tests),
    }
    payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_REQUEST_BYTES:
        raise SecrecyError("signatures_unbounded")
    return payload


def check_audit_result(value: object, target_count: int) -> dict[str, Any]:
    """Validate the closed, shared scanner output before calculating admission."""
    return _check_audit(value, target_count)


def audit_status(audit: dict[str, Any]) -> tuple[str, str]:
    """Recompute the bounded signature-admission verdict from complete details."""
    return _status(audit)


def runtime_scan_script() -> bytes:
    """Return the closed Axern audit entrypoint using exactly the shared scanner.

    The private input is removed before scanning. An audit Run is always fresh,
    model-free, and separate from inference; its hidden inputs are never mounts
    or files in the model's Allocation. No directory is excluded to hide the
    audit input. Errors expose only stable codes, not exception bodies.
    """
    marker = "request = json.load(sys.stdin)"
    if _CONTAINER_CODE.count(marker) != 1:
        raise SecrecyError("scanner_contract_invalid")
    scanner = _CONTAINER_CODE.replace(marker, "request = _axrun_request")
    script = f"""import contextlib, io, json, os, pathlib, platform, signal, stat, sys

REQUEST = {REQUEST_PATH!r}
OUTPUT = {OUTPUT_PATH!r}
MAX_REQUEST = {MAX_REQUEST_BYTES}
MAX_OUTPUT = {MAX_AUDIT_OUTPUT}
ERROR_CODES = frozenset({tuple(sorted(_CONTAINER_ERROR_CODES))!r})
SCANNER = {scanner!r}

class AuditDeadline(BaseException):
    pass

def deadline(signum, frame):
    raise AuditDeadline()

def no_duplicates(pairs):
    result = {{}}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result

def reject_constant(value):
    raise ValueError()

def execute():
    path = pathlib.Path(REQUEST)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb", closefd=True) as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_REQUEST:
            raise ValueError()
        payload = stream.read(MAX_REQUEST + 1)
        if len(payload) != metadata.st_size or len(payload) > MAX_REQUEST:
            raise ValueError()
    # Delete the single declared audit input, never a caller-selected directory.
    path.unlink()
    if os.path.lexists(REQUEST):
        raise ValueError()
    request = json.loads(payload, object_pairs_hook=no_duplicates,
                        parse_constant=reject_constant)
    captured = io.StringIO()
    exit_code = 0
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(io.StringIO()):
        try:
            exec(compile(SCANNER, "<axrun-flask-image-audit>", "exec"),
                 {{"__name__": "__main__", "_axrun_request": request}})
        except SystemExit:
            exit_code = 1
    raw = captured.getvalue()
    if len(raw.encode("utf-8")) > MAX_OUTPUT:
        return {{"error": "image_audit_output_unbounded"}}, 1
    audit = json.loads(raw, object_pairs_hook=no_duplicates,
                       parse_constant=reject_constant)
    if exit_code:
        if (isinstance(audit, dict) and set(audit) == {{"error"}} and
                audit["error"] in ERROR_CODES):
            return audit, 1
        return {{"error": "runtime_audit_failed_closed"}}, 1
    return {{"machine": platform.machine(), "request_deleted": True,
            "audit": audit}}, 0

signal.signal(signal.SIGALRM, deadline)
signal.alarm({AUDIT_TIMEOUT_SECONDS})
try:
    result, exit_code = execute()
except AuditDeadline:
    result, exit_code = {{"error": "runtime_audit_deadline_exceeded"}}, 1
except BaseException:
    result, exit_code = {{"error": "runtime_audit_failed_closed"}}, 1
finally:
    signal.alarm(0)

try:
    destination = pathlib.Path(OUTPUT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb", closefd=True) as output:
        output.write(json.dumps(result, sort_keys=True,
                                separators=(",", ":")).encode("utf-8") + b"\\n")
except BaseException:
    sys.exit(1)
sys.exit(exit_code)
"""
    return script.encode("utf-8")


def scanner_implementation_sha256() -> str:
    """Bind the signature builder, validator, and exact executed runtime bytes."""
    return _sha256(Path(__file__).read_bytes() + b"\x00" + runtime_scan_script())
