"""Allocation-scoped Axern tunnel lifecycle for a caller-side model proxy."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from axrun.errors import InfrastructureError
from axrun.models import ExecutionRef
from axrun.proxy.base import ModelProxyInstance


class ModelTunnelLifecycle:
    """Keep tunnel credentials ephemeral and release the stage only after preflight."""

    def __init__(
        self,
        *,
        client: Any,
        proxy: ModelProxyInstance,
        remote_port: int = 8765,
        ttl_seconds: float = 3600.0,
        ready_timeout_seconds: float = 60.0,
        connector_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._client = client
        self._proxy = proxy
        self._remote_port = remote_port
        self._ttl_seconds = ttl_seconds
        self._ready_timeout_seconds = ready_timeout_seconds
        self._connector_factory = connector_factory
        self._connector: Any | None = None
        self._session_id = ""

    def __repr__(self) -> str:
        return (
            f"ModelTunnelLifecycle(remote_port={self._remote_port}, "
            f"active={bool(self._session_id)})"
        )

    def start(self, execution: ExecutionRef, allocation: Any) -> None:
        if not execution.allocation_id:
            raise InfrastructureError("Allocation identity must be persisted before tunnel setup")
        if self._connector is not None:
            raise InfrastructureError("tunnel lifecycle has already started")
        self._proxy.start()
        try:
            response = self._client.create_tunnel_session(
                allocation_id=execution.allocation_id,
                remote_port=self._remote_port,
                ttl_seconds=self._ttl_seconds,
                wait_ready=True,
                ready_timeout_seconds=self._ready_timeout_seconds,
                timeout=self._ready_timeout_seconds + 30.0,
            )
            self._session_id = str(response.session.session_id)
            factory = self._connector_factory
            if factory is None:
                from axern_sdk import TunnelConnector

                factory = TunnelConnector
            connector = factory(
                client=self._client,
                session=response.session,
                client_token=response.client_token,
                local_target=self._proxy.local_target,
            )
            self._connector = connector
            connector.start()
            self._wait_for_preflight(allocation, response.session)
        except BaseException as exc:
            self.close()
            if isinstance(exc, Exception):
                raise InfrastructureError("model Tunnel setup or preflight failed") from None
            raise

    def close(self) -> None:
        session_id, connector = self._session_id, self._connector
        self._session_id = ""
        self._connector = None
        if session_id:
            with suppress(Exception):
                self._client.revoke_tunnel_session(
                    session_id, reason="axrun stage finished", timeout=10.0
                )
        if connector is not None:
            with suppress(Exception):
                connector.stop(timeout=5.0)
        self._proxy.stop()

    def _wait_for_preflight(self, allocation: Any, session: Any) -> None:
        bound_addr = str(session.bound_addr or f"127.0.0.1:{session.remote_port}")
        deadline = time.monotonic() + self._ready_timeout_seconds
        command = [
            "python3",
            "-c",
            (
                "import sys,urllib.request; "
                "r=urllib.request.urlopen('http://'+sys.argv[1]+'/healthz',timeout=2); "
                "assert r.status==200 and r.read()==b'ok\\n'"
            ),
            bound_addr,
        ]
        while time.monotonic() < deadline:
            connector = self._connector
            if connector is not None and connector.error is not None:
                raise InfrastructureError("model tunnel connector failed before preflight")
            try:
                allocation.exec(
                    command,
                    timeout_seconds=5,
                    check=True,
                    text=True,
                    rpc_timeout=10.0,
                )
                return
            except Exception:
                time.sleep(0.25)
        raise InfrastructureError("model tunnel did not pass Allocation preflight")
