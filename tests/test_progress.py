from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from axrun.errors import ContractError, DiagnosedInfrastructureError
from axrun.lifecycle.stage_progress import StageProgressObserver
from axrun.models import (
    EpisodePhase,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    VerifierSpec,
)
from axrun.progress.schema import (
    MAX_PROGRESS_BYTES,
    ProgressSnapshot,
    RuntimeProgress,
    canonical_progress_bytes,
    progress_snapshot_from_bytes,
)
from axrun.progress.store import ProgressStore
from axrun.proxy.base import ModelProxySnapshot, ModelRequestSummary
from axrun.store import EpisodeStore


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _snapshot() -> ProgressSnapshot:
    return ProgressSnapshot(
        1,
        "axrun.progress@1",
        "episode",
        "run",
        "allocation",
        "inference_running",
        1,
        _now(),
        True,
        2,
        3,
        "tool_call",
        "Read",
        100,
        50,
        4,
        0,
        "POST",
        "anthropic",
        "/v1/messages?beta=true",
        200,
        "upstream_response",
        10,
        20,
        30,
        {"input_tokens": 2, "output_tokens": 1},
        _now(),
        _now(),
        0,
        "tool_activity",
    )


def _episode(tmp_path: Path) -> ResolvedEpisode:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("secret prompt that must not enter progress")
    return ResolvedEpisode(
        1,
        "episode",
        "task",
        "a" * 64,
        "b" * 40,
        str(prompt),
        "env",
        "env",
        HarnessSpec("claude-code", "2.1.205", config={"model": "opaque"}),
        VerifierSpec("command-verifier", "1"),
    )


class _Proxy:
    def __init__(self) -> None:
        self.value = ModelProxySnapshot(
            1,
            0,
            _now(),
            ModelRequestSummary(
                "POST",
                "anthropic",
                "/v1/messages?beta=true",
                200,
                12,
                34,
                56,
                "opaque-model",
                {"input_tokens": 3, "output_tokens": 2},
                "upstream_response",
            ),
        )

    def snapshot(self) -> ModelProxySnapshot:
        return self.value


class _Allocation:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read_file(self, path: str, *, rpc_timeout: float | None = None) -> bytes:
        assert path == "/run/axrun/progress.json" and rpc_timeout == 5.0
        return self.payload


class _FlakyAllocation(_Allocation):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.reads = 0

    def read_file(self, path: str, *, rpc_timeout: float | None = None) -> bytes:
        self.reads += 1
        if self.reads > 1:
            raise RuntimeError("Allocation is no longer readable")
        return super().read_file(path, rpc_timeout=rpc_timeout)


def _runtime() -> RuntimeProgress:
    return RuntimeProgress(
        1,
        "axrun.claude-runtime-progress@1",
        2,
        _now(),
        True,
        4,
        5,
        "tool_result",
        "Read",
        123,
        45,
        _now(),
    )


def test_progress_contract_is_closed_bounded_and_safe() -> None:
    snapshot = _snapshot()
    payload = canonical_progress_bytes(snapshot)
    assert progress_snapshot_from_bytes(payload) == snapshot
    safe = payload.decode()
    for forbidden in (
        "prompt",
        "message_body",
        "arguments",
        "tool_result",
        "authorization",
        "x-api-key",
        "axrun-local-tunnel",
    ):
        assert forbidden not in safe.lower()

    raw = asdict(snapshot)
    raw["body"] = "forbidden"
    with pytest.raises(ContractError, match="fields"):
        progress_snapshot_from_bytes(json.dumps(raw).encode())
    with pytest.raises(ContractError, match="unsupported"):
        progress_snapshot_from_bytes(canonical_progress_bytes(replace(snapshot, schema_version=2)))
    with pytest.raises(ContractError, match="size bound"):
        progress_snapshot_from_bytes(b"x" * (MAX_PROGRESS_BYTES + 1))


def test_progress_store_rejects_path_traversal_and_atomic_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProgressStore(tmp_path)
    for unsafe in ("../episode", "a/b", r"a\b"):
        with pytest.raises(ContractError, match="safe path"):
            store.path_for(unsafe)

    def fail_replace(_source: str, _destination: str) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated crash"):
        store.save(_snapshot())
    assert not store.path_for("episode").exists()
    assert list((tmp_path / "progress" / "episode").glob(".progress.json.*")) == []


def test_observer_merges_runtime_and_proxy_and_cleanup_is_idempotent(tmp_path: Path) -> None:
    store = EpisodeStore(tmp_path / "state")
    record = store.initialize(_episode(tmp_path))
    record.phase = EpisodePhase.INFERENCE_RUNNING
    record.inference = ExecutionRef("env", "run", "allocation")
    store.save(record)
    allocation = _Allocation(canonical_progress_bytes(_runtime()))
    observer = StageProgressObserver(
        episode_id="episode",
        store=store,
        proxy=_Proxy(),  # type: ignore[arg-type]
        poll_seconds=0.01,
    )
    observer.start(record.inference, allocation)
    time.sleep(0.04)
    observer.close()
    observer.close()

    updated = store.load("episode")
    assert updated is not None and updated.progress_revision >= 2
    snapshot = ProgressStore(store.root).load("episode")
    assert snapshot is not None
    assert snapshot.native_event_count == 4
    assert snapshot.request_count == 1
    assert snapshot.last_model_path == "/v1/messages?beta=true"
    assert snapshot.state_reason_code == "tool_activity"
    assert snapshot.last_model_usage == {"input_tokens": 3, "output_tokens": 2}


def test_observer_preserves_last_runtime_counters_when_allocation_becomes_unreadable(
    tmp_path: Path,
) -> None:
    store = EpisodeStore(tmp_path / "state")
    record = store.initialize(_episode(tmp_path))
    record.phase = EpisodePhase.INFERENCE_RUNNING
    record.inference = ExecutionRef("env", "run", "allocation")
    store.save(record)
    observer = StageProgressObserver(
        episode_id="episode",
        store=store,
        proxy=_Proxy(),  # type: ignore[arg-type]
        poll_seconds=60.0,
    )
    observer.start(record.inference, _FlakyAllocation(canonical_progress_bytes(_runtime())))
    observer._sample()
    observer._sample()
    observer.close()

    snapshot = ProgressStore(store.root).load("episode")
    assert snapshot is not None
    assert snapshot.state_reason_code == "progress_unavailable"
    assert snapshot.native_event_count == 4
    assert snapshot.canonical_event_count == 5
    assert snapshot.latest_event_kind == "tool_result"
    assert snapshot.latest_tool_name == "Read"
    assert snapshot.trajectory_bytes == 123
    assert snapshot.usage_bytes == 45


def test_invalid_observed_progress_is_infrastructure_diagnostic(tmp_path: Path) -> None:
    store = EpisodeStore(tmp_path / "state")
    record = store.initialize(_episode(tmp_path))
    record.phase = EpisodePhase.INFERENCE_RUNNING
    record.inference = ExecutionRef("env", "run", "allocation")
    store.save(record)
    observer = StageProgressObserver(
        episode_id="episode",
        store=store,
        proxy=_Proxy(),  # type: ignore[arg-type]
        poll_seconds=0.01,
    )
    observer.start(record.inference, _Allocation(b'{"unknown":true}\n'))
    time.sleep(0.04)
    with pytest.raises(DiagnosedInfrastructureError) as captured:
        observer.close()
    assert captured.value.diagnostic_code == "progress_observer_failed"
    assert captured.value.details == {"reason_code": "invalid_progress_contract"}
    observer.close()
