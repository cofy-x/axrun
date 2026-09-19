"""Dataset boundary owned by Axrun adapters, not by the execution backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from axrun.models import HarnessSpec, ResolvedEpisode


class DatasetAdapter(Protocol):
    @property
    def identity(self) -> str: ...

    @property
    def version(self) -> str: ...

    def resolve(
        self,
        row: dict[str, Any],
        *,
        source_dir: Path,
        episode_id: str,
        inference_environment_id: str,
        verification_environment_id: str,
        task_image: str,
        task_platform: str,
        harness: HarnessSpec,
    ) -> ResolvedEpisode: ...
