from __future__ import annotations

from types import SimpleNamespace

from axrun.models import ExecutionRef
from axrun.tunnel_lifecycle import AxernTunnelLifecycle


def test_tunnel_lifecycle_uses_ephemeral_token_and_is_idempotent() -> None:
    events: list[object] = []
    token = "ephemeral-tunnel-token"

    class Gateway:
        local_target = "127.0.0.1:54321"

        def start(self):
            events.append("gateway-start")

        def stop(self):
            events.append("gateway-stop")

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

    lifecycle = AxernTunnelLifecycle(
        client=Client(),
        gateway=Gateway(),  # type: ignore[arg-type]
        connector_factory=Connector,
    )
    lifecycle.start(ExecutionRef("env", "run", "allocation-1"), Allocation())
    lifecycle.close()
    lifecycle.close()

    assert events[0] == "gateway-start"
    assert events[1][0] == "create"
    assert events[2][0] == "connector"
    assert events[3] == "connector-start"
    assert events[4][0] == "preflight"
    assert events[5][0] == "revoke"
    assert events[6] == ("connector-stop", 5.0)
    assert events[7:] == ["gateway-stop", "gateway-stop"]
    assert token not in repr(lifecycle)
