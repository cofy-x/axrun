from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def _run(workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["./executable", *arguments],
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
    passed = 0
    total = 3
    stale = args.workspace / "executable"
    stale.unlink(missing_ok=True)
    compile_script = args.workspace / "compile.sh"
    if not compile_script.is_file() or compile_script.is_symlink():
        failures.append("compile.sh is missing or is not a regular file")
    else:
        completed = subprocess.run(
            ["/bin/sh", "./compile.sh"],
            cwd=args.workspace,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            failures.append("compile.sh failed")
        elif not stale.is_file() or stale.is_symlink() or not stale.stat().st_mode & 0o111:
            failures.append("compile.sh did not produce an executable regular file")
        else:
            groups = (
                (("2", "+", "3"), "5\n"),
                (("10", "-", "3"), "7\n"),
                (("4", "*", "3"), "12\n"),
            )
            for arguments, expected in groups:
                result = _run(args.workspace, *arguments)
                if (result.returncode, result.stdout, result.stderr) == (0, expected, ""):
                    passed += 1
                else:
                    failures.append(f"behavior group {arguments[1]} failed")
    resolved = passed == total
    payload = {
        "resolved": resolved,
        "score": passed / total,
        "candidate_digest": args.candidate_digest,
        "diagnostic_code": "" if resolved else "programbench_behavior_failed",
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "passed_behavior_groups": passed,
        "total_behavior_groups": total,
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
