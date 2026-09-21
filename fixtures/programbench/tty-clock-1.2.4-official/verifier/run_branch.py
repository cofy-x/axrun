#!/usr/bin/env python3
"""Execute one locked ProgramBench test branch and emit body-free structured results."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract(archive: Path, workspace: Path) -> None:
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        for member in members:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or member.isdev()
                or member.isfifo()
            ):
                raise ValueError("unsafe branch archive entry")
            destination = (workspace / Path(*relative.parts)).resolve()
            if not destination.is_relative_to(workspace.resolve()):
                raise ValueError("branch archive entry escapes workspace")
        stream.extractall(workspace, filter="data")


def _parse_results(path: Path) -> list[dict[str, object]]:
    root = ET.parse(path).getroot()
    cases = root.iter("testcase")
    results: list[dict[str, object]] = []
    for case in cases:
        classname = case.attrib.get("classname", "")
        case_name = case.attrib.get("name", "")
        name = f"{classname}.{case_name}" if classname else case_name
        if not name:
            continue
        result_children = [child for child in case if child.tag in {"skipped", "failure", "error"}]
        if len(result_children) > 1 and len({child.tag for child in result_children}) == 1:
            result_children = result_children[:1]
        if not result_children:
            status = "passed"
        elif len(result_children) != 1:
            status = "system_error"
        else:
            status = {
                "skipped": "skipped",
                "failure": "failure",
                "error": "error",
            }[result_children[0].tag]
        results.append({"name": name, "status": status})
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True)
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--stash", type=Path, required=True)
    parser.add_argument("--executable-sha256", required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        _extract(args.asset, args.workspace)
        executable = args.workspace / "executable"
        executable.unlink(missing_ok=True)
        shutil.move(args.stash, executable)
        executable.chmod(executable.stat().st_mode | 0o111)
        if _digest(executable) != args.executable_sha256:
            raise ValueError("executable digest mismatch")
        results_path = args.workspace / "eval" / "results.xml"
        results_path.unlink(missing_ok=True)
        run_script = args.workspace / "eval" / "run.sh"
        if not run_script.is_file() or run_script.is_symlink():
            raise ValueError("branch run script missing")
        run_script.chmod(run_script.stat().st_mode | 0o100)
        run_script.write_text(
            run_script.read_text(encoding="utf-8").replace(
                "--timeout-method=thread", "--timeout-method=signal"
            ),
            encoding="utf-8",
        )
        environment = {**os.environ, "PYTEST_ADDOPTS": "--max-worker-restart=4"}
        subprocess.run(
            ["./eval/run.sh"],
            cwd=args.workspace,
            env=environment,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3600,
        )
        if not results_path.is_file() or results_path.is_symlink():
            raise ValueError("results XML missing")
        observed = _parse_results(results_path)
    except (OSError, ValueError, tarfile.TarError, ET.ParseError, subprocess.TimeoutExpired) as exc:
        _write(
            args.result,
            {
                "schema_version": 1,
                "branch": args.branch,
                "status": "branch_error",
                "reason_code": type(exc).__name__.lower(),
                "tests": [],
            },
        )
        return 0
    _write(
        args.result,
        {
            "schema_version": 1,
            "branch": args.branch,
            "status": "completed",
            "reason_code": "",
            "tests": observed,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
