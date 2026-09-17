from __future__ import annotations

from pathlib import Path

import pytest

from axrun.adapters import ClaudeCodeMountAdapter
from axrun.axern_backend import AxernBackend
from axrun.errors import SdkCapabilityError
from axrun.models import ResolvedEpisode


class ReleasedV080ClientShape:
    def create_run(self, *, environment_id, argv, declared_outputs, labels):
        raise AssertionError("Run must not be created when required SDK parameters are absent")


def test_mount_adapter_fails_before_run_with_incomplete_public_sdk(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("task", encoding="utf-8")
    episode = ResolvedEpisode(
        1, "episode", "task", "digest", "a" * 40, str(prompt), "env-i", "env-v"
    )
    plan = ClaudeCodeMountAdapter("example/claude@sha256:abc", "secret").plan(episode)
    backend = AxernBackend(ReleasedV080ClientShape())

    with pytest.raises(SdkCapabilityError, match="image_mounts, secret_env"):
        backend.execute(
            plan,
            artifact_dir=tmp_path / "artifacts",
            on_bound=lambda _execution: None,
        )
