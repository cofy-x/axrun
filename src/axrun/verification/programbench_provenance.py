"""Body-free, advisory provenance review for the locked ProgramBench seqtk run.

This is deliberately separate from the official verifier result. Tool-call heuristics
cannot establish where a model learned source code, so no output means eligible.
"""

from __future__ import annotations

import re
import tarfile
from pathlib import Path
from typing import Any, cast

from axrun.adapters._candidate import load_candidate
from axrun.errors import ContractError
from axrun.models import EpisodePhase
from axrun.report import verify_record
from axrun.store import EpisodeStore
from axrun.trajectories.bundle import load_trajectory_bundle
from axrun.trajectories.schema import TrajectoryEvent, load_trajectory_jsonl

FORMAT = "axrun.programbench-provenance-review@1"
_SEQTK = "lh3__seqtk.94e7070"
_NETWORK_COMMAND = re.compile(r"\b(?:curl|wget)\b|\bgit\s+(?:clone|fetch|pull)\b", re.I)
_PACKAGE_COMMAND = re.compile(
    r"\b(?:pip3?|npm|yarn|pnpm)\s+(?:install|download|add|pack|view)\b"
    r"|\b(?:apt-get|apt)\s+install\b",
    re.I,
)


def review_programbench_seqtk(store: EpisodeStore, episode_id: str) -> dict[str, Any]:
    """Verify immutable local evidence, then return only non-sensitive review signals."""
    report = verify_record(store, episode_id)
    episode = store.load_spec(episode_id)
    record = store.load(episode_id)
    if (
        record is None
        or record.phase != EpisodePhase.COMPLETED
        or episode.task.identity != "programbench-official-single"
        or episode.task_id != _SEQTK
        or episode.harness.identity != "claude-code"
        or not record.candidate_manifest
        or not record.trajectory_manifest
    ):
        raise ContractError("provenance review requires a completed Claude seqtk episode")
    candidate = load_candidate(Path(record.candidate_manifest))
    trajectory = load_trajectory_bundle(Path(record.trajectory_manifest))
    workspace_files = [item for item in candidate.files if item.role == "workspace"]
    if len(workspace_files) != 1 or len(candidate.files) != 1:
        raise ContractError("seqtk candidate must contain one workspace archive")
    events = load_trajectory_jsonl(Path(trajectory.root) / trajectory.trajectory.bundle_path)
    signals = tool_call_signals(events)
    signals["bundled_elf_files"] = _elf_count(Path(candidate.root) / workspace_files[0].bundle_path)
    return {
        "format": FORMAT,
        "episode_id": episode_id,
        "candidate_digest": candidate.digest,
        "trajectory_digest": trajectory.digest,
        "verification_result_digest": report["verification_result_digest"],
        "review_status": "human_attestation_required",
        "signals": signals,
        "limitations": [
            "Tool-call text matching is advisory and may miss encoded or indirect actions.",
            "Network attempts do not establish successful external consultation.",
            "A trajectory cannot establish what source code a model knew before inference.",
        ],
    }


def tool_call_signals(events: tuple[TrajectoryEvent, ...]) -> dict[str, int]:
    """Count possible external-source actions without returning arguments or results."""
    counts = {
        "network_retrieval_calls": 0,
        "package_registry_calls": 0,
        "web_tool_calls": 0,
    }
    for event in events:
        if event.kind != "tool_call":
            continue
        name = event.data.get("name")
        if name in {"WebFetch", "WebSearch"}:
            counts["web_tool_calls"] += 1
        if name != "Bash":
            continue
        arguments = event.data.get("arguments")
        if not isinstance(arguments, dict):
            continue
        command = cast(dict[str, object], arguments).get("command")
        if not isinstance(command, str):
            continue
        counts["network_retrieval_calls"] += bool(_NETWORK_COMMAND.search(command))
        counts["package_registry_calls"] += bool(_PACKAGE_COMMAND.search(command))
    return counts


def _elf_count(path: Path) -> int:
    count = 0
    try:
        with tarfile.open(path, "r:") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    raise ContractError("workspace archive has a missing file payload")
                if stream.read(4) == b"\x7fELF":
                    count += 1
    except (OSError, tarfile.TarError) as exc:
        raise ContractError("workspace archive cannot be reviewed") from exc
    return count
