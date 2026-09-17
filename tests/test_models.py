from __future__ import annotations

import pytest

from axrun.errors import ContractError
from axrun.models import OutputSpec, ResolvedEpisode


def test_episode_requires_full_base_commit() -> None:
    with pytest.raises(ContractError, match="base_commit"):
        ResolvedEpisode(1, "episode", "task", "digest", "abc", "prompt", "env-a", "env-v")


def test_output_requires_absolute_path() -> None:
    with pytest.raises(ContractError, match="absolute"):
        OutputSpec("relative.json")
