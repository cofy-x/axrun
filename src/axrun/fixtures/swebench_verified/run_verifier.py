"""Self-contained offline verifier for the minimal Django Verified vertical."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import cast


def _django_statuses(log: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    previous = ""
    for raw_line in log.splitlines():
        line = raw_line.strip()
        if " ... " in line:
            previous = line.split(" ... ", 1)[0]
        for suffix in (" ... ok", " ... OK", " ...  OK"):
            if line.endswith(suffix):
                statuses[line.rsplit(suffix, 1)[0]] = "PASSED"
                break
        if " ... skipped" in line:
            statuses[line.split(" ... skipped", 1)[0]] = "SKIPPED"
        if line.endswith(" ... FAIL"):
            statuses[line.rsplit(" ... FAIL", 1)[0]] = "FAILED"
        elif line.startswith("FAIL:") and len(line.split()) > 1:
            statuses[line.split()[1]] = "FAILED"
        if line.endswith(" ... ERROR"):
            statuses[line.rsplit(" ... ERROR", 1)[0]] = "ERROR"
        elif line.startswith("ERROR:") and len(line.split()) > 1:
            statuses[line.split()[1]] = "ERROR"
        if line.startswith("ok") and previous:
            statuses[previous] = "PASSED"
    return statuses


def _tests(value: str) -> list[str]:
    parsed: object = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("test selection must be a JSON string array")
    items = cast(list[object], parsed)
    if any(not isinstance(item, str) for item in items):
        raise ValueError("test selection must be a JSON string array")
    return list(cast(list[str], items))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-digest", required=True)
    parser.add_argument("--eval-script", type=Path, required=True)
    parser.add_argument("--log-parser", required=True)
    parser.add_argument("--fail-to-pass", required=True)
    parser.add_argument("--pass-to-pass", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if args.log_parser != "parse_log_django":
        return 2
    fail_to_pass = _tests(args.fail_to_pass)
    pass_to_pass = _tests(args.pass_to_pass)
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC).isoformat()
    actual_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.workspace, text=True, timeout=10
    ).strip()
    if actual_commit != args.base_commit:
        return 2
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=args.workspace,
        text=True,
        timeout=10,
    )
    if status:
        return 2
    with args.log.open("w", encoding="utf-8") as log:
        if args.candidate.stat().st_size:
            apply = subprocess.run(
                ["git", "apply", "--binary", str(args.candidate)],
                cwd=args.workspace,
                env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=60,
            )
            if apply.returncode != 0:
                return 2
        evaluation = subprocess.run(
            ["bash", str(args.eval_script)],
            cwd=args.workspace,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=7000,
        )
    log_bytes = args.log.read_bytes()
    log_text = log_bytes.decode(errors="replace")
    if ">>>>> Start Test Output" not in log_text or ">>>>> End Test Output" not in log_text:
        return 2
    test_output = log_text.split(">>>>> Start Test Output", 1)[1].split(">>>>> End Test Output", 1)[
        0
    ]
    statuses = _django_statuses(test_output)
    passing = {"PASSED"}
    maintained = {"PASSED", "SKIPPED"}
    resolved = all(statuses.get(test) in passing for test in fail_to_pass) and all(
        statuses.get(test) in maintained for test in pass_to_pass
    )
    args.result.write_text(
        json.dumps(
            {
                "candidate_digest": args.candidate_digest,
                "resolved": resolved,
                "score": 1.0 if resolved else 0.0,
                "diagnostic_code": "" if resolved else "SWEBENCH_TESTS_FAILED",
                "started_at": started_at,
                "completed_at": datetime.now(UTC).isoformat(),
                "eval_exit_code": evaluation.returncode,
                "output_digest": hashlib.sha256(log_bytes).hexdigest(),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
