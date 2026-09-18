from __future__ import annotations

import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from axrun.model_gateway import ModelGateway


def test_gateway_health_is_local_and_credentials_are_not_observable() -> None:
    upstream_requests: list[tuple[str, str, bytes]] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["content-length"])
            upstream_requests.append(
                (self.path, self.headers.get("x-api-key", ""), self.rfile.read(length))
            )
            body = b'{"ok":true}'
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
    gateway = ModelGateway(upstream_url=f"http://{host}:{port}", api_key=credential)
    gateway.start()
    gateway_host, gateway_port = gateway.local_target.split(":")
    connection = http.client.HTTPConnection(gateway_host, int(gateway_port), timeout=2)
    try:
        connection.request("GET", "/healthz")
        health = connection.getresponse()
        assert health.status == 200 and health.read() == b"ok\n"
        assert upstream_requests == []

        connection.request(
            "POST",
            "/v1/messages",
            body=b'{"model":"test"}',
            headers={
                "content-type": "application/json",
                "authorization": "Bearer sandbox-value",
                "x-api-key": "sandbox-value",
            },
        )
        response = connection.getresponse()
        assert response.status == 200 and response.read() == b'{"ok":true}'
    finally:
        connection.close()
        gateway.stop()
        gateway.stop()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    assert upstream_requests == [("/v1/messages", credential, b'{"model":"test"}')]
    assert credential not in repr(gateway)
    assert credential not in repr(gateway.summaries)
    assert "sandbox-value" not in repr(gateway.summaries)


def test_gateway_rejects_oversized_request_without_upstream_call() -> None:
    gateway = ModelGateway(upstream_url="http://127.0.0.1:1", api_key="secret", max_request_bytes=3)
    gateway.start()
    host, port = gateway.local_target.split(":")
    connection = http.client.HTTPConnection(host, int(port), timeout=2)
    try:
        connection.request("POST", "/v1/messages", body=b"four")
        response = connection.getresponse()
        assert response.status == 413
        response.read()
    finally:
        connection.close()
        gateway.stop()
