"""Bounded caller-side coordination for one verifier's finite Axern Runs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import cast

from axrun.backend import ExecutionBackend, RootfsExecutionBackend
from axrun.errors import InfrastructureError, RecoveryRequiredError
from axrun.models import ExecutionRef, StagePlan, StageResult


class MultiRunVerificationCoordinator:
    """Create or recover finite Runs without interpreting benchmark semantics.

    The benchmark adapter owns step names, ordering, assets, and scoring. This class only
    centralizes the public Run/rootfs-result lifecycle and makes reuse of a persisted Run ID
    explicit.
    """

    def __init__(self, backend: ExecutionBackend) -> None:
        self.backend = backend

    def run(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        existing: ExecutionRef | None,
        on_bound: Callable[[ExecutionRef], None],
    ) -> StageResult:
        if existing is None:
            return self.backend.execute(
                plan,
                artifact_dir=artifact_dir,
                on_bound=on_bound,
                lifecycle=None,
            )
        recovered = self.backend.recover(existing, plan, artifact_dir=artifact_dir)
        if recovered is not None:
            return recovered
        self.backend.wait(existing, timeout=plan.timeout_seconds + 120.0)
        recovered = self.backend.recover(existing, plan, artifact_dir=artifact_dir)
        if recovered is None:
            raise RecoveryRequiredError("persisted verification Run is still active")
        return recovered

    def run_with_rootfs(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        existing: ExecutionRef | None,
        on_bound: Callable[[ExecutionRef], None],
    ) -> tuple[StageResult, str]:
        backend = cast(RootfsExecutionBackend, self.backend)
        if not hasattr(backend, "execute_rootfs") or not hasattr(backend, "recover_rootfs"):
            raise InfrastructureError("execution backend does not expose rootfs results")
        if existing is None:
            return backend.execute_rootfs(
                plan,
                artifact_dir=artifact_dir,
                on_bound=on_bound,
            )
        recovered = backend.recover_rootfs(existing, plan, artifact_dir=artifact_dir)
        if recovered is not None:
            return recovered
        self.backend.wait(existing, timeout=plan.timeout_seconds + 120.0)
        recovered = backend.recover_rootfs(existing, plan, artifact_dir=artifact_dir)
        if recovered is None:
            raise RecoveryRequiredError("persisted rootfs-producing Run is still active")
        return recovered

    def cancel(self, executions: Iterable[ExecutionRef]) -> None:
        errors: list[Exception] = []
        seen: set[str] = set()
        for execution in executions:
            if execution.run_id in seen:
                continue
            seen.add(execution.run_id)
            try:
                self.backend.cancel(execution)
            except Exception as exc:  # cancellation remains best-effort across all owned Runs
                errors.append(exc)
        if errors:
            raise InfrastructureError("one or more verification Runs could not be cancelled")
