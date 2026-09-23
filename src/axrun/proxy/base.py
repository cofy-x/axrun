"""Small protocol boundary used by one-stage model proxy instances."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProtocolRequest:
    upstream_path: str
    headers: Mapping[str, str]
    model: str


@dataclass(frozen=True)
class ModelPreflight:
    path: str
    headers: Mapping[str, str]
    body: bytes
    expected_status: int = 200


class UsageCollector(Protocol):
    def feed(self, chunk: bytes) -> None: ...

    def finish(self) -> Mapping[str, int]: ...


class ModelProtocol(Protocol):
    @property
    def name(self) -> str: ...

    def prepare_request(
        self,
        *,
        method: str,
        path: str,
        incoming_headers: Mapping[str, str],
        body: bytes,
        credential: str,
    ) -> ProtocolRequest: ...

    def usage_collector(self, content_type: str) -> UsageCollector: ...

    def preflight(self, model: str) -> ModelPreflight: ...


class ModelProxyInstance(Protocol):
    @property
    def local_target(self) -> str: ...

    def preflight(self, model: str) -> ModelPreflight: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def snapshot(self) -> ModelProxySnapshot: ...

    @property
    def last_summary(self) -> ModelRequestSummary | None: ...


@dataclass(frozen=True)
class ModelRequestSummary:
    method: str
    protocol: str
    path: str
    status: int
    request_bytes: int
    response_bytes: int
    latency_ms: int
    model: str
    usage: Mapping[str, int]
    reason_code: str

    def as_safe_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "protocol": self.protocol,
            "path": self.path,
            "status": self.status,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "usage": dict(self.usage),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class ModelProxySnapshot:
    request_count: int
    requests_in_flight: int
    last_activity_at: str
    last_summary: ModelRequestSummary | None
