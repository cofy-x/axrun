"""Self-contained verifier uploaded into a fresh synthetic verification Allocation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


def _run(
    argv: list[str], *, cwd: Path, log: TextIO, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        check=check,
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-digest", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()  # noqa: UP017 -- sandbox Python 3.10
    with args.log.open("w", encoding="utf-8") as log:
        actual_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=args.workspace, text=True, timeout=10
        ).strip()
        if actual_commit != args.base_commit:
            print(
                f"base commit mismatch: expected {args.base_commit}, got {actual_commit}",
                file=log,
            )
            return 2
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=args.workspace,
            text=True,
            timeout=10,
        )
        if status:
            print("task image workspace is not clean", file=log)
            return 2
        patch_bytes = args.candidate.read_bytes()
        apply_result = None
        if patch_bytes:
            apply_result = _run(
                ["git", "apply", "--binary", str(args.candidate)],
                cwd=args.workspace,
                log=log,
            )
        if apply_result is not None and apply_result.returncode != 0:
            resolved = False
            diagnostic = "SYNTHETIC_PATCH_REJECTED"
            test_exit_code = None
        else:
            test_result = _run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                cwd=args.workspace,
                log=log,
            )
            resolved = test_result.returncode == 0
            diagnostic = "" if resolved else "SYNTHETIC_TESTS_FAILED"
            test_exit_code = test_result.returncode
    args.result.write_text(
        json.dumps(
            {
                "candidate_digest": args.candidate_digest,
                "resolved": resolved,
                "score": 1.0 if resolved else 0.0,
                "diagnostic_code": diagnostic,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                "test_exit_code": test_exit_code,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
