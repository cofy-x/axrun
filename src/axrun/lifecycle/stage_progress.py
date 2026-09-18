"""Caller-side observer for the bounded Allocation runtime progress file."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from axrun.errors import ContractError, DiagnosedInfrastructureError, InfrastructureError
from axrun.models import EpisodePhase, ExecutionRef
from axrun.progress.schema import (
    PROGRESS_FORMAT,
    ProgressSnapshot,
    RuntimeProgress,
    runtime_progress_from_bytes,
)
from axrun.progress.store import ProgressStore
from axrun.proxy.base import ModelProxyInstance, ModelProxySnapshot
from axrun.store import EpisodeStore

_REMOTE_PROGRESS = "/run/axrun/progress.json"


class StageProgressObserver:
    """Poll one Allocation and persist only the closed safe progress contract."""

    def __init__(
        self,
        *,
        episode_id: str,
        store: EpisodeStore,
        proxy: ModelProxyInstance,
        poll_seconds: float = 1.0,
        stale_after_seconds: float = 30.0,
    ) -> None:
        if poll_seconds <= 0 or stale_after_seconds <= 0:
            raise ContractError("progress timing bounds must be positive")
        self._episode_id = episode_id
        self._store = store
        self._progress_store = ProgressStore(store.root)
        self._proxy = proxy
        self._poll_seconds = poll_seconds
        self._stale_after_seconds = stale_after_seconds
        self._allocation: Any | None = None
        self._execution: ExecutionRef | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failure_reason = ""
        self._revision = 0
        self._closed = False

    def start(self, execution: ExecutionRef, allocation: Any) -> None:
        if self._thread is not None:
            raise InfrastructureError("progress observer has already started")
        if not execution.allocation_id:
            raise InfrastructureError("progress observer requires a persisted Allocation")
        self._execution = execution
        self._allocation = allocation
        self._publish_unavailable()
        thread = threading.Thread(
            target=self._observe,
            name="axrun-stage-progress",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        thread, self._thread = self._thread, None
        self._stop.set()
        if thread is not None:
            thread.join(timeout=max(5.0, self._poll_seconds + 2.0))
            if thread.is_alive() and not self._failure_reason:
                self._failure_reason = "observer_shutdown_timeout"
        if self._failure_reason:
            raise DiagnosedInfrastructureError(
                "progress_observer_failed", {"reason_code": self._failure_reason}
            )

    def _observe(self) -> None:
        try:
            while not self._stop.wait(self._poll_seconds):
                self._sample()
            self._sample()
        except ContractError:
            self._failure_reason = "invalid_progress_contract"
        except Exception:
            self._failure_reason = "observer_internal_error"

    def _sample(self) -> None:
        allocation = self._allocation
        execution = self._execution
        if allocation is None or execution is None:
            raise InfrastructureError("progress observer was not bound")
        try:
            payload = allocation.read_file(_REMOTE_PROGRESS, rpc_timeout=5.0)
        except Exception:
            self._publish_unavailable()
            return
        runtime = runtime_progress_from_bytes(payload)
        self._publish(self._merge(runtime, self._proxy.snapshot(), execution))

    def _publish_unavailable(self) -> None:
        execution = self._execution
        if execution is None or not execution.allocation_id:
            return
        model = self._proxy.snapshot()
        now = _now()
        self._revision += 1
        summary = model.last_summary
        snapshot = ProgressSnapshot(
            schema_version=1,
            format=PROGRESS_FORMAT,
            episode_id=self._episode_id,
            run_id=execution.run_id,
            allocation_id=execution.allocation_id,
            phase="inference_running",
            revision=self._revision,
            updated_at=now,
            process_alive=False,
            native_event_count=0,
            canonical_event_count=0,
            latest_event_kind="",
            latest_tool_name="",
            trajectory_bytes=0,
            usage_bytes=0,
            request_count=model.request_count,
            model_requests_in_flight=model.requests_in_flight,
            last_model_method=summary.method if summary else "",
            last_model_protocol=summary.protocol if summary else "",
            last_model_path=summary.path if summary else "",
            last_model_status=summary.status if summary else 0,
            last_model_reason_code=summary.reason_code if summary else "",
            last_model_request_bytes=summary.request_bytes if summary else 0,
            last_model_response_bytes=summary.response_bytes if summary else 0,
            last_model_latency_ms=summary.latency_ms if summary else 0,
            last_model_usage=dict(summary.usage) if summary else {},
            last_agent_activity_at="",
            last_model_activity_at=model.last_activity_at,
            stale_seconds=0,
            state_reason_code="progress_unavailable",
        )
        self._publish(snapshot)

    def _merge(
        self,
        runtime: RuntimeProgress,
        model: ModelProxySnapshot,
        execution: ExecutionRef,
    ) -> ProgressSnapshot:
        assert execution.allocation_id is not None
        now = datetime.now(UTC)
        heartbeat_age = _age_seconds(runtime.updated_at, now)
        agent_age = _age_seconds(runtime.last_agent_activity_at or runtime.updated_at, now)
        stale_limit = max(1, int(self._stale_after_seconds))
        summary = model.last_summary
        if not runtime.process_alive:
            reason = "process_exited"
        elif model.requests_in_flight:
            reason = "model_request_in_flight"
        elif heartbeat_age >= stale_limit:
            reason = "no_agent_heartbeat"
        elif runtime.latest_event_kind in {"tool_call", "tool_result"} and agent_age < stale_limit:
            reason = "tool_activity"
        elif runtime.native_event_count == 0 and model.request_count:
            reason = "waiting_for_model"
        elif agent_age >= stale_limit and model.last_activity_at:
            reason = "model_idle"
        else:
            reason = "agent_active"
        self._revision += 1
        return ProgressSnapshot(
            schema_version=1,
            format=PROGRESS_FORMAT,
            episode_id=self._episode_id,
            run_id=execution.run_id,
            allocation_id=execution.allocation_id,
            phase="inference_running",
            revision=self._revision,
            updated_at=now.isoformat(),
            process_alive=runtime.process_alive,
            native_event_count=runtime.native_event_count,
            canonical_event_count=runtime.canonical_event_count,
            latest_event_kind=runtime.latest_event_kind,
            latest_tool_name=runtime.latest_tool_name,
            trajectory_bytes=runtime.trajectory_bytes,
            usage_bytes=runtime.usage_bytes,
            request_count=model.request_count,
            model_requests_in_flight=model.requests_in_flight,
            last_model_method=summary.method if summary else "",
            last_model_protocol=summary.protocol if summary else "",
            last_model_path=summary.path if summary else "",
            last_model_status=summary.status if summary else 0,
            last_model_reason_code=summary.reason_code if summary else "",
            last_model_request_bytes=summary.request_bytes if summary else 0,
            last_model_response_bytes=summary.response_bytes if summary else 0,
            last_model_latency_ms=summary.latency_ms if summary else 0,
            last_model_usage=dict(summary.usage) if summary else {},
            last_agent_activity_at=runtime.last_agent_activity_at,
            last_model_activity_at=model.last_activity_at,
            stale_seconds=heartbeat_age if reason == "no_agent_heartbeat" else agent_age,
            state_reason_code=reason,
        )

    def _publish(self, snapshot: ProgressSnapshot) -> None:
        path = self._progress_store.save(snapshot)
        with self._store.lock(self._episode_id):
            record = self._store.load(self._episode_id)
            if record is None:
                raise InfrastructureError("progress episode record disappeared")
            if record.phase != EpisodePhase.INFERENCE_RUNNING:
                return
            if record.inference is None or record.inference.run_id != snapshot.run_id:
                raise InfrastructureError("progress Run does not match episode record")
            record.progress_path = str(path)
            record.progress_revision = snapshot.revision
            self._store.save(record)


def _age_seconds(value: str, now: datetime) -> int:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return max(0, int((now - observed).total_seconds()))


def _now() -> str:
    return datetime.now(UTC).isoformat()
