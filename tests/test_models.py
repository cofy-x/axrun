from __future__ import annotations

import pytest

from axrun.errors import ContractError
from axrun.models import OutputSpec, ResolvedEpisode, resolved_episode_from_dict


def test_episode_requires_full_base_commit() -> None:
    with pytest.raises(ContractError, match="base_commit"):
        ResolvedEpisode(1, "episode", "task", "digest", "abc", "prompt", "env-a", "env-v")


def test_output_requires_absolute_path() -> None:
    with pytest.raises(ContractError, match="absolute"):
        OutputSpec("relative.json")


def test_episode_decoder_rejects_unknown_fields_and_normalizes_commands() -> None:
    raw = {
        "schema_version": 1,
        "episode_id": "episode",
        "task_id": "task",
        "task_digest": "sha256:task",
        "base_commit": "a" * 40,
        "prompt_file": "prompt.txt",
        "inference_environment_id": "env-i",
        "verification_environment_id": "env-v",
        "harness": {"command": ["mini"], "version": "2.4.6"},
        "inference_resources": {"request_cpu": "500m", "limit_memory": "2Gi"},
    }
    episode = resolved_episode_from_dict(raw)
    assert episode.harness.command == ("mini",)
    assert episode.inference_resources.request_cpu == "500m"
    raw["node_id"] = "private"
    with pytest.raises(ContractError, match="unknown"):
        resolved_episode_from_dict(raw)
