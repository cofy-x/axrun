#!/usr/bin/env python3
"""ProgramBench 1.2.4-compatible compile phase for the locked tty-clock instance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

from axrun.candidates.archive import extract_workspace_archive


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _clear(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--stash", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    _clear(args.workspace)
    extract_workspace_archive(args.candidate, args.workspace)
    stale = args.workspace / "executable"
    if stale.exists() or stale.is_symlink():
        if stale.is_dir() and not stale.is_symlink():
            shutil.rmtree(stale)
        else:
            stale.unlink()

    if not (args.workspace / ".git").exists():
        environment = {
            **os.environ,
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }
        commands = (
            ("git", "-c", "init.defaultBranch=gold", "init", "-q"),
            ("git", "-c", "user.email=gold@local", "-c", "user.name=gold", "add", "-A"),
            (
                "git",
                "-c",
                "user.email=gold@local",
                "-c",
                "user.name=gold",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "gold",
            ),
        )
        for command in commands:
            completed = subprocess.run(command, cwd=args.workspace, env=environment, check=False)
            if completed.returncode != 0:
                _write(
                    args.result, {"status": "compile_error", "diagnostic_code": "seed_git_failed"}
                )
                return 21

    compile_script = args.workspace / "compile.sh"
    if not compile_script.is_file() or compile_script.is_symlink():
        _write(
            args.result, {"status": "compile_error", "diagnostic_code": "compile_script_missing"}
        )
        return 22
    compile_script.chmod(compile_script.stat().st_mode | stat.S_IXUSR)
    completed = subprocess.run(
        ["./compile.sh"],
        cwd=args.workspace,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=900,
    )
    if completed.returncode != 0:
        _write(
            args.result,
            {
                "status": "compile_error",
                "diagnostic_code": "compile_failed",
                "compile_exit_code": completed.returncode,
            },
        )
        return 23
    executable = args.workspace / "executable"
    if not executable.is_file() or executable.is_symlink():
        _write(args.result, {"status": "compile_error", "diagnostic_code": "executable_missing"})
        return 24
    mode = stat.S_IMODE(executable.stat().st_mode)
    if mode & 0o111 == 0:
        _write(
            args.result, {"status": "compile_error", "diagnostic_code": "executable_not_executable"}
        )
        return 25
    args.stash.parent.mkdir(parents=True, exist_ok=True)
    os.replace(executable, args.stash)
    digest = _digest(args.stash)
    _write(
        args.result,
        {
            "status": "succeeded",
            "diagnostic_code": "",
            "executable_sha256": digest,
            "executable_mode": mode,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
