"""Deterministic workspace archive creation and fail-closed extraction."""

from __future__ import annotations

import argparse
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath

from axrun.errors import ContractError

MAX_ARCHIVE_BYTES = 64 << 20
MAX_ENTRIES = 10_000
MAX_EXTRACTED_BYTES = 512 << 20
MAX_PATH_LENGTH = 240


def create_workspace_archive(root: Path, output: Path) -> None:
    root = root.resolve()
    if not root.is_dir():
        raise ContractError("workspace archive root must be a directory")
    output_absolute = output.absolute()
    if output_absolute == root or output_absolute.is_relative_to(root):
        raise ContractError("workspace archive output must be outside its root")
    entries = sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix())
    if len(entries) > MAX_ENTRIES:
        raise ContractError("workspace archive exceeds max entries")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as archive:
        for path in entries:
            relative = path.relative_to(root).as_posix()
            _validate_name(relative)
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
            ):
                raise ContractError(f"workspace archive rejects special entry: {relative}")
            member = tarfile.TarInfo(relative)
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.mtime = 0
            member.mode = stat.S_IMODE(info.st_mode) & 0o777
            if path.is_dir():
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            else:
                member.size = info.st_size
                with path.open("rb") as stream:
                    archive.addfile(member, stream)
    if output.stat().st_size > MAX_ARCHIVE_BYTES:
        output.unlink(missing_ok=True)
        raise ContractError("workspace archive exceeds max bytes")


def extract_workspace_archive(source: Path, destination: Path) -> None:
    if source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ContractError("workspace archive exceeds max bytes")
    if destination.is_symlink():
        raise ContractError("workspace archive destination must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    total = 0
    names: set[str] = set()
    with tarfile.open(source, "r:") as archive:
        members = archive.getmembers()
        if len(members) > MAX_ENTRIES:
            raise ContractError("workspace archive exceeds max entries")
        for member in members:
            _validate_name(member.name)
            if member.name in names:
                raise ContractError(f"workspace archive contains duplicate entry: {member.name}")
            names.add(member.name)
            if not (member.isfile() or member.isdir()):
                raise ContractError(f"workspace archive rejects special entry: {member.name}")
            total += member.size
            if total > MAX_EXTRACTED_BYTES:
                raise ContractError("workspace archive exceeds max extracted bytes")
            target = destination / member.name
            _validate_target(destination, target)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                os.chmod(target, member.mode & 0o777)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise ContractError("workspace archive file payload is missing")
            with target.open("wb") as output:
                while chunk := stream.read(1024 * 1024):
                    output.write(chunk)
            os.chmod(target, member.mode & 0o777)


def _validate_name(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > MAX_PATH_LENGTH
        or "\0" in value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or path.as_posix() != value
    ):
        raise ContractError(f"unsafe workspace archive path: {value}")


def _validate_target(destination: Path, target: Path) -> None:
    if not target.resolve(strict=False).is_relative_to(destination):
        raise ContractError(f"workspace archive target escapes destination: {target.name}")
    relative = target.relative_to(destination)
    current = destination
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ContractError(f"workspace archive target crosses symlink: {relative.as_posix()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("create", "extract"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.mode == "create":
        create_workspace_archive(args.source, args.destination)
    else:
        extract_workspace_archive(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
