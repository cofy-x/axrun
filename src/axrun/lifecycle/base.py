"""Ephemeral stage lifecycle hooks that are never part of a durable plan."""

from __future__ import annotations

from typing import Any, Protocol, cast

from axrun.errors import DiagnosedInfrastructureError
from axrun.models import ExecutionRef


class PreStartLifecycle(Protocol):
    def start(self, execution: ExecutionRef, allocation: Any) -> None: ...

    def close(self) -> None: ...


class CompositePreStartLifecycle:
    """Start ordered stage capabilities and close them in reverse order."""

    def __init__(self, *lifecycles: PreStartLifecycle) -> None:
        self._lifecycles = lifecycles
        self._started: list[PreStartLifecycle] = []

    @property
    def failure_diagnostic(self) -> dict[str, Any]:
        for lifecycle in self._lifecycles:
            value = getattr(lifecycle, "failure_diagnostic", None)
            if isinstance(value, dict) and value:
                return cast(dict[str, Any], value)
        return {}

    def start(self, execution: ExecutionRef, allocation: Any) -> None:
        if self._started:
            raise RuntimeError("composite lifecycle has already started")
        try:
            for lifecycle in self._lifecycles:
                # Start may create resources before it fails. Keep that child
                # reachable for cleanup and for retrying an incomplete close.
                self._started.append(lifecycle)
                lifecycle.start(execution, allocation)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        pending: list[PreStartLifecycle] = []
        error: BaseException | None = None
        for lifecycle in reversed(self._started):
            try:
                lifecycle.close()
            except BaseException as exc:
                pending.append(lifecycle)
                if error is None:
                    error = exc
        self._started = list(reversed(pending))
        if error is not None:
            if isinstance(error, DiagnosedInfrastructureError) or not isinstance(error, Exception):
                raise error from None
            raise DiagnosedInfrastructureError(
                "lifecycle_cleanup_failed", {"reason_code": "component_cleanup_failed"}
            ) from None
