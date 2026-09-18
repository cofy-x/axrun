from __future__ import annotations

import http.client
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from axrun.proxy.model import ModelProxy
from axrun.proxy.protocols import AnthropicProtocol


def test_model_proxy_health_is_local_and_credentials_are_not_observable() -> None:
    upstream_requests: list[tuple[str, str, str, str, bytes]] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["content-length"])
            upstream_requests.append(
                (
                    self.path,
                    self.headers.get("x-api-key", ""),
                    self.headers.get("authorization", ""),
                    self.headers.get("cookie", ""),
                    self.rfile.read(length),
                )
            )
            body = b'{"usage":{"input_tokens":3,"output_tokens":2}}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    host, port = upstream.server_address[:2]
    credential = "credential-must-stay-in-memory"
    proxy = ModelProxy(
        upstream_url=f"http://{host}:{port}",
        credential=credential,
        protocol=AnthropicProtocol(),
    )
    proxy.start()
    proxy_host, proxy_port = proxy.local_target.split(":")
    connection = http.client.HTTPConnection(proxy_host, int(proxy_port), timeout=2)
    try:
        connection.request("GET", "/healthz")
        health = connection.getresponse()
        assert health.status == 200 and health.read() == b"ok\n"
        assert upstream_requests == []

        connection.request(
            "POST",
            "/v1/messages?beta=true",
            body=b'{"model":"test"}',
            headers={
                "content-type": "application/json",
                "authorization": "Bearer sandbox-value",
                "cookie": "session=sandbox-value",
                "x-api-key": "sandbox-value",
            },
        )
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"usage": {"input_tokens": 3, "output_tokens": 2}}
    finally:
        connection.close()
        proxy.stop()
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    assert upstream_requests == [
        ("/v1/messages?beta=true", credential, "", "", b'{"model":"test"}')
    ]
    assert credential not in repr(proxy)
    assert credential not in repr(proxy.summaries)
    assert "sandbox-value" not in repr(proxy.summaries)
    assert proxy.summaries[0].protocol == "anthropic"
    assert proxy.summaries[0].model == "test"
    assert proxy.summaries[0].usage == {"input_tokens": 3, "output_tokens": 2}
    assert proxy.summaries[0].reason_code == "upstream_response"


def test_anthropic_proxy_forwards_only_closed_beta_query_paths() -> None:
    upstream_paths: list[str] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            upstream_paths.append(self.path)
            length = int(self.headers["content-length"])
            self.rfile.read(length)
            body = b"{}"
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    host, port = upstream.server_address[:2]
    proxy = ModelProxy(
        upstream_url=f"http://{host}:{port}",
        credential="caller-secret",
        protocol=AnthropicProtocol(),
    )
    proxy.start()
    proxy_host, proxy_port = proxy.local_target.split(":")
    connection = http.client.HTTPConnection(proxy_host, int(proxy_port), timeout=2)
    try:
        allowed_paths = (
            "/v1/messages",
            "/v1/messages?beta=true",
            "/v1/messages/count_tokens",
            "/v1/messages/count_tokens?beta=true",
        )
        for path in allowed_paths:
            connection.request("POST", path, body=b'{"model":"opaque[1m]"}')
            response = connection.getresponse()
            assert response.status == 200
            response.read()
        connection.request("POST", "/v1/messages?beta=false", body=b'{"secret":"body"}')
        rejected = connection.getresponse()
        assert rejected.status == 404
        rejected.read()
    finally:
        connection.close()
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    assert upstream_paths == [
        "/v1/messages",
        "/v1/messages?beta=true",
        "/v1/messages/count_tokens",
        "/v1/messages/count_tokens?beta=true",
    ]
    assert [summary.path for summary in proxy.summaries[:4]] == upstream_paths
    rejected_summary = proxy.summaries[4]
    assert rejected_summary.reason_code == "proxy_protocol_rejected"
    assert rejected_summary.status == 404 and rejected_summary.path == ""
    assert "secret" not in repr(rejected_summary)
    assert "caller-secret" not in repr(proxy.summaries)


def test_model_proxy_rejects_oversized_request_without_upstream_call() -> None:
    proxy = ModelProxy(
        upstream_url="http://127.0.0.1:1",
        credential="secret",
        protocol=AnthropicProtocol(),
        max_request_bytes=3,
    )
    proxy.start()
    host, port = proxy.local_target.split(":")
    connection = http.client.HTTPConnection(host, int(port), timeout=2)
    try:
        connection.request("POST", "/v1/messages", body=b"four")
        response = connection.getresponse()
        assert response.status == 413
        response.read()
    finally:
        connection.close()
        proxy.stop()


def test_model_proxy_rejects_half_closed_request_without_upstream_call() -> None:
    proxy = ModelProxy(
        upstream_url="http://127.0.0.1:1",
        credential="secret",
        protocol=AnthropicProtocol(),
        request_read_timeout_seconds=0.5,
    )
    proxy.start()
    host, raw_port = proxy.local_target.split(":")
    client = socket.create_connection((host, int(raw_port)), timeout=2)
    try:
        client.sendall(b"POST /v1/messages HTTP/1.1\r\nHost: local\r\nContent-Length: 10\r\n\r\n{}")
        client.shutdown(socket.SHUT_WR)
        response = client.recv(4096)
        assert b" 400 " in response
    finally:
        client.close()
        proxy.stop()
