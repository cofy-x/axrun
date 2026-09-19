from __future__ import annotations

import hashlib
import os
import tarfile
from pathlib import Path

import pytest

from axrun.candidates import archive
from axrun.errors import ContractError


def _tar(path: Path, member: tarfile.TarInfo, payload: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w") as output:
        if member.isfile():
            import io

            member.size = len(payload)
            output.addfile(member, io.BytesIO(payload))
        else:
            output.addfile(member)


def test_archive_is_byte_deterministic_and_preserves_executable_bit(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    executable = root / "bin" / "hello"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
    executable.chmod(0o755)
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    archive.create_workspace_archive(root, first)
    os.utime(executable, (2_000_000_000, 2_000_000_000))
    archive.create_workspace_archive(root, second)
    assert first.read_bytes() == second.read_bytes()
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    )
    extracted = tmp_path / "extracted"
    archive.extract_workspace_archive(first, extracted)
    assert (extracted / "bin" / "hello").stat().st_mode & 0o111 == 0o111
    assert (extracted / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_archive_rejects_symlink_fifo_and_its_own_output(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "link").symlink_to("elsewhere")
    with pytest.raises(ContractError, match="special entry"):
        archive.create_workspace_archive(root, tmp_path / "link.tar")
    (root / "link").unlink()
    os.mkfifo(root / "pipe")
    with pytest.raises(ContractError, match="special entry"):
        archive.create_workspace_archive(root, tmp_path / "fifo.tar")
    (root / "pipe").unlink()
    with pytest.raises(ContractError, match="outside"):
        archive.create_workspace_archive(root, root / "candidate.tar")


@pytest.mark.parametrize("name", ["/absolute", "../escape", "a/../../escape", "a\\b"])
def test_extraction_rejects_unsafe_paths(tmp_path: Path, name: str) -> None:
    source = tmp_path / "unsafe.tar"
    _tar(source, tarfile.TarInfo(name), b"payload")
    with pytest.raises(ContractError, match="unsafe"):
        archive.extract_workspace_archive(source, tmp_path / "out")


def test_extraction_rejects_symlink_and_existing_symlink_traversal(tmp_path: Path) -> None:
    source = tmp_path / "symlink.tar"
    member = tarfile.TarInfo("link")
    member.type = tarfile.SYMTYPE
    member.linkname = "target"
    _tar(source, member)
    with pytest.raises(ContractError, match="special entry"):
        archive.extract_workspace_archive(source, tmp_path / "out")

    regular = tmp_path / "regular.tar"
    _tar(regular, tarfile.TarInfo("parent/file"), b"payload")
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "parent").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ContractError, match=r"symlink|escapes"):
        archive.extract_workspace_archive(regular, destination)


def test_archive_limits_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "one").write_bytes(b"1234")
    monkeypatch.setattr(archive, "MAX_ENTRIES", 0)
    with pytest.raises(ContractError, match="entries"):
        archive.create_workspace_archive(root, tmp_path / "entries.tar")
    monkeypatch.setattr(archive, "MAX_ENTRIES", 10)
    monkeypatch.setattr(archive, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(ContractError, match="max bytes"):
        archive.create_workspace_archive(root, tmp_path / "bytes.tar")


def test_extracted_size_limit_and_duplicate_names_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large.tar"
    _tar(source, tarfile.TarInfo("file"), b"1234")
    monkeypatch.setattr(archive, "MAX_EXTRACTED_BYTES", 3)
    with pytest.raises(ContractError, match="extracted"):
        archive.extract_workspace_archive(source, tmp_path / "large-out")

    duplicate = tmp_path / "duplicate.tar"
    with tarfile.open(duplicate, "w") as output:
        for _ in range(2):
            member = tarfile.TarInfo("same")
            member.size = 0
            output.addfile(member)
    monkeypatch.setattr(archive, "MAX_EXTRACTED_BYTES", archive.MAX_ARCHIVE_BYTES)
    with pytest.raises(ContractError, match="duplicate"):
        archive.extract_workspace_archive(duplicate, tmp_path / "duplicate-out")
