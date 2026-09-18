"""Bounded loopback gateway for an Anthropic-compatible model endpoint."""

from __future__ import annotations

import http.client
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final
from urllib.parse import urlsplit

from axrun.errors import ContractError, InfrastructureError

_HOP_BY_HOP: Final = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_SENSITIVE: Final = frozenset({"authorization", "cookie", "proxy-authorization", "x-api-key"})
_MODEL_PATHS: Final = frozenset({"/v1/messages", "/v1/messages/count_tokens"})


@dataclass(frozen=True)
class GatewayRequestSummary:
    method: str
    path: str
    status: int
    request_bytes: int
    response_bytes: int


class ModelGateway:
    """A loopback-only proxy that injects the upstream credential in memory."""

    def __init__(
        self,
        *,
        upstream_url: str,
        api_key: str,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 300.0,
        max_request_bytes: int = 16 << 20,
        max_response_bytes: int = 64 << 20,
        upstream_headers: Mapping[str, str] | None = None,
    ) -> None:
        parsed = urlsplit(upstream_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ContractError("model upstream must be an http(s) URL with a host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ContractError(
                "model upstream URL must not contain credentials, query, or fragment"
            )
        if not api_key:
            raise ContractError("model gateway API key is required")
        if min(max_request_bytes, max_response_bytes) <= 0:
            raise ContractError("model gateway byte bounds must be positive")
        self._upstream = parsed
        self._api_key = api_key
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._upstream_headers = dict(upstream_headers or {})
        if any(key.lower() in _SENSITIVE for key in self._upstream_headers):
            raise ContractError("upstream_headers must not contain credentials")
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._summaries: list[GatewayRequestSummary] = []
        self._summary_lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            f"ModelGateway(upstream={self._upstream.scheme}://{self._upstream.hostname}, "
            f"running={self._server is not None})"
        )

    @property
    def local_target(self) -> str:
        server = self._server
        if server is None:
            raise InfrastructureError("model gateway is not running")
        host, port = server.server_address[:2]
        return f"{host}:{port}"

    @property
    def summaries(self) -> tuple[GatewayRequestSummary, ...]:
        with self._summary_lock:
            return tuple(self._summaries)

    def start(self) -> None:
        if self._server is not None:
            return
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:
                if self.path != "/healthz":
                    self.send_error(404)
                    return
                body = b"ok\n"
                self.send_response(200)
                self.send_header("content-type", "text/plain")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                gateway._proxy(self)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(
            target=server.serve_forever, name="axrun-model-gateway", daemon=True
        )
        self._server = server
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5.0)
        self._api_key = ""

    def _proxy(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlsplit(handler.path).path
        if path not in _MODEL_PATHS or handler.path != path:
            handler.send_error(404)
            return
        raw_length = handler.headers.get("content-length")
        if raw_length is None:
            handler.send_error(411)
            return
        try:
            request_bytes = int(raw_length)
        except ValueError:
            handler.send_error(400)
            return
        if request_bytes < 0 or request_bytes > self._max_request_bytes:
            handler.send_error(413)
            return
        body = handler.rfile.read(request_bytes)
        headers = {
            key: value
            for key, value in handler.headers.items()
            if key.lower() not in _HOP_BY_HOP | _SENSITIVE | {"host", "content-length"}
        }
        headers.update(self._upstream_headers)
        headers["x-api-key"] = self._api_key
        headers["content-length"] = str(len(body))
        base_path = self._upstream.path.rstrip("/")
        upstream_path = f"{base_path}{path}" if base_path else path
        hostname = self._upstream.hostname
        assert hostname is not None
        port = self._upstream.port or (443 if self._upstream.scheme == "https" else 80)
        if self._upstream.scheme == "https":
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                hostname, port, timeout=self._connect_timeout_seconds
            )
        else:
            connection = http.client.HTTPConnection(
                hostname, port, timeout=self._connect_timeout_seconds
            )
        response_bytes = 0
        status = 502
        headers_sent = False
        try:
            connection.request("POST", upstream_path, body=body, headers=headers)
            response = connection.getresponse()
            if connection.sock is not None:
                connection.sock.settimeout(self._read_timeout_seconds)
            status = response.status
            content_length = response.getheader("content-length")
            if content_length is not None and int(content_length) > self._max_response_bytes:
                raise InfrastructureError("model upstream response exceeds byte bound")
            handler.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in _HOP_BY_HOP | {"content-length"}:
                    handler.send_header(key, value)
            if content_length is not None:
                handler.send_header("content-length", content_length)
            else:
                handler.send_header("connection", "close")
                handler.close_connection = True
            handler.end_headers()
            headers_sent = True
            while chunk := response.read(64 * 1024):
                response_bytes += len(chunk)
                if response_bytes > self._max_response_bytes:
                    raise InfrastructureError("model upstream response exceeds byte bound")
                handler.wfile.write(chunk)
                handler.wfile.flush()
        except (OSError, http.client.HTTPException, InfrastructureError):
            handler.close_connection = True
            if not handler.wfile.closed and not headers_sent:
                with suppress(OSError):
                    handler.send_error(502)
        finally:
            connection.close()
            with self._summary_lock:
                self._summaries.append(
                    GatewayRequestSummary(
                        method="POST",
                        path=path,
                        status=status,
                        request_bytes=request_bytes,
                        response_bytes=response_bytes,
                    )
                )
