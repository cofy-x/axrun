from __future__ import annotations

import json
from dataclasses import replace

import pytest

from axrun.errors import ContractError
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
        HarnessSpec("static-candidate", "1"),
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
    spec = json.loads(store.spec_path_for("ep-1").read_text())
    assert "inference_network_policy" not in spec
    assert "verification_network_policy" not in spec


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
