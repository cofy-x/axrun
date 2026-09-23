from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

from axrun.cli import _parser
from axrun.datasets import ProgramBenchOfficialSingleResolver
from axrun.models import HarnessSpec
from axrun.trajectories.schema import TrajectoryEvent
from axrun.verification.programbench_provenance import _elf_count, tool_call_signals


def _call(sequence: int, name: str, arguments: dict[str, str]) -> TrajectoryEvent:
    return TrajectoryEvent(
        schema_version=1,
        sequence=sequence,
        event_id=f"event-{sequence:08d}",
        timestamp=None,
        kind="tool_call",
        actor="assistant",
        turn_id="turn-1",
        parent_event_id=None,
        model="model",
        data={"tool_call_id": f"call-{sequence}", "name": name, "arguments": arguments},
    )


def test_review_signals_never_echo_command_or_secret() -> None:
    marker = "DO-NOT-PRINT-PRIVATE-COMMAND"
    events = (
        _call(1, "Bash", {"command": f"curl https://example.invalid/{marker}"}),
        _call(2, "Bash", {"command": "git clone https://example.invalid/source"}),
        _call(3, "Bash", {"command": "python3 -m pip install package"}),
        _call(4, "WebFetch", {"url": f"https://example.invalid/{marker}"}),
    )
    signals = tool_call_signals(events)
    assert signals == {
        "network_retrieval_calls": 2,
        "package_registry_calls": 1,
        "web_tool_calls": 1,
    }
    assert marker not in json.dumps(signals)


def test_review_counts_bundled_elf_without_exposing_archive_paths(tmp_path: Path) -> None:
    path = tmp_path / "workspace.tar"
    with tarfile.open(path, "w") as archive:
        for name, content in (("private/path/tool", b"\x7fELFdata"), ("compile.sh", b"#!/bin/sh")):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    assert _elf_count(path) == 1


def test_seqtk_v2_prompt_locks_source_provenance_boundary() -> None:
    root = Path(__file__).parents[1] / "fixtures/programbench/seqtk-1.2.4-official"
    row = json.loads((root / "row.json").read_text(encoding="utf-8"))
    episode = ProgramBenchOfficialSingleResolver().resolve(
        row,
        source_dir=root,
        episode_id="seqtk-provenance-test",
        inference_environment_id="inference",
        verification_environment_id="verification",
        harness=HarnessSpec("static-candidate", "1"),
        verification_image="registry.invalid/evaluator@sha256:" + "a" * 64,
    )
    assert row["dataset_version"] == "programbench-1.2.4-seqtk-94e7070-v2"
    assert episode.task_id == "lh3__seqtk.94e7070"
    prompt = (root / "problem.md").read_text(encoding="utf-8")
    for phrase in ("bundled documentation", "Do not consult source code", "unit tests"):
        assert phrase in prompt
    assert _parser().parse_args(["review-programbench-provenance", "episode"]).command == (
        "review-programbench-provenance"
    )
