"""Anthropic-compatible request and streaming usage adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final, cast
from urllib.parse import urlsplit

from axrun.errors import ContractError
from axrun.proxy.base import ProtocolRequest, UsageCollector

_PATHS: Final = frozenset({"/v1/messages", "/v1/messages/count_tokens"})
_QUERIES: Final = frozenset({"", "beta=true"})
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
_USAGE_KEYS: Final = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


class AnthropicProtocol:
    name = "anthropic"

    def prepare_request(
        self,
        *,
        method: str,
        path: str,
        incoming_headers: Mapping[str, str],
        body: bytes,
        credential: str,
    ) -> ProtocolRequest:
        parsed = urlsplit(path)
        if (
            method != "POST"
            or parsed.path not in _PATHS
            or parsed.query not in _QUERIES
            or parsed.fragment
        ):
            raise ContractError("unsupported Anthropic-compatible request path")
        headers = {
            key: value
            for key, value in incoming_headers.items()
            if key.lower() not in _HOP_BY_HOP | _SENSITIVE | {"host", "content-length"}
        }
        headers["x-api-key"] = credential
        headers["content-length"] = str(len(body))
        model = ""
        try:
            payload: object = json.loads(body)
            if isinstance(payload, dict):
                raw_model = cast(dict[str, Any], payload).get("model")
                model = raw_model if isinstance(raw_model, str) else ""
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        upstream_path = parsed.path
        if parsed.query:
            upstream_path = f"{upstream_path}?{parsed.query}"
        return ProtocolRequest(upstream_path, headers, model)

    def usage_collector(self, content_type: str) -> UsageCollector:
        return _AnthropicUsageCollector(is_stream="text/event-stream" in content_type.lower())


class _AnthropicUsageCollector:
    _MAX_OBSERVATION_BYTES = 2 << 20

    def __init__(self, *, is_stream: bool) -> None:
        self._is_stream = is_stream
        self._buffer = bytearray()
        self._usage = {key: 0 for key in _USAGE_KEYS}

    def feed(self, chunk: bytes) -> None:
        if len(self._buffer) + len(chunk) <= self._MAX_OBSERVATION_BYTES:
            self._buffer.extend(chunk)

    def finish(self) -> Mapping[str, int]:
        if self._is_stream:
            for line in bytes(self._buffer).splitlines():
                if line.startswith(b"data:"):
                    self._observe_json(line.removeprefix(b"data:").strip())
        else:
            self._observe_json(bytes(self._buffer))
        return {key: value for key, value in self._usage.items() if value}

    def _observe_json(self, value: bytes) -> None:
        try:
            payload: object = json.loads(value)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        usage = cast(dict[str, Any], payload).get("usage")
        if not isinstance(usage, dict):
            message = cast(dict[str, Any], payload).get("message")
            usage = (
                cast(dict[str, Any], message).get("usage") if isinstance(message, dict) else None
            )
        if not isinstance(usage, dict):
            return
        usage_values = cast(dict[str, Any], usage)
        for key in _USAGE_KEYS:
            amount = usage_values.get(key)
            if isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
                self._usage[key] = max(self._usage[key], amount)
