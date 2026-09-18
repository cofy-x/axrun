"""Small protocol boundary used by one-stage model proxy instances."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProtocolRequest:
    upstream_path: str
    headers: Mapping[str, str]
    model: str


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


class ModelProxyInstance(Protocol):
    @property
    def local_target(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


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
