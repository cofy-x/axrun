"""Claude Code 2.1.205 native stream-json to ``axrun.trajectory@1``."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from axrun.trajectories.policy import TrajectoryLimits, bounded_json_size, sanitize
from axrun.trajectories.schema import (
    TrajectoryContractError,
    TrajectoryEvent,
    canonical_event_bytes,
    validate_trajectory,
)

if TYPE_CHECKING:
    from axrun.trajectories.bundle import TrajectoryBundle

_TRAJECTORY = "/outputs/trajectory.jsonl"
_USAGE = "/outputs/usage.json"
_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
_DEFAULT_LIMITS = TrajectoryLimits()


@dataclass(frozen=True, slots=True)
class ClaudeCodeTrajectoryAdapter:
    version: str = "2.1.205"
    name: str = "claude-code"

    def build_bundle(self, episode: Any, result: Any, *, destination: Path) -> TrajectoryBundle:
        from axrun.trajectories.bundle import persist_trajectory_bundle

        return persist_trajectory_bundle(
            episode,
            result,
            destination=destination,
            trajectory_path=_TRAJECTORY,
            usage_path=_USAGE,
            harness=self.name,
            harness_version=self.version,
        )


class _Emitter:
    def __init__(self, *, limits: TrajectoryLimits, secrets: tuple[str, ...]) -> None:
        self.events: list[TrajectoryEvent] = []
        self.limits = limits
        self.secrets = secrets
        self.tool_events: dict[str, str] = {}
        self.tool_turns: dict[str, str] = {}
        self.turns: dict[str, str] = {}
        self.turn_events: dict[str, str] = {}
        self.usage_observations: set[tuple[str, tuple[int, ...]]] = set()
        self.aggregate = {key: 0 for key in _USAGE_KEYS}
        self.usage_count = 0
        self.last_assistant_event: str | None = None

    def emit(
        self,
        kind: str,
        actor: str,
        data: dict[str, Any],
        *,
        timestamp: str | None = None,
        turn_id: str | None = None,
        parent_event_id: str | None = None,
        model: str | None = None,
    ) -> str:
        if len(self.events) >= self.limits.max_events:
            raise ValueError("canonical trajectory exceeds event count bound")
        cleaned = cast(dict[str, Any], sanitize(data, self.secrets))
        if kind == "context" and isinstance(cleaned.get("content"), str):
            cleaned["content_sha256"] = hashlib.sha256(cleaned["content"].encode()).hexdigest()
        sequence = len(self.events)
        event = TrajectoryEvent(
            schema_version=1,
            sequence=sequence,
            event_id=f"event-{sequence:08d}",
            timestamp=timestamp,
            kind=kind,
            actor=actor,
            turn_id=turn_id,
            parent_event_id=parent_event_id,
            model=model,
            data=cleaned,
        )
        if len(canonical_event_bytes(event)) > self.limits.canonical_event_bytes:
            raise ValueError("canonical trajectory event exceeds size bound")
        self.events.append(event)
        if kind == "assistant_message":
            self.last_assistant_event = event.event_id
        return event.event_id

    def turn(self, native_id: object) -> str:
        key = str(native_id or f"anonymous-{len(self.turns)}")
        if key not in self.turns:
            self.turns[key] = f"turn-{len(self.turns):08d}"
        return self.turns[key]

    def usage(self, raw: object, *, source_id: str, model: str | None, parent: str | None) -> None:
        if not isinstance(raw, dict):
            return
        values = cast(dict[str, object], raw)
        normalized: dict[str, int] = {}
        for key in _USAGE_KEYS:
            value = values.get(key, 0)
            normalized[key] = (
                value
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                else 0
            )
        signature = (source_id, tuple(normalized[key] for key in _USAGE_KEYS))
        if signature in self.usage_observations:
            return
        self.usage_observations.add(signature)
        self.usage_count += 1
        for key, value in normalized.items():
            self.aggregate[key] = max(self.aggregate[key], value)
        self.emit("usage", "runtime", normalized, parent_event_id=parent, model=model)


def normalize_claude_stream(
    native_path: Path,
    prompt_path: Path,
    trajectory_path: Path,
    usage_path: Path,
    *,
    secrets: tuple[str, ...] = (),
    limits: TrajectoryLimits = _DEFAULT_LIMITS,
) -> tuple[TrajectoryEvent, ...]:
    if native_path.stat().st_size > limits.native_input_bytes:
        raise ValueError("Claude native trajectory exceeds input bound")
    prompt = prompt_path.read_text(encoding="utf-8")
    emitter = _Emitter(limits=limits, secrets=secrets)
    saw_session = False
    with native_path.open("rb") as source:
        for line_number, raw_line in enumerate(source, 1):
            if len(raw_line) > limits.native_line_bytes:
                raise ValueError("Claude native trajectory line exceeds bound")
            try:
                value: object = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise TrajectoryContractError(
                    f"Claude native trajectory line {line_number} is invalid JSON"
                ) from exc
            if not isinstance(value, dict):
                raise TrajectoryContractError("Claude native trajectory event must be an object")
            native = cast(dict[str, object], value)
            native_type = native.get("type")
            if native_type == "system" and native.get("subtype") == "init":
                if saw_session or emitter.events:
                    raise TrajectoryContractError("Claude init must be the first native event")
                session_data = {
                    "harness": "claude-code",
                    "harness_version": "2.1.205",
                    "runtime_version": _string(native.get("claude_code_version"), "unknown"),
                    "permission_mode": _optional_string(native.get("permissionMode")),
                    "tools": _strings(native.get("tools")),
                    "mcp_enabled": bool(_items(native.get("mcp_servers"))),
                    "skills_enabled": bool(_items(native.get("skills"))),
                }
                emitter.emit(
                    "session_start",
                    "runtime",
                    session_data,
                    model=_optional_string(native.get("model")),
                )
                emitter.emit(
                    "context",
                    "user",
                    {
                        "provenance": "axrun_task_prompt",
                        "content": prompt,
                        "content_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    },
                )
                saw_session = True
            elif native_type == "assistant":
                _map_assistant(native, emitter)
            elif native_type == "user":
                _map_user(native, emitter)
            elif native_type == "result":
                _map_result(native, emitter)
            elif native_type in {"error", "api_error"}:
                emitter.emit(
                    "error",
                    "runtime",
                    {
                        "code": _string(native.get("subtype"), "claude_error"),
                        "message": _string(native.get("error"), "Claude Code reported an error"),
                    },
                    timestamp=_optional_string(native.get("timestamp")),
                )
            elif native_type == "thinking_tokens":
                tokens = native.get("thinking_tokens")
                emitter.emit(
                    "reasoning_metadata",
                    "assistant",
                    {
                        "occurred": True,
                        "thinking_tokens": tokens
                        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0
                        else 0,
                    },
                    model=_optional_string(native.get("model")),
                )
            elif native_type == "stream_event":
                _map_stream_event(native, emitter)
            elif native_type == "system":
                text = native.get("message", native.get("text"))
                if isinstance(text, str) and text:
                    emitter.emit(
                        "context",
                        "runtime",
                        {
                            "provenance": "harness_exposed",
                            "content": text,
                            "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        },
                        timestamp=_optional_string(native.get("timestamp")),
                    )
            else:
                raise TrajectoryContractError(
                    f"unsupported Claude native event type: {native_type}"
                )
    if not saw_session:
        raise TrajectoryContractError("Claude native trajectory is missing system/init")
    events = tuple(emitter.events)
    validate_trajectory(events)
    trajectory_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with trajectory_path.open("wb") as target:
        for event in events:
            payload = canonical_event_bytes(event) + b"\n"
            total += len(payload)
            if total > limits.canonical_total_bytes:
                raise ValueError("canonical trajectory exceeds total size bound")
            target.write(payload)
    usage_path.write_text(
        json.dumps(
            {"schema_version": 1, "observations": emitter.usage_count, **emitter.aggregate},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return events


def claude_stage_exit_code(native_path: Path, agent_exit_code: int) -> int:
    """Classify the one bounded agent terminal state that still yields a candidate."""
    if agent_exit_code == 0:
        return 0
    final: object = None
    with native_path.open("rb") as source:
        for raw_line in source:
            if raw_line.strip():
                final = json.loads(raw_line)
    if isinstance(final, dict):
        values = cast(dict[str, object], final)
        if (
            values.get("type") == "result"
            and values.get("subtype") == "error_max_turns"
            and values.get("is_error") is True
        ):
            return 0
    return agent_exit_code if 1 <= agent_exit_code <= 255 else 1


def _map_assistant(native: dict[str, object], emitter: _Emitter) -> None:
    message = native.get("message")
    if not isinstance(message, dict):
        raise TrajectoryContractError("Claude assistant event is missing message")
    values = cast(dict[str, object], message)
    model = _optional_string(values.get("model"))
    turn = emitter.turn(values.get("id", native.get("uuid")))
    parent = _native_parent(native, emitter) or emitter.turn_events.get(turn)
    last = parent
    content = values.get("content")
    if not isinstance(content, list):
        raise TrajectoryContractError("Claude assistant content must be an array")
    for block_value in cast(list[object], content):
        if not isinstance(block_value, dict):
            raise TrajectoryContractError("Claude assistant content block must be an object")
        block = cast(dict[str, object], block_value)
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise TrajectoryContractError("Claude text block is invalid")
            last = emitter.emit(
                "assistant_message",
                "assistant",
                {"content": text, "stop_reason": _optional_string(values.get("stop_reason"))},
                turn_id=turn,
                parent_event_id=last,
                model=model,
            )
        elif block_type == "tool_use":
            call_id = _string(block.get("id"), "")
            name = _string(block.get("name"), "")
            arguments = block.get("input", {})
            if not call_id or not name or not isinstance(arguments, dict):
                raise TrajectoryContractError("Claude tool_use block is invalid")
            cleaned = sanitize(arguments, emitter.secrets)
            bounded_json_size(cleaned, emitter.limits.tool_arguments_bytes, "tool arguments")
            event_id = emitter.emit(
                "tool_call",
                "assistant",
                {"tool_call_id": call_id, "name": name, "arguments": cleaned},
                turn_id=turn,
                parent_event_id=last,
                model=model,
            )
            emitter.tool_events[call_id] = event_id
            emitter.tool_turns[call_id] = turn
            last = event_id
        elif block_type in {"thinking", "redacted_thinking"}:
            last = emitter.emit(
                "reasoning_metadata",
                "assistant",
                {"occurred": True},
                turn_id=turn,
                parent_event_id=last,
                model=model,
            )
        else:
            raise TrajectoryContractError(f"unsupported Claude assistant block: {block_type}")
    emitter.usage(
        values.get("usage"),
        source_id=_string(values.get("id"), str(native.get("uuid", "assistant"))),
        model=model,
        parent=last,
    )
    if last is not None:
        emitter.turn_events[turn] = last


def _map_user(native: dict[str, object], emitter: _Emitter) -> None:
    message = native.get("message")
    if not isinstance(message, dict):
        raise TrajectoryContractError("Claude user event is missing message")
    content = cast(dict[str, object], message).get("content")
    if isinstance(content, str):
        emitter.emit(
            "user_message",
            "user",
            {"content": content},
            timestamp=_optional_string(native.get("timestamp")),
            turn_id=emitter.turn(native.get("uuid")),
            parent_event_id=_native_parent(native, emitter),
        )
        return
    if not isinstance(content, list):
        raise TrajectoryContractError("Claude user content must be text or an array")
    for block_value in cast(list[object], content):
        if not isinstance(block_value, dict):
            raise TrajectoryContractError("Claude user content block must be an object")
        block = cast(dict[str, object], block_value)
        block_type = block.get("type")
        if block_type == "tool_result":
            call_id = _string(block.get("tool_use_id"), "")
            parent = emitter.tool_events.get(call_id)
            if not call_id or parent is None:
                raise TrajectoryContractError("Claude tool_result has no earlier tool_use")
            content_value = sanitize(block.get("content", ""), emitter.secrets)
            content_text = (
                content_value
                if isinstance(content_value, str)
                else json.dumps(content_value, sort_keys=True, separators=(",", ":"))
            )
            if len(content_text.encode()) > emitter.limits.tool_result_bytes:
                raise ValueError("tool result exceeds size bound")
            emitter.emit(
                "tool_result",
                "tool",
                {
                    "tool_call_id": call_id,
                    "content": content_text,
                    "is_error": block.get("is_error") is True,
                },
                timestamp=_optional_string(native.get("timestamp")),
                turn_id=emitter.tool_turns[call_id],
                parent_event_id=parent,
            )
        elif block_type == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise TrajectoryContractError("Claude user text block is invalid")
            emitter.emit(
                "user_message",
                "user",
                {"content": text},
                timestamp=_optional_string(native.get("timestamp")),
                turn_id=emitter.turn(native.get("uuid")),
                parent_event_id=_native_parent(native, emitter),
            )
        else:
            raise TrajectoryContractError(f"unsupported Claude user block: {block_type}")


def _map_result(native: dict[str, object], emitter: _Emitter) -> None:
    model_usage = native.get("modelUsage")
    model: str | None = None
    if isinstance(model_usage, dict) and model_usage:
        usage_values = cast(dict[object, object], model_usage)
        model = str(next(iter(usage_values)))
    parent = emitter.last_assistant_event
    emitter.usage(native.get("usage"), source_id="final-result", model=model, parent=parent)
    is_error = native.get("is_error") is True or native.get("subtype") not in {"success", None}
    emitter.emit(
        "final_result",
        "runtime",
        {
            "status": "error" if is_error else "success",
            "stop_reason": _optional_string(native.get("stop_reason")),
            "content": _optional_string(native.get("result")),
        },
        timestamp=_optional_string(native.get("timestamp")),
        parent_event_id=parent,
        model=model,
    )


def _map_stream_event(native: dict[str, object], emitter: _Emitter) -> None:
    event = native.get("event")
    if not isinstance(event, dict):
        raise TrajectoryContractError("Claude stream_event is missing event")
    values = cast(dict[str, object], event)
    delta = values.get("delta")
    if not isinstance(delta, dict):
        return
    delta_values = cast(dict[str, object], delta)
    delta_type = delta_values.get("type")
    if delta_type in {"thinking_delta", "signature_delta"}:
        token_count = delta_values.get("thinking_tokens")
        data: dict[str, Any] = {"occurred": True}
        if isinstance(token_count, int) and not isinstance(token_count, bool) and token_count >= 0:
            data["thinking_tokens"] = token_count
        emitter.emit(
            "reasoning_metadata",
            "assistant",
            data,
            model=_optional_string(native.get("model")),
        )


def _native_parent(native: dict[str, object], emitter: _Emitter) -> str | None:
    value = native.get("parent_tool_use_id")
    if value is None:
        return None
    parent = emitter.tool_events.get(str(value))
    if parent is None:
        raise TrajectoryContractError("Claude subagent parent tool_use is not earlier in stream")
    return parent


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _items(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [item for item in _items(value) if isinstance(item, str)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--usage", type=Path, required=True)
    parser.add_argument("--redact-value", action="append", default=[])
    parser.add_argument("--agent-exit-code", type=int, default=0)
    args = parser.parse_args()
    normalize_claude_stream(
        args.input,
        args.prompt,
        args.trajectory,
        args.usage,
        secrets=tuple(args.redact_value),
    )
    return claude_stage_exit_code(args.input, args.agent_exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
