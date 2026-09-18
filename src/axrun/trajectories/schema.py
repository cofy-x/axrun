"""Strict, provider-neutral ``axrun.trajectory@1`` JSONL schema."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1
FORMAT = "axrun.trajectory@1"
KINDS = frozenset(
    {
        "session_start",
        "context",
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "reasoning_metadata",
        "usage",
        "final_result",
        "error",
    }
)
ACTORS = frozenset({"runtime", "user", "assistant", "tool"})
_ACTORS_BY_KIND = {
    "session_start": {"runtime"},
    "context": {"runtime", "user"},
    "user_message": {"user"},
    "assistant_message": {"assistant"},
    "tool_call": {"assistant"},
    "tool_result": {"tool"},
    "reasoning_metadata": {"assistant"},
    "usage": {"runtime"},
    "final_result": {"runtime"},
    "error": {"runtime"},
}
_TOP_LEVEL = {
    "schema_version",
    "sequence",
    "event_id",
    "timestamp",
    "kind",
    "actor",
    "turn_id",
    "parent_event_id",
    "model",
    "data",
}
_DATA_FIELDS = {
    "session_start": {
        "harness",
        "harness_version",
        "runtime_version",
        "permission_mode",
        "tools",
        "mcp_enabled",
        "skills_enabled",
    },
    "context": {"provenance", "content", "content_sha256"},
    "user_message": {"content"},
    "assistant_message": {"content", "stop_reason"},
    "tool_call": {"tool_call_id", "name", "arguments"},
    "tool_result": {"tool_call_id", "content", "is_error"},
    "reasoning_metadata": {
        "occurred",
        "thinking_tokens",
        "estimated_token_delta",
        "duration_ms",
        "reasoning_summary",
    },
    "usage": {
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    },
    "final_result": {"status", "stop_reason", "content"},
    "error": {"code", "message"},
}


class TrajectoryContractError(ValueError):
    """The canonical trajectory is malformed or violates event relationships."""


@dataclass(frozen=True, slots=True)
class TrajectoryEvent:
    schema_version: int
    sequence: int
    event_id: str
    timestamp: str | None
    kind: str
    actor: str
    turn_id: str | None
    parent_event_id: str | None
    model: str | None
    data: dict[str, Any]

    def __post_init__(self) -> None:
        validate_event(self)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def event_from_dict(raw: dict[str, Any]) -> TrajectoryEvent:
    unknown = set(raw) - _TOP_LEVEL
    missing = _TOP_LEVEL - set(raw)
    if unknown or missing:
        raise TrajectoryContractError(
            "invalid trajectory event fields "
            f"(missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    return TrajectoryEvent(**raw)


def validate_event(event: TrajectoryEvent) -> None:
    if event.schema_version != SCHEMA_VERSION:
        raise TrajectoryContractError(f"unsupported trajectory schema {event.schema_version}")
    if not _is_nonnegative_integer(event.sequence):
        raise TrajectoryContractError("trajectory sequence must be a non-negative integer")
    if re.fullmatch(r"event-[0-9]{8}", event.event_id) is None:
        raise TrajectoryContractError("trajectory event_id is not canonical")
    if event.kind not in KINDS:
        raise TrajectoryContractError(f"unknown trajectory event kind: {event.kind}")
    if event.actor not in ACTORS:
        raise TrajectoryContractError(f"unknown trajectory actor: {event.actor}")
    if event.actor not in _ACTORS_BY_KIND[event.kind]:
        raise TrajectoryContractError(f"invalid actor for {event.kind}: {event.actor}")
    if event.timestamp is not None:
        _validate_timestamp(event.timestamp)
    for name, value in (("turn_id", event.turn_id), ("parent_event_id", event.parent_event_id)):
        if not _is_optional_nonempty_string(value):
            raise TrajectoryContractError(f"trajectory {name} must be null or a non-empty string")
    if not _is_optional_nonempty_string(event.model):
        raise TrajectoryContractError("trajectory model must be null or a non-empty string")
    if not _is_dict(event.data):
        raise TrajectoryContractError("trajectory data must be an object")
    allowed = _DATA_FIELDS[event.kind]
    unknown = set(event.data) - allowed
    if unknown:
        raise TrajectoryContractError(
            f"unknown {event.kind} data fields: {', '.join(sorted(unknown))}"
        )
    _validate_data(event.kind, event.data)


def validate_trajectory(events: tuple[TrajectoryEvent, ...]) -> None:
    if not events:
        raise TrajectoryContractError("trajectory must contain at least one event")
    seen: dict[str, TrajectoryEvent] = {}
    tool_calls: dict[str, str] = {}
    tool_turns: dict[str, str | None] = {}
    session_count = 0
    for expected, event in enumerate(events):
        if event.sequence != expected:
            raise TrajectoryContractError("trajectory sequence must be contiguous from zero")
        if event.event_id in seen:
            raise TrajectoryContractError("trajectory event_id must be unique")
        if event.parent_event_id is not None and event.parent_event_id not in seen:
            raise TrajectoryContractError("trajectory parent must reference an earlier event")
        if event.kind == "tool_call":
            call_id = cast(str, event.data["tool_call_id"])
            if call_id in tool_calls:
                raise TrajectoryContractError("tool_call_id must be unique")
            tool_calls[call_id] = event.event_id
            tool_turns[call_id] = event.turn_id
        elif event.kind == "tool_result":
            call_id = cast(str, event.data["tool_call_id"])
            parent = tool_calls.get(call_id)
            if parent is None or event.parent_event_id != parent:
                raise TrajectoryContractError("tool_result must reference its earlier tool_call")
            if event.turn_id != tool_turns[call_id]:
                raise TrajectoryContractError("tool_result must preserve its tool_call turn")
        if event.kind == "session_start":
            session_count += 1
        seen[event.event_id] = event
    if events[0].kind != "session_start":
        raise TrajectoryContractError("trajectory must begin with session_start")
    if session_count != 1:
        raise TrajectoryContractError("trajectory must contain exactly one session_start")


def load_trajectory_jsonl(path: Path) -> tuple[TrajectoryEvent, ...]:
    events: list[TrajectoryEvent] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                raw: object = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrajectoryContractError(
                    f"trajectory line {line_number} is not valid JSON"
                ) from exc
            if not isinstance(raw, dict):
                raise TrajectoryContractError(f"trajectory line {line_number} must be an object")
            events.append(event_from_dict(cast(dict[str, Any], raw)))
    result = tuple(events)
    validate_trajectory(result)
    return result


def canonical_event_bytes(event: TrajectoryEvent) -> bytes:
    return json.dumps(
        event.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _validate_timestamp(value: str) -> None:
    if not value.endswith(("Z", "+00:00")):
        raise TrajectoryContractError("trajectory timestamp must be UTC RFC3339")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrajectoryContractError("trajectory timestamp must be UTC RFC3339") from exc


def _validate_data(kind: str, data: dict[str, Any]) -> None:
    required: dict[str, set[str]] = {
        "session_start": {"harness", "harness_version", "runtime_version", "tools"},
        "context": {"provenance", "content", "content_sha256"},
        "user_message": {"content"},
        "assistant_message": {"content"},
        "tool_call": {"tool_call_id", "name", "arguments"},
        "tool_result": {"tool_call_id", "content", "is_error"},
        "reasoning_metadata": {"occurred"},
        "usage": set(_DATA_FIELDS["usage"]),
        "final_result": {"status"},
        "error": {"code", "message"},
    }
    missing = required[kind] - set(data)
    if missing:
        raise TrajectoryContractError(f"missing {kind} data fields: {', '.join(sorted(missing))}")
    for key in _string_fields(kind):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            raise TrajectoryContractError(f"{kind}.{key} must be a string or null")
    if kind == "session_start":
        tools = data["tools"]
        if not isinstance(tools, list) or any(
            not isinstance(item, str) for item in cast(list[object], tools)
        ):
            raise TrajectoryContractError("session_start.tools must be a string array")
        for key in ("mcp_enabled", "skills_enabled"):
            value = data.get(key)
            if value is not None and not isinstance(value, bool):
                raise TrajectoryContractError(f"session_start.{key} must be boolean")
    elif kind == "context":
        if data["provenance"] not in {"axrun_task_prompt", "harness_exposed"}:
            raise TrajectoryContractError("context.provenance is unknown")
        digest = data["content_sha256"]
        if not _is_sha256(digest):
            raise TrajectoryContractError("context.content_sha256 must be lowercase SHA-256")
        if hashlib.sha256(cast(str, data["content"]).encode()).hexdigest() != digest:
            raise TrajectoryContractError("context content digest mismatch")
    elif kind == "tool_call":
        if not isinstance(data["arguments"], dict):
            raise TrajectoryContractError("tool_call.arguments must be an object")
    elif kind == "tool_result":
        if not isinstance(data["is_error"], bool):
            raise TrajectoryContractError("tool_result.is_error must be boolean")
    elif kind == "reasoning_metadata":
        if not isinstance(data["occurred"], bool):
            raise TrajectoryContractError("reasoning_metadata.occurred must be boolean")
        for key in ("thinking_tokens", "estimated_token_delta", "duration_ms"):
            value = data.get(key)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise TrajectoryContractError(f"reasoning_metadata.{key} must be non-negative")
    elif kind == "usage":
        for key in _DATA_FIELDS["usage"]:
            value = data[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise TrajectoryContractError(f"usage.{key} must be non-negative")
    elif kind == "final_result" and data["status"] not in {"success", "error"}:
        raise TrajectoryContractError("final_result.status must be success or error")


def _string_fields(kind: str) -> set[str]:
    return {
        "session_start": {"harness", "harness_version", "runtime_version", "permission_mode"},
        "context": {"provenance", "content", "content_sha256"},
        "user_message": {"content"},
        "assistant_message": {"content", "stop_reason"},
        "tool_call": {"tool_call_id", "name"},
        "tool_result": {"tool_call_id", "content"},
        "reasoning_metadata": {"reasoning_summary"},
        "usage": set[str](),
        "final_result": {"status", "stop_reason", "content"},
        "error": {"code", "message"},
    }[kind]


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_optional_nonempty_string(value: object) -> bool:
    return value is None or (isinstance(value, str) and bool(value))


def _is_dict(value: object) -> bool:
    return isinstance(value, dict)
