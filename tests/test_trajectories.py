from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

import axrun.trajectories.bundle as bundle_module
from axrun.errors import ContractError
from axrun.models import (
    Artifact,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageResult,
    VerifierSpec,
)
from axrun.trajectories.adapters import ClaudeCodeTrajectoryAdapter
from axrun.trajectories.adapters.claude_code import normalize_claude_stream
from axrun.trajectories.bundle import (
    TrajectoryArtifact,
    load_trajectory_bundle,
    persist_trajectory_bundle,
)
from axrun.trajectories.policy import TrajectoryLimits
from axrun.trajectories.schema import (
    TrajectoryContractError,
    event_from_dict,
    load_trajectory_jsonl,
    validate_trajectory,
)

THINKING_MARKER = "RAW-THINKING-MARKER-MUST-DISAPPEAR"
SIGNATURE_MARKER = "RAW-SIGNATURE-MARKER-MUST-DISAPPEAR"
SECRET_MARKER = "CREDENTIAL-HEADER-MARKER-MUST-DISAPPEAR"


def _native_events() -> list[dict[str, Any]]:
    usage = {
        "input_tokens": 12,
        "output_tokens": 4,
        "cache_creation_input_tokens": 1,
        "cache_read_input_tokens": 2,
    }
    return [
        {
            "type": "system",
            "subtype": "init",
            "claude_code_version": "2.1.205",
            "model": "opaque-model[1m]",
            "permissionMode": "bypassPermissions",
            "tools": ["Read", "Edit"],
            "skills": [],
            "mcp_servers": [],
        },
        {
            "type": "assistant",
            "message": {
                "id": "message-1",
                "model": "opaque-model[1m]",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": THINKING_MARKER,
                        "signature": SIGNATURE_MARKER,
                    }
                ],
                "usage": usage,
            },
            "parent_tool_use_id": None,
        },
        {
            "type": "assistant",
            "message": {
                "id": "message-1",
                "model": "opaque-model[1m]",
                "content": [{"type": "text", "text": "I will inspect the file."}],
                "usage": usage,
            },
            "parent_tool_use_id": None,
        },
        {
            "type": "assistant",
            "message": {
                "id": "message-1",
                "model": "opaque-model[1m]",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "Read",
                        "input": {
                            "file_path": "/workspace/calculator.py",
                            "authorization": SECRET_MARKER,
                            "note": SECRET_MARKER,
                        },
                    }
                ],
                "usage": usage,
            },
            "parent_tool_use_id": None,
        },
        {
            "type": "user",
            "timestamp": "2026-09-18T12:00:00Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": f"file contents {SECRET_MARKER}",
                        "is_error": False,
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "id": "subagent-message",
                "model": "opaque-model[1m]",
                "content": [{"type": "text", "text": "Subagent-visible response."}],
            },
            "parent_tool_use_id": "call-1",
        },
        {"type": "thinking_tokens", "thinking_tokens": 23, "model": "opaque-model[1m]"},
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "Fixed the task.",
            "stop_reason": "end_turn",
            "modelUsage": {"opaque-model[1m]": {}},
            "usage": {
                "input_tokens": 20,
                "output_tokens": 8,
                "cache_creation_input_tokens": 1,
                "cache_read_input_tokens": 7,
            },
        },
    ]


def _write_native(path: Path, events: list[dict[str, Any]] | None = None) -> None:
    path.write_text(
        "".join(
            json.dumps(event, separators=(",", ":")) + "\n" for event in events or _native_events()
        ),
        encoding="utf-8",
    )


