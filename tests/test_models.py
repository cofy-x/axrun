from __future__ import annotations

import pytest

from axrun.errors import ContractError
from axrun.models import (
    HarnessSpec,
    OutputSpec,
    ResolvedEpisode,
    VerifierSpec,
    resolved_episode_from_dict,
)


def test_episode_requires_full_base_commit() -> None:
    with pytest.raises(ContractError, match="base_commit"):
        ResolvedEpisode(
            1,
            "episode",
            "task",
            "b" * 64,
            "abc",
            "prompt",
            "env-a",
            "env-v",
            HarnessSpec("static-patch", "1"),
            VerifierSpec("command-verifier", "1"),
        )


def test_output_requires_absolute_path() -> None:
    with pytest.raises(ContractError, match="absolute"):
        OutputSpec("relative.json")


def test_episode_decoder_uses_generic_adapters_and_rejects_unknown_fields() -> None:
    raw = {
        "schema_version": 1,
        "episode_id": "episode",
        "task_id": "task",
        "seed_digest": "b" * 64,
        "base_commit": "a" * 40,
        "prompt_file": "prompt.txt",
        "inference_environment_id": "env-i",
        "verification_environment_id": "env-v",
        "harness": {
            "identity": "mini-swe-agent",
            "version": "2.4.6",
            "config": {"command": ["mini"]},
        },
        "verifier": {
            "identity": "command-verifier",
            "version": "1",
            "config": {"command": ["/opt/axrun/run-verifier"]},
        },
        "inference_resources": {"request_cpu": "500m", "limit_memory": "2Gi"},
    }
    episode = resolved_episode_from_dict(raw)
    assert episode.harness == HarnessSpec("mini-swe-agent", "2.4.6", config={"command": ["mini"]})
    assert episode.inference_resources.request_cpu == "500m"
    raw["node_id"] = "private"
    with pytest.raises(ContractError, match="unknown"):
        resolved_episode_from_dict(raw)


def test_episode_requires_sha256_seed() -> None:
    raw = {
        "schema_version": 1,
        "episode_id": "episode",
        "task_id": "task",
        "seed_digest": "not-a-digest",
        "base_commit": "a" * 40,
        "prompt_file": "prompt.txt",
        "inference_environment_id": "env-i",
        "verification_environment_id": "env-v",
        "harness": {
            "identity": "static-patch",
            "version": "1",
            "config": {"candidate_file": "gold.patch"},
        },
        "verifier": {"identity": "command-verifier", "version": "1"},
    }
    with pytest.raises(ContractError, match="seed_digest"):
        resolved_episode_from_dict(raw)


def test_only_canonical_v1_is_supported() -> None:
    with pytest.raises(ContractError, match="unsupported"):
        resolved_episode_from_dict({"schema_version": 2})
