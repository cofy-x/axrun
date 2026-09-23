#!/usr/bin/env python3
"""Make the copied glibc loader resolve only mount-rooted library locations."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("deb_lib_arch")
    parser.add_argument("lib_alias")
    parser.add_argument("usr_alias")
    args = parser.parse_args()
    data = args.path.read_bytes()
    replacements = (
        (
            f"/usr/lib/{args.deb_lib_arch}/".encode(),
            f"/__claude_code/{args.usr_alias}/".encode(),
            2,
        ),
        (
            f"/lib/{args.deb_lib_arch}/".encode(),
            f"/__claude_code/{args.lib_alias}/".encode(),
            2,
        ),
        (b"/etc/ld.so.cache", b"/__claude_code/c", 2),
    )
    for old, new, expected_count in replacements:
        if len(old) != len(new):
            raise SystemExit(f"loader replacement length mismatch: {old!r} -> {new!r}")
        if data.count(old) != expected_count:
            raise SystemExit(f"unexpected loader string count for {old!r}")
        data = data.replace(old, new)
    args.path.write_bytes(data)


if __name__ == "__main__":
    main()
