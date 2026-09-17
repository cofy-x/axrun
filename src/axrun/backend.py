"""Execution backend boundary."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from axrun.models import ExecutionRef, StagePlan, StageResult


class ExecutionBackend(Protocol):
    def execute(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
    ) -> StageResult:
        """Execute one immutable stage and download its sealed outputs."""
        ...

    def recover(
        self,
        execution: ExecutionRef,
        plan: StagePlan,
        *,
        artifact_dir: Path,
    ) -> StageResult | None:
        """Return a terminal result, None while still live, or raise on ambiguity."""
        ...
