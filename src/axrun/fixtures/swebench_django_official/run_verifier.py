"""Offline SWE-bench Django-12419 verifier for a fresh Axern Allocation.

The parser and pass-and-fail calculation follow pinned SWE-bench harness commit
f7bbbb2ccdf479001d6467c9e34af59e44a840f9. Only the CandidateBundle
patch and the locked evaluation script enter this verifier Run; no scorer
checkout, dataset row, gold patch, or model credential is required.
"""

# ruff: noqa: UP017 -- The imported Django image provides Python 3.10.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INSTANCE_ID = "django__django-12419"
IMAGE_HEAD = "7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
EVAL_SCRIPT_SHA256 = "da94f6e6b371f5f4f929fd0e71d2de2aa38427429380e7a18dfdc4498e5e5cd7"
SELECTION_SHA256 = "452bd1de2fd32e99ec6f365e0dc44a09212104be795b7904965b3cfedae7a23a"
RESULT_SCHEMA = "axrun.swebench-django-official-result@1"
MAX_LOG_BYTES = 16 << 20
START_MARKER = ">>>>> Start Test Output"
END_MARKER = ">>>>> End Test Output"
BAD_LOG_MARKERS = (
    ">>>>> Patch Apply Failed",
    ">>>>> Reset Failed",
    ">>>>> Tests Errored",
    ">>>>> Tests Timed Out",
)
TEST_STATUSES = frozenset({"PASSED", "FAILED", "SKIPPED", "ERROR", "XFAIL"})


