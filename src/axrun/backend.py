"""Execution backend boundary."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from axrun.lifecycle.base import PreStartLifecycle
from axrun.models import ExecutionRef, StagePlan, StageResult


class RootfsExecutionBackend(Protocol):
    def execute_rootfs(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
    ) -> tuple[StageResult, str]:
        """Execute a finite Run and return its ready derived Environment ID."""
        ...

    def recover_rootfs(
        self,
        execution: ExecutionRef,
        plan: StagePlan,
        *,
        artifact_dir: Path,
    ) -> tuple[StageResult, str] | None:
        """Recover a finite Run and its ready rootfs result."""
        ...

    def delete_environment(self, environment_id: str) -> None:
        """Delete a verifier-owned derived Environment; absence is success."""
        ...


class ExecutionBackend(Protocol):
    def execute(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
        lifecycle: PreStartLifecycle | None = None,
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

    def cancel(self, execution: ExecutionRef) -> None:
        """Cancel the authoritative Axern Run. Repeated cancellation is safe."""
        ...

    def wait(self, execution: ExecutionRef, *, timeout: float | None = None) -> None:
        """Wait for the authoritative Axern Run to become terminal."""
        ...
