#!/usr/bin/env python3
"""Validate the artifact lock and emit one closed architecture environment."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any, cast

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLATFORM_KEYS = {
    "node_arch",
    "node_sha256",
    "claude_native_package",
    "claude_native_sha256",
    "deb_lib_arch",
    "source_interp",
    "lib_alias",
    "usr_alias",
}


def required_object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"invalid artifact lock object: {name}")
    return cast(dict[str, Any], value)


def required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise SystemExit(f"invalid artifact lock string: {key}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    parser.add_argument("architecture")
    parser.add_argument("output", type=Path)
    parser.add_argument("--ubuntu-base-image", required=True)
    parser.add_argument("--claude-code-version", required=True)
    parser.add_argument("--claude-runtime-version", required=True)
    parser.add_argument("--node-version", required=True)
    args = parser.parse_args()

    raw: object = json.loads(args.lock.read_text(encoding="utf-8"))
    lock = required_object(raw, "root")
    if (
        set(lock)
        != {
            "schema_version",
            "ubuntu_base_image",
            "claude_code",
            "node",
            "platforms",
        }
        or lock["schema_version"] != 1
    ):
        raise SystemExit("invalid artifact lock root")
    claude = required_object(lock["claude_code"], "claude_code")
    node = required_object(lock["node"], "node")
    platforms = required_object(lock["platforms"], "platforms")
    if set(claude) != {"version", "runtime_version", "package_sha256"}:
        raise SystemExit("invalid claude_code artifact lock")
    if set(node) != {"version"} or set(platforms) != {"amd64", "arm64"}:
        raise SystemExit("artifact lock must contain only amd64 and arm64")
    if args.architecture not in platforms:
        raise SystemExit(f"unsupported TARGETARCH: {args.architecture}")
    platform = required_object(platforms[args.architecture], args.architecture)
    if set(platform) != PLATFORM_KEYS:
        raise SystemExit(f"invalid {args.architecture} artifact lock")

    expected = {
        "ubuntu_base_image": args.ubuntu_base_image,
        "version": args.claude_code_version,
        "runtime_version": args.claude_runtime_version,
        "node_version": args.node_version,
    }
    actual = {
        "ubuntu_base_image": required_string(lock, "ubuntu_base_image"),
        "version": required_string(claude, "version"),
        "runtime_version": required_string(claude, "runtime_version"),
        "node_version": required_string(node, "version"),
    }
    if actual != expected:
        raise SystemExit("Docker build arguments do not match artifacts.lock.json")
    for key in ("package_sha256",):
        if not SHA256.fullmatch(required_string(claude, key)):
            raise SystemExit(f"invalid sha256: claude_code.{key}")
    for key in ("node_sha256", "claude_native_sha256"):
        if not SHA256.fullmatch(required_string(platform, key)):
            raise SystemExit(f"invalid sha256: platforms.{args.architecture}.{key}")

    values = {
        "TARGETARCH": args.architecture,
        "CLAUDE_CODE_VERSION": actual["version"],
        "CLAUDE_RUNTIME_VERSION": actual["runtime_version"],
        "CLAUDE_PACKAGE_SHA256": required_string(claude, "package_sha256"),
        "NODE_VERSION": actual["node_version"],
        "NODE_ARCH": required_string(platform, "node_arch"),
        "NODE_SHA256": required_string(platform, "node_sha256"),
        "CLAUDE_NATIVE_PACKAGE": required_string(platform, "claude_native_package"),
        "CLAUDE_NATIVE_SHA256": required_string(platform, "claude_native_sha256"),
        "DEB_LIB_ARCH": required_string(platform, "deb_lib_arch"),
        "SOURCE_INTERP": required_string(platform, "source_interp"),
        "LIB_ALIAS": required_string(platform, "lib_alias"),
        "USR_ALIAS": required_string(platform, "usr_alias"),
    }
    args.output.write_text(
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items()),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
