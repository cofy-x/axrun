from __future__ import annotations

from axrun.models import EpisodePhase, ExecutionRef, ResolvedEpisode
from axrun.store import EpisodeStore


def test_store_separates_immutable_spec_from_minimal_execution_record(tmp_path) -> None:
    episode = ResolvedEpisode(
        1, "ep-1", "task-1", "sha256:task", "a" * 40, "prompt.txt", "env-i", "env-v"
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
