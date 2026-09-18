"""Ephemeral stage lifecycle hooks that are never part of a durable plan."""

from __future__ import annotations

from typing import Any, Protocol

from axrun.models import ExecutionRef


class PreStartLifecycle(Protocol):
    def start(self, execution: ExecutionRef, allocation: Any) -> None: ...

    def close(self) -> None: ...
