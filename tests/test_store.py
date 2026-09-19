from __future__ import annotations

from axrun.models import (
    CandidateSpec,
    EnvironmentBinding,
    EpisodePhase,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    TaskSpec,
    VerifierSpec,
)
from axrun.store import EpisodeStore


def test_store_separates_immutable_spec_from_minimal_execution_record(tmp_path) -> None:
    episode = ResolvedEpisode(
        1,
        "ep-1",
        "task-1",
        "b" * 64,
        str(tmp_path / "prompt.txt"),
        TaskSpec("git-worktree", "1", {"base_commit": "a" * 40}),
        EnvironmentBinding("env-i", f"x/task@sha256:{'f' * 64}", "linux/amd64", "/workspace"),
        EnvironmentBinding("env-v", f"x/task@sha256:{'f' * 64}", "linux/amd64", "/workspace"),
        HarnessSpec("static-patch", "1"),
        CandidateSpec("git-patch", "1"),
        VerifierSpec("command-verifier", "1"),
    )
    store = EpisodeStore(tmp_path)
    record = store.initialize(episode)
    record.phase = EpisodePhase.INFERENCE_RUNNING
    record.inference = ExecutionRef("env-i", "run-i", "alloc-i")
    store.save(record)
    assert store.load("ep-1") == record
    assert store.load_spec("ep-1") == episode
    assert "prompt_file" not in store.path_for("ep-1").read_text()
    assert not list(store.path_for("ep-1").parent.glob("*.tmp"))