class VerifierError(Exception):
    """Stable infrastructure or inconclusive-evaluation reason code."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex_digest(value: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _verified_file(path: Path, *, sha256: str) -> bytes:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise VerifierError("DJANGO_ASSET_NOT_REGULAR")
        data = path.read_bytes()
    except OSError as exc:
        raise VerifierError("DJANGO_ASSET_UNAVAILABLE") from exc
    if _digest(data) != sha256:
        raise VerifierError("DJANGO_ASSET_DIGEST_MISMATCH")
    return data


def parse_log_django(log: str) -> dict[str, str]:
    """Mirror the pinned upstream Django line parser, including multiline cases."""
    statuses: dict[str, str] = {}
    previous: str | None = None
    for raw_line in log.split("\n"):
        line = raw_line.strip()
        if "--version is equivalent to version" in line:
            statuses["--version is equivalent to version"] = "PASSED"
        if " ... " in line:
            previous = line.split(" ... ")[0]
        for suffix in (" ... ok", " ... OK", " ...  OK"):
            if line.endswith(suffix):
                if line.startswith("Applying sites.0002_alter_domain_unique...test_no_migrations"):
                    line = line.split("...", 1)[-1].strip()
                statuses[line.rsplit(suffix, 1)[0]] = "PASSED"
                break
        if " ... skipped" in line:
            statuses[line.split(" ... skipped")[0]] = "SKIPPED"
        if line.endswith(" ... FAIL"):
            statuses[line.split(" ... FAIL")[0]] = "FAILED"
        if line.startswith("FAIL:"):
            fields = line.split()
            if len(fields) < 2:
                raise VerifierError("DJANGO_TEST_LOG_MALFORMED")
            statuses[fields[1].strip()] = "FAILED"
        if line.endswith(" ... ERROR"):
            statuses[line.split(" ... ERROR")[0]] = "ERROR"
        if line.startswith("ERROR:"):
            fields = line.split()
            if len(fields) < 2:
                raise VerifierError("DJANGO_TEST_LOG_MALFORMED")
            statuses[fields[1].strip()] = "ERROR"
        if line.lstrip().startswith("ok") and previous is not None:
            statuses[previous] = "PASSED"
    # The pinned parser recognizes these three interrupted Django output forms.
    multiline_patterns = (
        r"^(.*?)\s\.\.\.\sTesting\ against\ Django\ installed\ in\ ((?s:.*?))\ silenced\)\.\nok$",
        r"^(.*?)\s\.\.\.\sInternal\ Server\ Error:\ \/(.*)\/\nok$",
        r"^(.*?)\s\.\.\.\sSystem check identified no issues \(0 silenced\)\nok$",
    )
    for pattern in multiline_patterns:
        for match in re.finditer(pattern, log, re.MULTILINE):
            statuses[match.group(1)] = "PASSED"
    return statuses


def _status_map(log: str) -> dict[str, str]:
    if any(marker in log for marker in BAD_LOG_MARKERS):
        raise VerifierError("DJANGO_EVALUATION_ERROR_MARKER")
    if log.count(START_MARKER) != 1 or log.count(END_MARKER) != 1:
        raise VerifierError("DJANGO_TEST_MARKERS_INCOMPLETE")
    start = log.index(START_MARKER) + len(START_MARKER)
    end = log.index(END_MARKER)
    if end < start:
        raise VerifierError("DJANGO_TEST_MARKERS_OUT_OF_ORDER")
    statuses = parse_log_django(log[start:end])
    if not statuses:
        statuses = parse_log_django(log)
    if any(status not in TEST_STATUSES for status in statuses.values()):
        raise VerifierError("DJANGO_TEST_STATUS_INVALID")
    return statuses


def _selection_digest(case: str) -> str:
    value = {"fail_to_pass": [case], "pass_to_pass": []}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return _digest(encoded)


def score_locked_log(log: str) -> dict[str, Any]:
    """Find the private expected test by digest, never by a public Run argv."""
    statuses = _status_map(log)
    expected = [case for case in statuses if _selection_digest(case) == SELECTION_SHA256]
    if len(expected) != 1:
        raise VerifierError("DJANGO_EXPECTED_TEST_MISSING")
    return _grade_status_map(statuses, expected, [])


def score_log(log: str, fail_to_pass: list[str], pass_to_pass: list[str]) -> dict[str, Any]:
    """Apply pinned pass-and-fail scoring, refusing incomplete expected evidence."""
    return _grade_status_map(_status_map(log), fail_to_pass, pass_to_pass)


def _grade_status_map(
    statuses: dict[str, str], fail_to_pass: list[str], pass_to_pass: list[str]
) -> dict[str, Any]:
    expected = set(fail_to_pass) | set(pass_to_pass)
    if set(fail_to_pass) & set(pass_to_pass):
        raise VerifierError("DJANGO_TEST_SELECTION_OVERLAP")
    if not expected <= statuses.keys():
        raise VerifierError("DJANGO_EXPECTED_TEST_MISSING")
    if any(statuses[test] in {"SKIPPED", "XFAIL"} for test in expected):
        # The upstream pass-and-fail helper does not count SKIPPED, silently
        # reducing the denominator. The native oracle also rejects XFAIL here.
        raise VerifierError("DJANGO_EXPECTED_TEST_INCONCLUSIVE")
    report: dict[str, dict[str, list[str]]] = {}
    for category, cases in (("FAIL_TO_PASS", fail_to_pass), ("PASS_TO_PASS", pass_to_pass)):
        report[category] = {
            "success": [case for case in cases if statuses[case] == "PASSED"],
            "failure": [case for case in cases if statuses[case] in {"FAILED", "ERROR"}],
        }
    report["FAIL_TO_FAIL"] = {"success": [], "failure": []}
    report["PASS_TO_FAIL"] = {"success": [], "failure": []}
    resolved = not report["FAIL_TO_PASS"]["failure"] and not report["PASS_TO_PASS"]["failure"]
    return {
        "status_map": statuses,
        "tests_status": report,
        "missing_expected": [],
        "resolved": resolved,
    }


def _git(workspace: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerifierError("DJANGO_GIT_INSPECTION_FAILED") from exc
    if result.returncode != 0:
        raise VerifierError("DJANGO_GIT_INSPECTION_FAILED")
    return result.stdout.strip()


def _validate_workspace(workspace: Path) -> None:
    if workspace.is_symlink() or not workspace.is_dir():
        raise VerifierError("DJANGO_WORKSPACE_MISSING")
    if _git(workspace, "rev-parse", "--verify", "HEAD") != IMAGE_HEAD:
        raise VerifierError("DJANGO_IMAGE_HEAD_MISMATCH")
    if _git(workspace, "status", "--porcelain=v1", "--untracked-files=all"):
        raise VerifierError("DJANGO_WORKSPACE_DIRTY")


def _apply_patch(workspace: Path, patch: Path) -> bool:
    commands = (
        ("git", "apply", "--verbose", str(patch)),
        ("git", "apply", "--verbose", "--reject", str(patch)),
        ("patch", "--batch", "--fuzz=5", "-p1", "-i", str(patch)),
    )
    for command in commands:
        try:
            applied = subprocess.run(
                command,
                cwd=workspace,
                env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VerifierError("DJANGO_PATCH_TOOL_FAILED") from exc
        if applied.returncode == 0:
            return True
    return False


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise VerifierError("DJANGO_EVALUATION_CLEANUP_FAILED") from exc


def _evaluate(eval_script: Path, workspace: Path, log: Path, timeout_seconds: int) -> int:
    """Capture at most 16 MiB while enforcing one wall-clock deadline."""
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    finished = False
    deadline = time.monotonic() + timeout_seconds
    try:
        with log.open("xb") as output:
            process = subprocess.Popen(
                ["/bin/bash", str(eval_script)],
                cwd=workspace,
                env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            if process.stdout is None:
                raise VerifierError("DJANGO_EVALUATION_START_FAILED")
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            written = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise VerifierError("DJANGO_EVALUATION_TIMEOUT")
                if not selector.select(min(remaining, 0.25)):
                    continue
                chunk = os.read(process.stdout.fileno(), 64 << 10)
                if not chunk:
                    break
                if written + len(chunk) > MAX_LOG_BYTES:
                    raise VerifierError("DJANGO_TEST_LOG_OVERSIZED")
                output.write(chunk)
                written += len(chunk)
            remaining = max(0.0, deadline - time.monotonic())
            try:
                exit_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise VerifierError("DJANGO_EVALUATION_TIMEOUT") from exc
            finished = True
            return exit_code
    except OSError as exc:
        raise VerifierError("DJANGO_EVALUATION_START_FAILED") from exc
    finally:
        if selector is not None:
            selector.close()
        if process is not None and not finished:
            _stop_process_group(process)
        if process is not None and process.stdout is not None:
            process.stdout.close()


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )


def _unscored_result(candidate_digest: str, classification: str, started_at: str) -> dict[str, Any]:
    empty = classification == "empty_patch_unscored"
    return {
        "schema_version": RESULT_SCHEMA,
        "candidate_digest": candidate_digest,
        "classification": classification,
        "patch_successfully_applied": None if empty else False,
        "resolved": False,
        "score": None,
        "diagnostic_code": "SWEBENCH_EMPTY_PATCH" if empty else "SWEBENCH_PATCH_APPLY_FAILED",
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "eval_exit_code": None,
        "test_output_sha256": _digest(b""),
        "status_map": None,
        "tests_status": None,
        "missing_expected": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--candidate-digest", required=True)
    parser.add_argument("--eval-script", type=Path, required=True)
    parser.add_argument("--eval-timeout-seconds", type=int, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not _hex_digest(args.candidate_digest) or not _hex_digest(args.candidate_sha256):
            raise VerifierError("DJANGO_CANDIDATE_DIGEST_INVALID")
        if args.eval_timeout_seconds != 1800:
            raise VerifierError("DJANGO_EVALUATION_TIMEOUT_INVALID")
        _validate_workspace(args.workspace)
        candidate = _verified_file(args.candidate, sha256=args.candidate_sha256)
        _verified_file(args.eval_script, sha256=EVAL_SCRIPT_SHA256)
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.log.parent.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc).isoformat()
        if not candidate:
            args.log.write_bytes(b"")
            _write_result(
                args.result,
                _unscored_result(args.candidate_digest, "empty_patch_unscored", started_at),
            )
            return 0
        if not _apply_patch(args.workspace, args.candidate):
            args.log.write_bytes(b"")
            _write_result(
                args.result,
                _unscored_result(args.candidate_digest, "patch_apply_failed_unscored", started_at),
            )
            return 0
        eval_exit_code = _evaluate(
            args.eval_script, args.workspace, args.log, args.eval_timeout_seconds
        )
        log_bytes = args.log.read_bytes()
        try:
            log_text = log_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise VerifierError("DJANGO_TEST_LOG_ENCODING_INVALID") from exc
        grade = score_locked_log(log_text)
        resolved = grade["resolved"] is True
        _write_result(
            args.result,
            {
                "schema_version": RESULT_SCHEMA,
                "candidate_digest": args.candidate_digest,
                "classification": "scored",
                "patch_successfully_applied": True,
                "resolved": resolved,
                "score": 1.0 if resolved else 0.0,
                "diagnostic_code": "" if resolved else "SWEBENCH_TESTS_FAILED",
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "eval_exit_code": eval_exit_code,
                "test_output_sha256": _digest(log_bytes),
                **grade,
            },
        )
        return 0
    except VerifierError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
