"""Closed JSON contracts for safe inference progress."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, cast

from axrun.errors import ContractError
from axrun.trajectories.schema import KINDS

RUNTIME_PROGRESS_FORMAT = "axrun.claude-runtime-progress@1"
PROGRESS_FORMAT = "axrun.progress@1"
MAX_PROGRESS_BYTES = 16 << 10
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_MODEL_PATHS = frozenset(
    {
        "",
        "/v1/messages",
        "/v1/messages?beta=true",
        "/v1/messages/count_tokens",
        "/v1/messages/count_tokens?beta=true",
    }
)
_REASON_CODES = frozenset(
    {
        "",
        "proxy_protocol_rejected",
        "proxy_upstream_error",
        "proxy_upstream_timeout",
        "upstream_response",
    }
)
_STATE_CODES = frozenset(
    {
        "agent_active",
        "waiting_for_model",
        "tool_activity",
        "no_agent_heartbeat",
        "model_request_in_flight",
        "model_idle",
        "process_exited",
        "progress_unavailable",
    }
)
_USAGE_KEYS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeProgress:
    schema_version: int
    format: str
    revision: int
    updated_at: str
    process_alive: bool
    native_event_count: int
    canonical_event_count: int
    latest_event_kind: str
    latest_tool_name: str
    trajectory_bytes: int
    usage_bytes: int
    last_agent_activity_at: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.format != RUNTIME_PROGRESS_FORMAT:
            raise ContractError("unsupported Claude runtime progress contract")
        _validate_common_progress(self)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    schema_version: int
    format: str
    episode_id: str
    run_id: str
    allocation_id: str
    phase: str
    revision: int
    updated_at: str
    process_alive: bool
    native_event_count: int
    canonical_event_count: int
    latest_event_kind: str
    latest_tool_name: str
    trajectory_bytes: int
    usage_bytes: int
    request_count: int
    model_requests_in_flight: int
    last_model_method: str
    last_model_protocol: str
    last_model_path: str
    last_model_status: int
    last_model_reason_code: str
    last_model_request_bytes: int
    last_model_response_bytes: int
    last_model_latency_ms: int
    last_model_usage: dict[str, int]
    last_agent_activity_at: str
    last_model_activity_at: str
    stale_seconds: int
    state_reason_code: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.format != PROGRESS_FORMAT:
            raise ContractError("unsupported inference progress contract")
        if (
            not self.episode_id
            or any(value in self.episode_id for value in ("/", "\\", ".."))
            or not self.run_id
            or not self.allocation_id
        ):
            raise ContractError("progress identities are invalid")
        if self.phase != "inference_running":
            raise ContractError("progress phase must be inference_running")
        _validate_common_progress(self)
        for name in (
            "request_count",
            "model_requests_in_flight",
            "last_model_status",
            "last_model_request_bytes",
            "last_model_response_bytes",
            "last_model_latency_ms",
            "stale_seconds",
        ):
            _nonnegative(getattr(self, name), name)
        if self.last_model_method not in {"", "POST"}:
            raise ContractError("progress model method is invalid")
        if self.last_model_protocol not in {"", "anthropic"}:
            raise ContractError("progress model protocol is invalid")
        if self.last_model_path not in _MODEL_PATHS:
            raise ContractError("progress model path is invalid")
        if self.last_model_reason_code not in _REASON_CODES:
            raise ContractError("progress model reason code is invalid")
        if set(self.last_model_usage) - _USAGE_KEYS:
            raise ContractError("progress model usage fields are invalid")
        for key, value in self.last_model_usage.items():
            _nonnegative(value, f"last_model_usage.{key}")
        _optional_timestamp(self.last_model_activity_at, "last_model_activity_at")
        if self.state_reason_code not in _STATE_CODES:
            raise ContractError("progress state reason code is invalid")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def runtime_progress_from_bytes(payload: bytes) -> RuntimeProgress:
    values = _values_from_bytes(payload, set(RuntimeProgress.__dataclass_fields__))
    try:
        return RuntimeProgress(**values)
    except (AttributeError, TypeError) as exc:
        raise ContractError("progress payload field types are invalid") from exc


def progress_snapshot_from_bytes(payload: bytes) -> ProgressSnapshot:
    values = _values_from_bytes(payload, set(ProgressSnapshot.__dataclass_fields__))
    try:
        return ProgressSnapshot(**values)
    except (AttributeError, TypeError) as exc:
        raise ContractError("progress payload field types are invalid") from exc


def canonical_progress_bytes(value: RuntimeProgress | ProgressSnapshot) -> bytes:
    payload = json.dumps(value.as_dict(), sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if len(payload) > MAX_PROGRESS_BYTES:
        raise ContractError("progress payload exceeds size bound")
    return payload


def _values_from_bytes(payload: bytes, expected: set[str]) -> dict[str, Any]:
    if len(payload) > MAX_PROGRESS_BYTES:
        raise ContractError("progress payload exceeds size bound")
    try:
        raw: object = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("progress payload is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ContractError("progress payload must be an object")
    values = cast(dict[str, Any], raw)
    if set(values) != expected:
        raise ContractError("progress payload fields are invalid")
    return values


def _validate_common_progress(value: RuntimeProgress | ProgressSnapshot) -> None:
    for name in (
        "revision",
        "native_event_count",
        "canonical_event_count",
        "trajectory_bytes",
        "usage_bytes",
    ):
        _nonnegative(getattr(value, name), name)
    if not _is_bool(value.process_alive):
        raise ContractError("progress process_alive must be boolean")
    _timestamp(value.updated_at, "updated_at")
    _optional_timestamp(value.last_agent_activity_at, "last_agent_activity_at")
    if value.latest_event_kind and value.latest_event_kind not in KINDS:
        raise ContractError("progress latest event kind is invalid")
    if value.latest_tool_name and _TOOL_NAME.fullmatch(value.latest_tool_name) is None:
        raise ContractError("progress tool name is invalid")


def _nonnegative(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(f"progress {name} must be a non-negative integer")


def _optional_timestamp(value: str, name: str) -> None:
    if value:
        _timestamp(value, name)


def _timestamp(value: str, name: str) -> None:
    if not _is_utc_timestamp(value):
        raise ContractError(f"progress {name} must be UTC RFC3339")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"progress {name} must be UTC RFC3339") from exc


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_utc_timestamp(value: Any) -> bool:
    return isinstance(value, str) and value.endswith(("Z", "+00:00"))
