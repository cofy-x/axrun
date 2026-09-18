"""Ephemeral stage lifecycle hooks that are never part of a durable plan."""

from __future__ import annotations

from typing import Any, Protocol

from axrun.models import ExecutionRef


class PreStartLifecycle(Protocol):
    """Prepare caller-local capabilities before a staged process is released."""

    def start(self, execution: ExecutionRef, allocation: Any) -> None:
        """Make the capability ready for an already-running Allocation."""
        ...

    def close(self) -> None:
        """Release all ephemeral resources. Repeated calls must be safe."""
        ...
