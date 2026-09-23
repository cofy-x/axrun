import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

PATH = Path(__file__).parents[1] / "tools/validation/programbench_seqtk_axern.py"
SPEC = importlib.util.spec_from_file_location("seqtk_axern", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _archive(path: Path, name: str, *, kind: bytes = tarfile.REGTYPE) -> None:
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        if kind == tarfile.REGTYPE:
            member.size = 4
            archive.addfile(member, io.BytesIO(b"data"))
        else:
            member.linkname = "target"
            archive.addfile(member)


def test_locked_candidate_extraction_preserves_regular_file(tmp_path: Path) -> None:
    source = tmp_path / "candidate.tar.gz"
    _archive(source, "compile.sh")

    MODULE._extract_locked_candidate(source, tmp_path / "workspace")

    assert (tmp_path / "workspace" / "compile.sh").read_bytes() == b"data"


@pytest.mark.parametrize(
    ("name", "kind"),
    (("../escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)),
)
def test_locked_candidate_extraction_rejects_unsafe_entries(
    tmp_path: Path, name: str, kind: bytes
) -> None:
    source = tmp_path / "candidate.tar.gz"
    _archive(source, name, kind=kind)

    with pytest.raises(ValueError, match="unsafe entry"):
        MODULE._extract_locked_candidate(source, tmp_path / "workspace")
