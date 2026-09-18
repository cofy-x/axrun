"""Bounded, short-lived loopback proxy for one inference stage."""

from __future__ import annotations

import http.client
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from axrun.errors import ContractError, InfrastructureError
from axrun.proxy.base import ModelPreflight, ModelProtocol, ModelRequestSummary

_RESPONSE_BLOCKED_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "set-cookie",
}


class ModelProxy:
    """A loopback-only per-stage proxy that injects credentials in memory."""

    def __init__(
        self,
        *,
        upstream_url: str,
        credential: str,
        protocol: ModelProtocol,
        connect_timeout_seconds: float = 10.0,
        request_read_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 300.0,
        max_request_bytes: int = 16 << 20,
        max_response_bytes: int = 64 << 20,
        max_concurrent_requests: int = 8,
    ) -> None:
        parsed = urlsplit(upstream_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ContractError("model upstream must be an http(s) URL with a host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ContractError(
                "model upstream URL must not contain credentials, query, or fragment"
            )
        if not credential:
            raise ContractError("model proxy credential is required")
        if min(max_request_bytes, max_response_bytes, max_concurrent_requests) <= 0:
            raise ContractError("model proxy byte bounds must be positive")
        self._upstream = parsed
        self._credential = credential
        self._protocol = protocol
        self._connect_timeout_seconds = connect_timeout_seconds
        self._request_read_timeout_seconds = request_read_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._summaries: list[ModelRequestSummary] = []
        self._summary_lock = threading.Lock()
        self._request_slots = threading.BoundedSemaphore(max_concurrent_requests)

    def __repr__(self) -> str:
        return (
            f"ModelProxy(protocol={self._protocol.name}, "
            f"upstream={self._upstream.scheme}://{self._upstream.hostname}, "
            f"running={self._server is not None})"
        )

    @property
    def local_target(self) -> str:
        server = self._server
        if server is None:
            raise InfrastructureError("model proxy is not running")
        host, port = server.server_address[:2]
        return f"{host}:{port}"

    @property
    def summaries(self) -> tuple[ModelRequestSummary, ...]:
        with self._summary_lock:
            return tuple(self._summaries)

    def preflight(self, model: str) -> ModelPreflight:
        return self._protocol.preflight(model)

    def start(self) -> None:
        if self._server is not None:
            return
        proxy = self

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
                self.connection.settimeout(proxy._request_read_timeout_seconds)
                if not proxy._request_slots.acquire(blocking=False):
                    self.send_error(503)
                    return
                try:
                    proxy._proxy(self)
                finally:
                    proxy._request_slots.release()

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(
            target=server.serve_forever, name="axrun-model-proxy", daemon=True
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
        self._credential = ""

    def _proxy(self, handler: BaseHTTPRequestHandler) -> None:
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
        if len(body) != request_bytes:
            handler.send_error(400)
            return
        started = time.monotonic()
        try:
            request = self._protocol.prepare_request(
                method="POST",
                path=handler.path,
                incoming_headers=dict(handler.headers.items()),
                body=body,
                credential=self._credential,
            )
        except ContractError:
            handler.send_error(404)
            self._record_summary(
                ModelRequestSummary(
                    method="POST",
                    protocol=self._protocol.name,
                    path="",
                    status=404,
                    request_bytes=request_bytes,
                    response_bytes=0,
                    latency_ms=max(0, round((time.monotonic() - started) * 1000)),
                    model="",
                    usage={},
                    reason_code="proxy_protocol_rejected",
                )
            )
            return
        base_path = self._upstream.path.rstrip("/")
        upstream_path = (
            f"{base_path}{request.upstream_path}" if base_path else request.upstream_path
        )
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
        collector = self._protocol.usage_collector("")
        reason_code = "proxy_upstream_error"
        try:
            connection.request("POST", upstream_path, body=body, headers=dict(request.headers))
            response = connection.getresponse()
            collector = self._protocol.usage_collector(response.getheader("content-type", ""))
            if connection.sock is not None:
                connection.sock.settimeout(self._read_timeout_seconds)
            status = response.status
            reason_code = "upstream_response"
            content_length = response.getheader("content-length")
            if content_length is not None and int(content_length) > self._max_response_bytes:
                raise InfrastructureError("model upstream response exceeds byte bound")
            handler.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in _RESPONSE_BLOCKED_HEADERS:
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
                collector.feed(chunk)
                handler.wfile.write(chunk)
                handler.wfile.flush()
        except (OSError, ValueError, http.client.HTTPException, InfrastructureError):
            handler.close_connection = True
            if not handler.wfile.closed and not headers_sent:
                with suppress(OSError):
                    handler.send_error(502)
        finally:
            connection.close()
            self._record_summary(
                ModelRequestSummary(
                    method="POST",
                    protocol=self._protocol.name,
                    path=request.upstream_path,
                    status=status,
                    request_bytes=request_bytes,
                    response_bytes=response_bytes,
                    latency_ms=max(0, round((time.monotonic() - started) * 1000)),
                    model=request.model,
                    usage=collector.finish(),
                    reason_code=reason_code,
                )
            )

    def _record_summary(self, summary: ModelRequestSummary) -> None:
        with self._summary_lock:
            self._summaries.append(summary)
