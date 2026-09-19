from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def _run(workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "greeter.py", *arguments],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--candidate-digest", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    started = datetime.now(UTC).isoformat()
    failures: list[str] = []
    program = args.workspace / "greeter.py"
    if not program.is_file() or program.is_symlink():
        failures.append("greeter.py is missing or is not a regular file")
    else:
        cases = (
            (("Ada",), 0, "Hello, Ada!\n", ""),
            (("--shout", "Ada Lovelace"), 0, "HELLO, ADA LOVELACE!\n", ""),
            ((), 2, "", "usage: greeter.py [--shout] NAME\n"),
            (("",), 2, "", "name must not be empty\n"),
        )
        for arguments, exit_code, stdout, stderr in cases:
            completed = _run(args.workspace, *arguments)
            if (completed.returncode, completed.stdout, completed.stderr) != (
                exit_code,
                stdout,
                stderr,
            ):
                failures.append(f"case {arguments!r} did not match the command contract")
    resolved = not failures
    completed_at = datetime.now(UTC).isoformat()
    payload = {
        "resolved": resolved,
        "score": 1.0 if resolved else 0.0,
        "candidate_digest": args.candidate_digest,
        "diagnostic_code": "" if resolved else "greenfield_contract_failed",
        "started_at": started,
        "completed_at": completed_at,
        "failed_checks": failures,
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    args.log.write_text("\n".join(failures) + ("\n" if failures else "passed\n"), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
