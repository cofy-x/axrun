#!/usr/bin/env python3
"""Replace Bun's PT_INTERP in place without changing the ELF file length."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("source_interp")
    args = parser.parse_args()
    data = bytearray(args.path.read_bytes())
    old = args.source_interp.encode("ascii") + b"\0"
    new = b"/__claude_code/l\0"
    if data[:6] != b"\x7fELF\x02\x01":
        raise SystemExit(f"expected a little-endian ELF64 file: {args.path}")
    header_offset = struct.unpack_from("<Q", data, 32)[0]
    header_size = struct.unpack_from("<H", data, 54)[0]
    header_count = struct.unpack_from("<H", data, 56)[0]
    if header_size != 56:
        raise SystemExit(f"unexpected ELF64 program header size: {header_size}")
    interpreters: list[tuple[int, int]] = []
    for index in range(header_count):
        offset = header_offset + index * header_size
        if struct.unpack_from("<I", data, offset)[0] == 3:
            interpreters.append(
                (
                    struct.unpack_from("<Q", data, offset + 8)[0],
                    struct.unpack_from("<Q", data, offset + 32)[0],
                )
            )
    if len(interpreters) != 1:
        raise SystemExit(f"expected one PT_INTERP in {args.path}, got {len(interpreters)}")
    file_offset, file_size = interpreters[0]
    if bytes(data[file_offset : file_offset + file_size]) != old:
        raise SystemExit(f"unexpected PT_INTERP contents in {args.path}")
    if len(new) > file_size:
        raise SystemExit("replacement interpreter does not fit PT_INTERP")
    data[file_offset : file_offset + file_size] = new.ljust(file_size, b"\0")
    args.path.write_bytes(data)


if __name__ == "__main__":
    main()
