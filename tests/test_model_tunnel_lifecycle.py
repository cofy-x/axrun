from __future__ import annotations

from types import SimpleNamespace

import pytest

from axrun.errors import DiagnosedInfrastructureError, InfrastructureError
from axrun.lifecycle.model_tunnel import ModelTunnelLifecycle
from axrun.models import ExecutionRef
from axrun.proxy.base import ModelPreflight, ModelRequestSummary


def test_tunnel_lifecycle_uses_ephemeral_token_and_is_idempotent() -> None:
    events: list[object] = []
    token = "ephemeral-tunnel-token"

    class Proxy:
        local_target = "127.0.0.1:54321"

        def start(self):
            events.append("proxy-start")

        def stop(self):
            events.append("proxy-stop")

        def preflight(self, model):
            events.append(("proxy-preflight", model))
            return ModelPreflight(
                path="/v1/messages",
                headers={"content-type": "application/json"},
                body=b'{"model":"test-model"}',
            )

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
        def write_file(self, path, body):
            events.append(("preflight-body", path, body))

        def exec(self, command, **kwargs):
            events.append(("preflight", command, kwargs))

    lifecycle = ModelTunnelLifecycle(
        client=Client(),
        proxy=Proxy(),
        model="test-model",
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
    assert events[4][1][0] == "/usr/bin/python3"
    assert events[5] == ("proxy-preflight", "test-model")
    assert events[6] == (
        "preflight-body",
        "/run/axrun/model-preflight-body",
        b'{"model":"test-model"}',
    )
    assert events[7][0] == "preflight"
    assert events[7][1][0] == "/usr/bin/python3"
    assert "/v1/messages" in events[7][1]
    assert b'{"model":"test-model"}' not in repr(events[7]).encode()
    assert events[8][0] == "revoke"
    assert events[9] == ("connector-stop", 5.0)
    assert events[10:] == ["proxy-stop", "proxy-stop"]
    assert token not in repr(lifecycle)


def test_tunnel_lifecycle_does_not_echo_connector_token_on_failure() -> None:
    token = "never-echo-this-token"

    class Proxy:
        local_target = "127.0.0.1:1"

        def start(self):
            return None

        def stop(self):
            return None

        def preflight(self, model):
            raise AssertionError(f"unexpected preflight for {model}")

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
        client=Client(),
        proxy=Proxy(),
        model="test-model",
        connector_factory=broken_connector,
    )
    with pytest.raises(InfrastructureError) as raised:
        lifecycle.start(ExecutionRef("env", "run", "allocation"), object())
    assert token not in str(raised.value) and token not in repr(raised.value)


def test_tunnel_health_failure_has_stable_safe_diagnosis() -> None:
    token = "never-echo-health-token"

    class Proxy:
        local_target = "127.0.0.1:1"
        last_summary = None

        def start(self):
            return None

        def stop(self):
            return None

        def preflight(self, _model):
            raise AssertionError("model preflight must follow health")

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

    class Connector:
        error = None

        def __init__(self, **_kwargs):
            return None

        def start(self):
            return None

        def stop(self, **_kwargs):
            return None

    class Allocation:
        def exec(self, *_args, **_kwargs):
            raise RuntimeError("health-response-secret")

    lifecycle = ModelTunnelLifecycle(
        client=Client(),
        proxy=Proxy(),
        model="test-model",
        connector_factory=Connector,
        ready_timeout_seconds=0.01,
    )
    with pytest.raises(DiagnosedInfrastructureError) as raised:
        lifecycle.start(ExecutionRef("env", "run", "allocation"), Allocation())
    assert raised.value.diagnostic_code == "tunnel_health_failed"
    assert token not in str(raised.value)
    assert "health-response-secret" not in str(raised.value)


def test_tunnel_model_preflight_failure_reports_only_proxy_safe_summary() -> None:
    token = "never-echo-model-token"
    credential = "never-echo-model-credential"
    summary = ModelRequestSummary(
        method="POST",
        protocol="anthropic",
        path="/v1/messages",
        status=401,
        request_bytes=91,
        response_bytes=42,
        latency_ms=12,
        model="test-model",
        usage={},
        reason_code="upstream_response",
    )

    class Proxy:
        local_target = "127.0.0.1:1"
        last_summary = summary

        def start(self):
            return None

        def stop(self):
            return None

        def preflight(self, _model):
            return ModelPreflight(
                "/v1/messages", {"content-type": "application/json"}, b'{"model":"test"}'
            )

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

    class Connector:
        error = None

        def __init__(self, **_kwargs):
            return None

        def start(self):
            return None

        def stop(self, **_kwargs):
            return None

    class Allocation:
        calls = 0

        def write_file(self, _path, _body):
            return None

        def exec(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError(f"response-secret {credential}")

    lifecycle = ModelTunnelLifecycle(
        client=Client(), proxy=Proxy(), model="test-model", connector_factory=Connector
    )
    with pytest.raises(DiagnosedInfrastructureError) as raised:
        lifecycle.start(ExecutionRef("env", "run", "allocation"), Allocation())
    error = raised.value
    assert error.diagnostic_code == "tunnel_model_preflight_failed"
    assert error.details == summary.as_safe_dict()
    assert token not in str(error) and credential not in str(error)
    assert "response-secret" not in str(error)
