from __future__ import annotations

from axrun.models import EpisodePhase, EpisodeRecord, ExecutionRef, ResolvedEpisode
from axrun.store import EpisodeStore


def test_store_round_trip(tmp_path) -> None:
    episode = ResolvedEpisode(
        1, "ep-1", "task-1", "sha256:task", "a" * 40, "prompt.txt", "env-i", "env-v"
    )
    record = EpisodeRecord(
        schema_version=1,
        episode=episode,
        phase=EpisodePhase.INFERENCE_RUNNING,
        inference=ExecutionRef("env-i", "run-i", "alloc-i"),
    )
    store = EpisodeStore(tmp_path)
    store.save(record)

    assert store.load("ep-1") == record
    assert not store.path_for("ep-1").with_suffix(".json.tmp").exists()
