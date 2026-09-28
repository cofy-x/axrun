from __future__ import annotations

import pytest

from axrun.errors import ContractError, DiagnosedInfrastructureError
from axrun.lifecycle.base import CompositePreStartLifecycle
from axrun.models import ExecutionRef


@pytest.mark.parametrize("failed_component", ["first", "second"])
def test_composite_cleanup_retries_only_failed_component(failed_component: str) -> None:
    events: list[str] = []

    class Component:
        def __init__(self, name: str) -> None:
            self.name = name
            self.attempts = 0

        def start(self, _execution, _allocation) -> None:
            events.append(f"start:{self.name}")

        def close(self) -> None:
            self.attempts += 1
            events.append(f"close:{self.name}")
            if self.name == failed_component and self.attempts == 1:
                raise RuntimeError("private-component-token")

    lifecycle = CompositePreStartLifecycle(Component("first"), Component("second"))
    lifecycle.start(ExecutionRef("env", "run", "alloc"), object())
    with pytest.raises(DiagnosedInfrastructureError) as raised:
        lifecycle.close()
    assert raised.value.diagnostic_code == "lifecycle_cleanup_failed"
    assert raised.value.details == {"reason_code": "component_cleanup_failed"}
    assert "private-component-token" not in str(raised.value)
    assert events == ["start:first", "start:second", "close:second", "close:first"]

    lifecycle.close()
    assert events[-1] == f"close:{failed_component}"
    assert len(events) == 5
    lifecycle.close()
    assert len(events) == 5


def test_composite_preserves_safe_child_diagnostic_while_closing_other_components() -> None:
    closed: list[str] = []

    class Component:
        def start(self, _execution, _allocation):
            pass

        def close(self):
            closed.append("clean")

    class Broken(Component):
        def close(self):
            closed.append("broken")
            raise DiagnosedInfrastructureError(
                "model_tunnel_cleanup_failed", {"reason_code": "tunnel_revoke_failed"}
            )

    lifecycle = CompositePreStartLifecycle(Component(), Broken())
    lifecycle.start(ExecutionRef("env", "run", "alloc"), object())
    with pytest.raises(DiagnosedInfrastructureError) as raised:
        lifecycle.close()
    assert raised.value.diagnostic_code == "model_tunnel_cleanup_failed"
    assert closed == ["broken", "clean"]


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_partial_start_failure_keeps_child_reachable_for_cleanup_and_retry(
    cleanup_fails: bool,
) -> None:
    events: list[str] = []

    class Component:
        def __init__(self, name: str) -> None:
            self.name = name
            self.active = False
            self.close_attempts = 0

        def start(self, _execution, _allocation) -> None:
            events.append(f"start:{self.name}")
            self.active = True
            if self.name == "partial":
                raise ContractError("partial component start rejected")

        def close(self) -> None:
            events.append(f"close:{self.name}")
            self.close_attempts += 1
            if self.name == "partial" and cleanup_fails and self.close_attempts == 1:
                raise RuntimeError("private-partial-component-token")
            self.active = False

    first, partial, untouched = (Component(name) for name in ("first", "partial", "untouched"))
    lifecycle = CompositePreStartLifecycle(first, partial, untouched)
    error = DiagnosedInfrastructureError if cleanup_fails else ContractError
    with pytest.raises(error) as raised:
        lifecycle.start(ExecutionRef("env", "run", "alloc"), object())
    assert "private-partial-component-token" not in str(raised.value)
    assert events == ["start:first", "start:partial", "close:partial", "close:first"]
    assert not first.active and not untouched.active
    assert partial.active is cleanup_fails

    lifecycle.close()
    assert not partial.active
    assert partial.close_attempts == (2 if cleanup_fails else 1)
    assert untouched.close_attempts == 0
    completed_events = list(events)
    lifecycle.close()
    assert events == completed_events
