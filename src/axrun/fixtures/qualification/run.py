"""Fail-closed stage qualification fixture."""

from __future__ import annotations

import argparse
import json
import os
import platform
import py_compile
import subprocess
import sys
from pathlib import Path


def _output(argv: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(argv, cwd=cwd, text=True, timeout=30).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("inference", "verification"), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--base-commit")
    parser.add_argument("--require-empty-workspace", action="store_true")
    parser.add_argument("--archive-module", type=Path)
    parser.add_argument("--verifier-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--claude", action="store_true")
    args = parser.parse_args()
    if (sys.version_info.major, sys.version_info.minor) < (3, 10):
        raise RuntimeError("task image Python must be 3.10 or newer")
    if not args.workspace.is_dir():
        raise RuntimeError("working directory is missing")
    head = git = None
    workspace_empty = None
    if args.base_commit:
        head = _output(["git", "rev-parse", "HEAD"], cwd=args.workspace)
        git = _output(["git", "--version"])
        if head != args.base_commit:
            raise RuntimeError("task image Git HEAD differs from the episode base commit")
        if _output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=args.workspace):
            raise RuntimeError("task image workspace is not clean")
    elif args.require_empty_workspace:
        workspace_empty = next(args.workspace.iterdir(), None) is None
        if not workspace_empty:
            raise RuntimeError("greenfield workspace is not empty")
    else:
        raise RuntimeError("task qualification policy is missing")
    archive_module = args.archive_module is not None
    verifier_file = args.verifier_file is not None
    if args.archive_module:
        py_compile.compile(str(args.archive_module), doraise=True)
    if args.verifier_file:
        py_compile.compile(str(args.verifier_file), doraise=True)
    payload: dict[str, object] = {
        "schema_version": 1,
        "role": args.role,
        "base_commit": head,
        "git": git,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "working_directory": str(args.workspace),
        "workspace_empty": workspace_empty,
        "archive_module": archive_module,
        "verifier_file": verifier_file,
        "claude": None,
    }
    if args.claude:
        mount = Path("/__claude_code")
        entry = mount / "usr/local/bin/claude"
        node = mount / "opt/claude-code/node/bin/node"
        manifest_path = mount / "opt/claude-code/manifest.json"
        for path in (entry, node, manifest_path):
            if not path.exists():
                raise RuntimeError(f"Claude mount ABI path is missing: {path}")
        probe = mount / ".axrun-write-probe"
        try:
            descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            pass
        else:
            os.close(descriptor)
            probe.unlink(missing_ok=True)
            raise RuntimeError("Claude rootfs mount is writable")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("canonical_mount_target") != "/__claude_code"
            or manifest.get("canonical_entry") != "/__claude_code/usr/local/bin/claude"
        ):
            raise RuntimeError("Claude manifest ABI mismatch")
        claude_version = _output([str(entry), "--version"])
        node_version = _output([str(node), "--version"])
        if "2.1.205 (Claude Code)" not in claude_version or node_version != "v22.23.2":
            raise RuntimeError("Claude or Node version mismatch")
        payload["claude"] = {
            "entry": str(entry),
            "mount_readonly": True,
            "node_version": node_version,
            "version": claude_version,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
