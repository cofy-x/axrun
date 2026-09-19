from __future__ import annotations

import pytest

from axrun.errors import ContractError
from axrun.models import (
    EnvironmentBinding,
    OutputSpec,
    resolved_episode_from_dict,
)


def test_environment_binding_requires_digest_pinned_image() -> None:
    with pytest.raises(ContractError, match="sha256"):
        EnvironmentBinding("env", "registry.invalid/task:latest", "linux/amd64", "/workspace")


def test_output_requires_absolute_path() -> None:
    with pytest.raises(ContractError, match="absolute"):
        OutputSpec("relative.json")


def test_episode_decoder_uses_generic_adapters_and_rejects_unknown_fields() -> None:
    raw = {
        "schema_version": 1,
        "episode_id": "episode",
        "task_id": "task",
        "seed_digest": "b" * 64,
        "prompt_file": "/inputs/prompt.txt",
        "task": {"identity": "git-worktree", "version": "1", "config": {"base_commit": "a" * 40}},
        "inference_environment": {
            "environment_id": "env-i",
            "image": f"x/task@sha256:{'f' * 64}",
            "platform": "linux/amd64",
            "working_directory": "/workspace",
        },
        "verification_environment": {
            "environment_id": "env-v",
            "image": f"x/task@sha256:{'e' * 64}",
            "platform": "linux/amd64",
            "working_directory": "/workspace",
        },
        "harness": {
            "identity": "claude-code",
            "version": "2.1.205",
            "config": {"model": "test-model"},
        },
        "candidate": {"identity": "git-patch", "version": "1"},
        "verifier": {
            "identity": "command-verifier",
            "version": "1",
            "config": {"command": ["/opt/axrun/run-verifier"]},
        },
        "inference_resources": {"request_cpu": "500m", "limit_memory": "2Gi"},
    }
    episode = resolved_episode_from_dict(raw)
    assert episode.harness.identity == "claude-code"
    assert episode.candidate.identity == "git-patch"
    assert episode.inference_environment.image != episode.verification_environment.image
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
        "prompt_file": "/inputs/prompt.txt",
        "task": {"identity": "git-worktree", "version": "1"},
        "inference_environment": {
            "environment_id": "env-i",
            "image": f"x/task@sha256:{'f' * 64}",
            "platform": "linux/amd64",
            "working_directory": "/workspace",
        },
        "verification_environment": {
            "environment_id": "env-v",
            "image": f"x/task@sha256:{'f' * 64}",
            "platform": "linux/amd64",
            "working_directory": "/workspace",
        },
        "harness": {
            "identity": "static-patch",
            "version": "1",
            "config": {"candidate_file": "gold.patch"},
        },
        "candidate": {"identity": "git-patch", "version": "1"},
        "verifier": {"identity": "command-verifier", "version": "1"},
    }
    with pytest.raises(ContractError, match="seed_digest"):
        resolved_episode_from_dict(raw)


def test_only_canonical_v1_is_supported() -> None:
    with pytest.raises(ContractError, match="unsupported"):
        resolved_episode_from_dict({"schema_version": 2})
