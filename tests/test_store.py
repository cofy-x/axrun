from __future__ import annotations

import json
from dataclasses import replace

import pytest

from axrun.errors import ContractError, RecoveryRequiredError
from axrun.models import (
    CandidateSpec,
    EnvironmentBinding,
    EpisodePhase,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageNetworkPolicy,
    TaskSpec,
    VerifierSpec,
    canonical_json,
)
from axrun.store import EpisodeStore


def _episode(tmp_path) -> ResolvedEpisode:
    return ResolvedEpisode(
        1,
        "ep-1",
        "task-1",
        "b" * 64,
        str(tmp_path / "prompt.txt"),
        TaskSpec("git-worktree", "1", {"base_commit": "a" * 40}),
        EnvironmentBinding("env-i", f"x/task@sha256:{'f' * 64}", "linux/amd64", "/workspace"),
        EnvironmentBinding("env-v", f"x/task@sha256:{'f' * 64}", "linux/amd64", "/workspace"),
        HarnessSpec("static-candidate", "1"),
        CandidateSpec("git-patch", "1"),
        VerifierSpec("command-verifier", "1"),
    )


def test_store_separates_immutable_spec_from_minimal_execution_record(tmp_path) -> None:
    episode = _episode(tmp_path)
    store = EpisodeStore(tmp_path)
    record = store.initialize(episode)
    record.phase = EpisodePhase.INFERENCE_RUNNING
    record.inference = ExecutionRef("env-i", "run-i", "alloc-i")
    store.save(record)
    assert store.load("ep-1") == record
    assert store.load_spec("ep-1") == episode
    assert "prompt_file" not in store.path_for("ep-1").read_text()
    assert not list(store.path_for("ep-1").parent.glob("*.tmp"))
    spec = json.loads(store.spec_path_for("ep-1").read_text())
    assert "inference_network_policy" not in spec
    assert "verification_network_policy" not in spec
    spec["episode_id"] = "other-episode"
    store.spec_path_for("ep-1").write_text(json.dumps(spec))
    with pytest.raises(ContractError, match="specification identity differs"):
        store.load_spec("ep-1")


def test_orphaned_spec_is_reused_only_for_identical_episode(tmp_path) -> None:
    episode = _episode(tmp_path)
    store = EpisodeStore(tmp_path / "state")
    path = store.spec_path_for(episode.episode_id)
    path.parent.mkdir(parents=True)
    path.write_bytes(canonical_json(episode.as_dict()) + b"\n")
    assert store.initialize(episode).spec_digest == episode.digest

    other = EpisodeStore(tmp_path / "different-state")
    other_path = other.spec_path_for(episode.episode_id)
    other_path.parent.mkdir(parents=True)
    other_path.write_bytes(canonical_json(episode.as_dict()) + b"\n")
    with pytest.raises(RecoveryRequiredError, match="orphaned episode specification differs"):
        other.initialize(replace(episode, task_id="different-task"))
    assert not other.path_for(episode.episode_id).exists()


def test_initialize_rejects_missing_existing_spec(tmp_path) -> None:
    episode = _episode(tmp_path)
    store = EpisodeStore(tmp_path)
    store.initialize(episode)
    store.spec_path_for(episode.episode_id).unlink()
    with pytest.raises(RecoveryRequiredError, match="specification is missing"):
        store.initialize(episode)


@pytest.mark.parametrize(
    "episode_id", ["", ".", "..", "../other", "/tmp/other", "a/b", "a\\b", "a\nb"]
)
def test_store_rejects_unsafe_episode_ids_before_access(tmp_path, episode_id: str) -> None:
    store = EpisodeStore(tmp_path / "state")
    with pytest.raises(ContractError, match="safe path component"):
        store.path_for(episode_id)
    with pytest.raises(ContractError, match="safe path component"):
        store.spec_path_for(episode_id)
    with pytest.raises(ContractError, match="safe path component"):
        store.load(episode_id)
    with pytest.raises(ContractError, match="safe path component"), store.lock(episode_id):
        pass
    assert not store.root.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "record schema"),
        ("schema_version", True, "record schema"),
        ("episode_id", "other-episode", "record identity differs"),
        ("spec_digest", "bad-digest", "digest is invalid"),
        ("phase", "future-phase", "phase is invalid"),
        ("unknown_future_field", "data", "unknown fields"),
    ],
)
def test_load_rejects_wrong_record_identity_version_or_shape(
    tmp_path, field: str, value: object, message: str
) -> None:
    from axrun.models import EpisodeRecord

    store = EpisodeStore(tmp_path)
    store.save(EpisodeRecord(1, "ep-1", "a" * 64))
    path = store.path_for("ep-1")
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(ContractError, match=message):
        store.load("ep-1")


def test_v2_stage_policies_are_persisted_and_recovered(tmp_path) -> None:
    episode = ResolvedEpisode(
        2,
        "ep-public",
        "task-public",
        "b" * 64,
        str(tmp_path / "prompt.txt"),
        TaskSpec("task", "1"),
        EnvironmentBinding("env-i", f"x/task@sha256:{'f' * 64}", "linux/amd64", "/app"),
        EnvironmentBinding("env-v", f"x/task@sha256:{'f' * 64}", "linux/amd64", "/app"),
        HarnessSpec("static-candidate", "1"),
        CandidateSpec("workspace-archive", "1"),
        VerifierSpec("command-verifier", "1"),
        inference_network_policy=StageNetworkPolicy.UNRESTRICTED,
        verification_network_policy=StageNetworkPolicy.DENY_ALL,
    )
    store = EpisodeStore(tmp_path)
    store.initialize(episode)
    assert store.load_spec(episode.episode_id) == episode
    raw = json.loads(store.spec_path_for(episode.episode_id).read_text())
    assert raw["inference_network_policy"] == "unrestricted"
    assert raw["verification_network_policy"] == "deny_all"
    with pytest.raises(ContractError, match="requires both"):
        replace(episode, verification_network_policy=None)
    with pytest.raises(ContractError, match="unsupported episode network policy"):
        replace(episode, inference_network_policy="default")  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="implicit deny-all"):
        replace(episode, schema_version=1)
