from __future__ import annotations

from types import SimpleNamespace

import pytest

from axrun.errors import InfrastructureError
from axrun.lifecycle.model_tunnel import ModelTunnelLifecycle
from axrun.models import ExecutionRef


def test_tunnel_lifecycle_uses_ephemeral_token_and_is_idempotent() -> None:
    events: list[object] = []
    token = "ephemeral-tunnel-token"

    class Proxy:
        local_target = "127.0.0.1:54321"

        def start(self):
            events.append("proxy-start")

        def stop(self):
            events.append("proxy-stop")

    class Client:
        def create_tunnel_session(self, **kwargs):
            events.append(("create", kwargs))
            return SimpleNamespace(
                session=SimpleNamespace(
                    session_id="session-1", bound_addr="127.0.0.1:8765", remote_port=8765
                ),
                client_token=token,
            )

        def revoke_tunnel_session(self, session_id, **kwargs):
            events.append(("revoke", session_id, kwargs))

    class Connector:
        error = None

        def __init__(self, **kwargs):
            events.append(("connector", kwargs))

        def start(self):
            events.append("connector-start")

        def stop(self, *, timeout):
            events.append(("connector-stop", timeout))

    class Allocation:
        def exec(self, command, **kwargs):
            events.append(("preflight", command, kwargs))

    lifecycle = ModelTunnelLifecycle(
        client=Client(),
        proxy=Proxy(),
        connector_factory=Connector,
    )
    lifecycle.start(ExecutionRef("env", "run", "allocation-1"), Allocation())
    lifecycle.close()
    lifecycle.close()

    assert events[0] == "proxy-start"
    assert events[1][0] == "create"
    assert events[2][0] == "connector"
    assert events[3] == "connector-start"
    assert events[4][0] == "preflight"
    assert events[5][0] == "revoke"
    assert events[6] == ("connector-stop", 5.0)
    assert events[7:] == ["proxy-stop", "proxy-stop"]
    assert token not in repr(lifecycle)


def test_tunnel_lifecycle_does_not_echo_connector_token_on_failure() -> None:
    token = "never-echo-this-token"

    class Proxy:
        local_target = "127.0.0.1:1"

        def start(self):
            return None

        def stop(self):
            return None

    class Client:
        def create_tunnel_session(self, **_kwargs):
            return SimpleNamespace(
                session=SimpleNamespace(
                    session_id="session", bound_addr="127.0.0.1:8765", remote_port=8765
                ),
                client_token=token,
            )

        def revoke_tunnel_session(self, *_args, **_kwargs):
            return None

    def broken_connector(**kwargs):
        raise RuntimeError(f"bad connector token: {kwargs['client_token']}")

    lifecycle = ModelTunnelLifecycle(
        client=Client(), proxy=Proxy(), connector_factory=broken_connector
    )
    with pytest.raises(InfrastructureError) as raised:
        lifecycle.start(ExecutionRef("env", "run", "allocation"), object())
    assert token not in str(raised.value) and token not in repr(raised.value)