def _normalize(tmp_path: Path, *, limits: TrajectoryLimits | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    native = tmp_path / "native.jsonl"
    prompt = tmp_path / "prompt.txt"
    trajectory = tmp_path / "trajectory.jsonl"
    usage = tmp_path / "usage.json"
    _write_native(native)
    prompt.write_text("Fix add_one without changing its signature.", encoding="utf-8")
    events = normalize_claude_stream(
        native,
        prompt,
        trajectory,
        usage,
        secrets=(SECRET_MARKER,),
        **({"limits": limits} if limits is not None else {}),
    )
    return events, trajectory, usage, prompt


def test_strict_schema_round_trip_and_relationship_validation(tmp_path: Path) -> None:
    events, trajectory, _, _ = _normalize(tmp_path)
    assert load_trajectory_jsonl(trajectory) == events
    raw = asdict(events[0])
    with pytest.raises(TrajectoryContractError, match="unsupported"):
        event_from_dict({**raw, "schema_version": 2})
    with pytest.raises(TrajectoryContractError, match="fields"):
        event_from_dict({**raw, "provider_payload": {}})
    with pytest.raises(TrajectoryContractError, match="unknown trajectory event kind"):
        event_from_dict({**raw, "kind": "model_packet"})

    duplicate = replace(events[1], sequence=1, event_id=events[0].event_id)
    with pytest.raises(TrajectoryContractError, match="event_id must be unique"):
        validate_trajectory((events[0], duplicate))
    discontinuous = replace(events[1], sequence=2, event_id="event-00000002")
    with pytest.raises(TrajectoryContractError, match="contiguous"):
        validate_trajectory((events[0], discontinuous))
    future_parent = replace(events[1], parent_event_id="event-99999999")
    with pytest.raises(TrajectoryContractError, match="earlier"):
        validate_trajectory((events[0], future_parent))


def test_claude_mapping_is_deterministic_safe_and_preserves_tool_relationships(
    tmp_path: Path,
) -> None:
    first, trajectory, usage, prompt = _normalize(tmp_path / "first")
    second, second_path, _, _ = _normalize(tmp_path / "second")
    assert [event.as_dict() for event in first] == [event.as_dict() for event in second]
    assert trajectory.read_bytes() == second_path.read_bytes()
    kinds = [event.kind for event in first]
    assert kinds == [
        "session_start",
        "context",
        "reasoning_metadata",
        "usage",
        "assistant_message",
        "tool_call",
        "tool_result",
        "assistant_message",
        "reasoning_metadata",
        "usage",
        "final_result",
    ]
    context = first[1]
    assert context.data == {
        "provenance": "axrun_task_prompt",
        "content": prompt.read_text(),
        "content_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
    }
    tool_call = next(event for event in first if event.kind == "tool_call")
    tool_result = next(event for event in first if event.kind == "tool_result")
    assert tool_result.parent_event_id == tool_call.event_id
    assert tool_result.turn_id == tool_call.turn_id
    assert tool_call.model == "opaque-model[1m]"
    subagent = [event for event in first if event.kind == "assistant_message"][-1]
    assert subagent.parent_event_id == tool_call.event_id
    assert "authorization" not in tool_call.data["arguments"]
    serialized = trajectory.read_text()
    for marker in (THINKING_MARKER, SIGNATURE_MARKER, SECRET_MARKER):
        assert marker not in serialized
    assert json.loads(usage.read_text()) == {
        "schema_version": 1,
        "observations": 2,
        "input_tokens": 20,
        "output_tokens": 8,
        "cache_creation_input_tokens": 1,
        "cache_read_input_tokens": 7,
    }


def test_claude_visible_user_message_and_failed_result_mapping(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    native = tmp_path / "native.jsonl"
    prompt = tmp_path / "prompt.txt"
    trajectory = tmp_path / "trajectory.jsonl"
    usage = tmp_path / "usage.json"
    events = [
        {
            "type": "system",
            "subtype": "init",
            "claude_code_version": "2.1.205",
            "model": "opaque-model",
            "tools": [],
        },
        {"type": "user", "message": {"content": "Visible follow-up"}},
        {
            "type": "result",
            "subtype": "error_max_turns",
            "is_error": True,
            "result": "Stopped",
            "stop_reason": "max_turns",
            "usage": {},
        },
    ]
    _write_native(native, events)
    prompt.write_text("Task prompt")
    normalized = normalize_claude_stream(native, prompt, trajectory, usage)
    user = next(event for event in normalized if event.kind == "user_message")
    final = next(event for event in normalized if event.kind == "final_result")
    assert user.data["content"] == "Visible follow-up"
    assert final.data == {
        "status": "error",
        "stop_reason": "max_turns",
        "content": "Stopped",
    }


def test_trajectory_limits_fail_closed(tmp_path: Path) -> None:
    base = TrajectoryLimits()
    with pytest.raises(ValueError, match="input bound"):
        _normalize(tmp_path / "input", limits=replace(base, native_input_bytes=10))
    with pytest.raises(ValueError, match="line exceeds"):
        _normalize(tmp_path / "line", limits=replace(base, native_line_bytes=10))
    with pytest.raises(ValueError, match="event count"):
        _normalize(tmp_path / "events", limits=replace(base, max_events=2))
    with pytest.raises(ValueError, match="event exceeds"):
        _normalize(tmp_path / "event", limits=replace(base, canonical_event_bytes=20))
    with pytest.raises(ValueError, match="total size"):
        _normalize(tmp_path / "total", limits=replace(base, canonical_total_bytes=100))
    with pytest.raises(ValueError, match="tool arguments"):
        _normalize(tmp_path / "arguments", limits=replace(base, tool_arguments_bytes=10))
    with pytest.raises(ValueError, match="tool result"):
        _normalize(tmp_path / "result", limits=replace(base, tool_result_bytes=10))


def _episode(tmp_path: Path) -> ResolvedEpisode:
    prompt = tmp_path / "episode-prompt.txt"
    prompt.write_text("task", encoding="utf-8")
    return ResolvedEpisode(
        1,
        "trajectory-episode",
        "task",
        "b" * 64,
        "a" * 40,
        str(prompt),
        "env-i",
        "env-v",
        HarnessSpec("claude-code", "2.1.205"),
        VerifierSpec("synthetic-code-task", "1"),
    )


def _artifact(name: str, path: Path, media_type: str) -> Artifact:
    payload = path.read_bytes()
    return Artifact(name, str(path), len(payload), hashlib.sha256(payload).hexdigest(), media_type)


def test_trajectory_bundle_is_atomic_content_addressed_and_detects_tampering(
    tmp_path: Path,
) -> None:
    _, trajectory, usage, _ = _normalize(tmp_path / "normalized")
    result = StageResult(
        ExecutionRef("env-i", "run-i", "alloc-i"),
        0,
        "",
        (
            _artifact("/outputs/trajectory.jsonl", trajectory, "application/x-ndjson"),
            _artifact("/outputs/usage.json", usage, "application/json"),
        ),
    )
    destination = tmp_path / "bundles"
    bundle = persist_trajectory_bundle(
        _episode(tmp_path),
        result,
        destination=destination,
        trajectory_path="/outputs/trajectory.jsonl",
        usage_path="/outputs/usage.json",
        harness="claude-code",
        harness_version="2.1.205",
    )
    manifest = Path(bundle.root) / "trajectory-manifest.json"
    assert load_trajectory_bundle(manifest) == bundle
    assert (
        persist_trajectory_bundle(
            _episode(tmp_path),
            result,
            destination=destination,
            trajectory_path="/outputs/trajectory.jsonl",
            usage_path="/outputs/usage.json",
            harness="claude-code",
            harness_version="2.1.205",
        ).digest
        == bundle.digest
    )
    (Path(bundle.root) / "usage.json").write_text("{}\n")
    with pytest.raises(ContractError, match="integrity"):
        load_trajectory_bundle(manifest)
    with pytest.raises(ContractError, match="safe filename"):
        TrajectoryArtifact("../trajectory.jsonl", 1, "a" * 64)


def test_trajectory_bundle_rejects_symlink_manifest(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ContractError, match="regular file"):
        load_trajectory_bundle(link)


def test_trajectory_bundle_crash_before_atomic_publish_leaves_no_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, trajectory, usage, _ = _normalize(tmp_path / "normalized-crash")
    result = StageResult(
        ExecutionRef("env-i", "run-crash", "alloc-crash"),
        0,
        "",
        (
            _artifact("/outputs/trajectory.jsonl", trajectory, "application/x-ndjson"),
            _artifact("/outputs/usage.json", usage, "application/json"),
        ),
    )
    destination = tmp_path / "crash-bundles"
    monkeypatch.setattr(
        bundle_module.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("simulated crash")),
    )
    with pytest.raises(OSError, match="simulated crash"):
        persist_trajectory_bundle(
            _episode(tmp_path),
            result,
            destination=destination,
            trajectory_path="/outputs/trajectory.jsonl",
            usage_path="/outputs/usage.json",
            harness="claude-code",
            harness_version="2.1.205",
        )
    assert not list(destination.glob("sha256/*/trajectory-manifest.json"))


def test_claude_trajectory_adapter_builds_bundle_from_sealed_outputs(tmp_path: Path) -> None:
    events, trajectory, usage, _ = _normalize(tmp_path / "adapter")
    result = StageResult(
        ExecutionRef("env-i", "run-i", "alloc-i"),
        0,
        "",
        (
            _artifact("/outputs/trajectory.jsonl", trajectory, "application/x-ndjson"),
            _artifact("/outputs/usage.json", usage, "application/json"),
        ),
    )
    bundle = ClaudeCodeTrajectoryAdapter().build_bundle(
        _episode(tmp_path), result, destination=tmp_path / "adapter-bundles"
    )
    assert bundle.format == "axrun.trajectory@1" and bundle.event_count == len(events)
