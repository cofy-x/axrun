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


class EvaluatorError(Exception):
    """Body-free infrastructure diagnostic, never a candidate score."""


def _offline_script(source: str, branch: str = "89bbe1810fa3") -> str:
    # Only these two locked setup commands move to canonical image construction.
    # Refuse upstream drift rather than silently removing arbitrary shell commands.
    commands = {
        "89bbe1810fa3": (
            "python3 -m pip install -q --upgrade pip",
            "python3 -m pip install -q pytest pytest-timeout pytest-xdist pytest-dependency",
        ),
        "9951be903ea4": (
            "python3 -m pip install --upgrade pip >/dev/null",
            "python3 -m pip install -q pytest pytest-xdist pytest-timeout",
        ),
        "b2bd72001100": (
            "python3 -m pip install -q --upgrade pip",
            "python3 -m pip install -q pytest pytest-xdist pytest-timeout",
        ),
        "b48a2e05f04f": (
            "python3 -m pip -q install --upgrade pip >/dev/null",
            "python3 -m pip -q install pytest pytest-timeout pytest-dependency libtmux >/dev/null",
        ),
        "dc1d19eea619": ("pip3 install -q pytest pytest-timeout pytest-xdist 2>/dev/null || true",),
        "ed5c2b1ffc48": ("pip install pytest pytest-timeout pytest-xdist -q 2>/dev/null || true",),
    }.get(branch)
    if commands is None:
        raise EvaluatorError("evaluator_branch_unknown")
    lines = source.splitlines()
    for command in commands:
        if lines.count(command) != 1:
            raise EvaluatorError("evaluator_setup_contract_changed")
        lines.remove(command)
    return "\n".join(lines).replace("--timeout-method=thread", "--timeout-method=signal") + "\n"


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
    parser.add_argument("--dependency-lock-sha256", required=True)
    args = parser.parse_args()
    try:
        checked = subprocess.run(
            [
                "python3",
                "/opt/axrun-programbench/check_environment.py",
                args.dependency_lock_sha256,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        if checked.returncode != 0:
            raise EvaluatorError("evaluator_environment_invalid")
        _extract(args.asset, args.workspace)
        executable = args.workspace / "executable"
        executable.unlink(missing_ok=True)
        shutil.move(args.stash, executable)
        executable.chmod(executable.stat().st_mode | 0o111)
        if _digest(executable) != args.executable_sha256:
            raise EvaluatorError("executable_digest_mismatch")
        results_path = args.workspace / "eval" / "results.xml"
        results_path.unlink(missing_ok=True)
        run_script = args.workspace / "eval" / "run.sh"
        if not run_script.is_file() or run_script.is_symlink():
            raise EvaluatorError("evaluator_script_missing")
        run_script.chmod(run_script.stat().st_mode | 0o100)
        run_script.write_text(
            _offline_script(run_script.read_text(encoding="utf-8"), args.branch),
            encoding="utf-8",
        )
        environment = {
            **os.environ,
            "PYTEST_ADDOPTS": "--max-worker-restart=4 --reruns=2 --reruns-delay=1",
        }
        completed = subprocess.run(
            ["./eval/run.sh"],
            cwd=args.workspace,
            env=environment,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3600,
        )
        # pytest 1 means test failure; other statuses mean invocation/infrastructure
        # failure even when it wrote a partial XML file.
        if completed.returncode not in (0, 1):
            raise EvaluatorError("evaluator_process_failed")
        if not results_path.is_file() or results_path.is_symlink():
            raise EvaluatorError("evaluator_results_missing")
        observed = _parse_results(results_path)
        if not observed:
            raise EvaluatorError("evaluator_results_empty")
    except (
        EvaluatorError,
        OSError,
        ValueError,
        tarfile.TarError,
        ET.ParseError,
        subprocess.TimeoutExpired,
    ) as exc:
        reason = (
            str(exc)
            if isinstance(exc, EvaluatorError)
            else {
                subprocess.TimeoutExpired: "evaluator_deadline_exceeded",
                ET.ParseError: "evaluator_results_invalid",
            }.get(type(exc), "evaluator_input_or_io_invalid")
        )
        _write(
            args.result,
            {
                "schema_version": 1,
                "branch": args.branch,
                "status": "infrastructure_error",
                "reason_code": reason,
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
