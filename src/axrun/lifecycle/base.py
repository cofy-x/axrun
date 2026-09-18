"""Ephemeral stage lifecycle hooks that are never part of a durable plan."""

from __future__ import annotations

from typing import Any, Protocol, cast

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
                lifecycle.start(execution, allocation)
                self._started.append(lifecycle)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        started, self._started = self._started, []
        error: BaseException | None = None
        for lifecycle in reversed(started):
            try:
                lifecycle.close()
            except BaseException as exc:
                if error is None:
                    error = exc
        if error is not None:
            raise error
