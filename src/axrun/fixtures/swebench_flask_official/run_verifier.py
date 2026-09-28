"""Offline, single-instance Flask verifier run inside a fresh Axern Allocation.

The parser and pass-and-fail grader mirror SWE-bench harness commit
f7bbbb2ccdf479001d6467c9e34af59e44a840f9. This script does not download
assets or import the upstream checkout at runtime. It is not registered until
native-oracle and Axern test-level parity have been demonstrated.
"""

# ruff: noqa: UP017 -- Allocation fixtures must also run on Python 3.10.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

INSTANCE_ID = "pallets__flask-5014"
IMAGE_HEAD = "966bb873e3a1e42d857362a17f5af2533dfd8f46"
EVAL_SCRIPT_SHA256 = "a752d2d3520db71513c263dd476e8da457395a447a346f6b5c18782dc0faf034"
WHEELHOUSE = Path("/opt/axrun-wheelhouse")
WHEELS = {
    "setuptools-70.0.0-py3-none-any.whl": (
        863_432,
        "54faa7f2e8d2d11bcd2c07bed282eef1046b5c080d1c32add737d7b5817b1ad4",
    ),
    "wheel-0.45.1-py3-none-any.whl": (
        72_494,
        "708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248",
    ),
}
TEST_STATUSES = ("FAILED", "PASSED", "SKIPPED", "ERROR", "XFAIL")
PASSING_STATUSES = frozenset(("PASSED", "XFAIL"))
BAD_LOG_MARKERS = (
    ">>>>> Patch Apply Failed",
    ">>>>> Reset Failed",
    ">>>>> Tests Errored",
    ">>>>> Tests Timed Out",
)
START_MARKER = ">>>>> Start Test Output"
END_MARKER = ">>>>> End Test Output"
RESULT_SCHEMA = "axrun.swebench-flask-official-result@1"


class VerifierError(Exception):
    """One stable, caller-safe infrastructure reason code."""


def _hex_digest(value: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _verified_file(path: Path, *, sha256: str, size: int | None = None) -> bytes:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise VerifierError("FLASK_ASSET_NOT_REGULAR")
        if size is not None and metadata.st_size != size:
            raise VerifierError("FLASK_ASSET_SIZE_MISMATCH")
        payload = path.read_bytes()
    except OSError as exc:
        raise VerifierError("FLASK_ASSET_UNAVAILABLE") from exc
    if hashlib.sha256(payload).hexdigest() != sha256:
        raise VerifierError("FLASK_ASSET_DIGEST_MISMATCH")
    return payload


def _expected_tests(value: str) -> list[str]:
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError as exc:
        raise VerifierError("FLASK_TEST_SELECTION_INVALID") from exc
    if not isinstance(parsed, list):
        raise VerifierError("FLASK_TEST_SELECTION_INVALID")
    tests = cast(list[object], parsed)
    if (
        not tests
        or any(not isinstance(item, str) or not item for item in tests)
        or len(tests) != len(set(item for item in tests if isinstance(item, str)))
    ):
        raise VerifierError("FLASK_TEST_SELECTION_INVALID")
    return [item for item in tests if isinstance(item, str)]


def parse_log_flask(log: str) -> dict[str, str]:
    """Pinned upstream ``parse_log_flask = parse_log_pytest`` line semantics."""
    statuses: dict[str, str] = {}
    for line in log.split("\n"):
        if any(line.startswith(status) for status in TEST_STATUSES):
            if line.startswith("FAILED"):
                line = line.replace(" - ", " ")
            fields = line.split()
            if len(fields) > 1:
                statuses[fields[1]] = fields[0]
    return statuses


def score_log(log: str, fail_to_pass: list[str], pass_to_pass: list[str]) -> dict[str, object]:
    """Mirror pinned ``get_logs_eval`` and pass-and-fail report semantics."""
    if any(marker in log for marker in BAD_LOG_MARKERS):
        raise VerifierError("FLASK_EVALUATION_ERROR_MARKER")
    if log.count(START_MARKER) != 1 or log.count(END_MARKER) != 1:
        raise VerifierError("FLASK_TEST_MARKERS_INCOMPLETE")
    before, _, remainder = log.partition(START_MARKER)
    test_output, _, after = remainder.partition(END_MARKER)
    if not after and not log.endswith(END_MARKER):
        raise VerifierError("FLASK_TEST_MARKERS_INCOMPLETE")
    if END_MARKER in before:
        raise VerifierError("FLASK_TEST_MARKERS_OUT_OF_ORDER")
    statuses = parse_log_flask(test_output)
    if not statuses:
        statuses = parse_log_flask(log)
    if any(status not in TEST_STATUSES for status in statuses.values()):
        raise VerifierError("FLASK_TEST_STATUS_INVALID")

    expected = set(fail_to_pass) | set(pass_to_pass)
    if set(fail_to_pass) & set(pass_to_pass):
        raise VerifierError("FLASK_TEST_SELECTION_OVERLAP")
    if any(statuses.get(test) == "SKIPPED" for test in expected):
        # Upstream neither succeeds nor fails SKIPPED, shrinking its denominator.
        # An official-instance acceptance must not silently grade that ambiguity.
        raise VerifierError("FLASK_EXPECTED_TEST_SKIPPED")

    report: dict[str, dict[str, list[str]]] = {}
    for category, tests in (("FAIL_TO_PASS", fail_to_pass), ("PASS_TO_PASS", pass_to_pass)):
        report[category] = {
            "success": [test for test in tests if statuses.get(test) in PASSING_STATUSES],
            "failure": [test for test in tests if statuses.get(test) not in PASSING_STATUSES],
        }
    for category in ("FAIL_TO_FAIL", "PASS_TO_FAIL"):
        report[category] = {"success": [], "failure": []}
    resolved = not report["FAIL_TO_PASS"]["failure"] and not report["PASS_TO_PASS"]["failure"]
    return {
        "status_map": statuses,
        "tests_status": report,
        "missing_expected": sorted(expected - statuses.keys()),
        "resolved": resolved,
    }


def _run_git(workspace: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=workspace,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerifierError("FLASK_GIT_INSPECTION_FAILED") from exc
    if result.returncode != 0:
        raise VerifierError("FLASK_GIT_INSPECTION_FAILED")
    return result.stdout.strip()


def _validate_workspace(workspace: Path) -> None:
    if not workspace.is_dir() or workspace.is_symlink():
        raise VerifierError("FLASK_WORKSPACE_MISSING")
    if _run_git(workspace, "rev-parse", "--verify", "HEAD") != IMAGE_HEAD:
        raise VerifierError("FLASK_IMAGE_HEAD_MISMATCH")
    if _run_git(workspace, "status", "--porcelain=v1", "--untracked-files=all"):
        raise VerifierError("FLASK_WORKSPACE_DIRTY")


def _apply_patch(workspace: Path, patch: Path) -> bool:
    commands = (
        ("git", "apply", "--verbose", str(patch)),
        ("git", "apply", "--verbose", "--reject", str(patch)),
        ("patch", "--batch", "--fuzz=5", "-p1", "-i", str(patch)),
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=workspace,
                env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VerifierError("FLASK_PATCH_TOOL_FAILED") from exc
        if result.returncode == 0:
            return True
    return False


def _evaluate(eval_script: Path, workspace: Path, log: Path, timeout_seconds: int) -> int:
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "PIP_NO_INDEX": "1",
        "PIP_FIND_LINKS": str(WHEELHOUSE),
    }
    try:
        with log.open("xb") as stream:
            result = subprocess.run(
                ["/bin/bash", str(eval_script)],
                cwd=workspace,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout_seconds,
            )
    except subprocess.TimeoutExpired as exc:
        raise VerifierError("FLASK_EVALUATION_TIMEOUT") from exc
    except OSError as exc:
        raise VerifierError("FLASK_EVALUATION_START_FAILED") from exc
    return result.returncode


def _write_result(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--candidate-digest", required=True)
    parser.add_argument("--eval-script", type=Path, required=True)
    parser.add_argument("--fail-to-pass", required=True)
    parser.add_argument("--pass-to-pass", required=True)
    parser.add_argument("--eval-timeout-seconds", type=int, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not _hex_digest(args.candidate_digest) or not _hex_digest(args.candidate_sha256):
            raise VerifierError("FLASK_CANDIDATE_DIGEST_INVALID")
        if not 60 <= args.eval_timeout_seconds <= 3600:
            raise VerifierError("FLASK_EVALUATION_TIMEOUT_INVALID")
        fail_to_pass = _expected_tests(args.fail_to_pass)
        pass_to_pass = _expected_tests(args.pass_to_pass)
        if set(fail_to_pass) & set(pass_to_pass):
            raise VerifierError("FLASK_TEST_SELECTION_OVERLAP")
        _validate_workspace(args.workspace)
        candidate = _verified_file(args.candidate, sha256=args.candidate_sha256)
        _verified_file(args.eval_script, sha256=EVAL_SCRIPT_SHA256)
        for name, (size, digest) in WHEELS.items():
            _verified_file(WHEELHOUSE / name, sha256=digest, size=size)
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.log.parent.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc).isoformat()
        if not candidate:
            args.log.write_bytes(b"")
            _write_result(
                args.result,
                {
                    "schema_version": RESULT_SCHEMA,
                    "candidate_digest": args.candidate_digest,
                    "classification": "empty_patch_unscored",
                    "patch_successfully_applied": None,
                    "resolved": False,
                    "score": None,
                    "diagnostic_code": "SWEBENCH_EMPTY_PATCH",
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "eval_exit_code": None,
                    "test_output_sha256": hashlib.sha256(b"").hexdigest(),
                    "status_map": None,
                    "tests_status": None,
                    "missing_expected": None,
                },
            )
            return 0
        if not _apply_patch(args.workspace, args.candidate):
            args.log.write_bytes(b"")
            _write_result(
                args.result,
                {
                    "schema_version": RESULT_SCHEMA,
                    "candidate_digest": args.candidate_digest,
                    "classification": "patch_apply_failed_unscored",
                    "patch_successfully_applied": False,
                    "resolved": False,
                    "score": None,
                    "diagnostic_code": "SWEBENCH_PATCH_APPLY_FAILED",
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "eval_exit_code": None,
                    "test_output_sha256": hashlib.sha256(b"").hexdigest(),
                    "status_map": None,
                    "tests_status": None,
                    "missing_expected": None,
                },
            )
            return 0
        eval_exit_code = _evaluate(
            args.eval_script, args.workspace, args.log, args.eval_timeout_seconds
        )
        log_bytes = args.log.read_bytes()
        try:
            log_text = log_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise VerifierError("FLASK_TEST_LOG_ENCODING_INVALID") from exc
        grade = score_log(log_text, fail_to_pass, pass_to_pass)
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
                "test_output_sha256": hashlib.sha256(log_bytes).hexdigest(),
                **grade,
            },
        )
        return 0
    except VerifierError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
