from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from axrun import cli
from axrun.adapters._candidate import load_candidate, persist_candidate
from axrun.errors import (
    ContractError,
    DiagnosedInfrastructureError,
    InfrastructureError,
    RecoveryRequiredError,
)
from axrun.models import (
    Artifact,
    EpisodePhase,
    ExecutionRef,
    HarnessSpec,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    StageResult,
    VerificationResult,
    VerifierSpec,
)
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore
from axrun.trajectories.adapters import ClaudeCodeTrajectoryAdapter
from axrun.trajectories.bundle import load_trajectory_bundle


class FakeBackend:
    def __init__(self, *, resolved: bool = True) -> None:
        self.executions: list[ExecutionRef] = []
        self.cancelled: list[str] = []
        self.resolved = resolved
        self.plans: list[StagePlan] = []

    def execute(self, plan, *, artifact_dir, on_bound, lifecycle=None):
        self.plans.append(plan)
        index = len(self.executions) + 1
        ref = ExecutionRef(plan.environment_id, f"run-{index}", f"alloc-{index}")
        self.executions.append(ref)
        on_bound(ref)
        if lifecycle is not None:
            lifecycle.start(ref, object())
            lifecycle.close()
        return self._result(plan, artifact_dir, ref)

    def _result(self, plan, artifact_dir, ref):
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for index, output in enumerate(plan.outputs):
            path = artifact_dir / f"{index}.out"
            payload = (
                json.dumps(
                    {
                        "resolved": self.resolved,
                        "score": 1.0 if self.resolved else 0.0,
                        "candidate_digest": plan.env.get("AXRUN_CANDIDATE_DIGEST", ""),
                    }
                ).encode()
                if output.path.endswith("verification.json")
                else b"candidate"
            )
            path.write_bytes(payload)
            artifacts.append(
                Artifact(
                    output.path,
                    str(path),
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                    output.media_type,
                )
            )
        return StageResult(ref, 0, "", tuple(artifacts))

    def recover(self, execution, plan, *, artifact_dir):
        return self._result(plan, artifact_dir, execution)

    def cancel(self, execution):
        self.cancelled.append(execution.run_id)

    def wait(self, execution, *, timeout=None):
        return None


class BlockingBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.bound = threading.Event()
        self.released = threading.Event()

    def execute(self, plan, *, artifact_dir, on_bound, lifecycle=None):
        ref = ExecutionRef(plan.environment_id, "run-blocked", "alloc-blocked")
        self.executions.append(ref)
        on_bound(ref)
        if lifecycle is not None:
            lifecycle.start(ref, object())
        self.bound.set()
        assert self.released.wait(5)
        return StageResult(ref, 1, "cancelled", ())

    def cancel(self, execution):
        super().cancel(execution)
        self.released.set()


class Inference:
    name = "fake"

    def plan(self, episode):
        return StagePlan(
            episode.inference_environment_id,
            ("agent",),
            "/workspace",
            (OutputSpec("/outputs/candidate.patch"),),
        )

    def build_candidate(self, episode, result, *, destination):
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_paths=("/outputs/candidate.patch",),
            harness=self.name,
            harness_version="1",
        )


class Verifier:
    name = "fake-verifier"

    def plan(self, episode, candidate):
        return StagePlan(
            episode.verification_environment_id,
            ("verify",),
            "/workspace",
            (OutputSpec("/outputs/verification.json", media_type="application/json"),),
            env={"AXRUN_CANDIDATE_DIGEST": candidate.digest},
        )

    def parse_result(self, result):
        raw = json.loads(Path(result.artifacts[0].path).read_text())
        now = datetime.now(UTC).isoformat()
        return VerificationResult(
            1,
            raw["candidate_digest"],
            self.name,
            "1",
            "passed" if raw["resolved"] else "failed",
            "",
            result.exit_code,
            result.artifacts[0].sha256,
            now,
            now,
            float(raw["score"]),
        )


def episode(tmp_path: Path, name: str = "ep") -> ResolvedEpisode:
    prompt = tmp_path / f"{name}.txt"
    prompt.write_text("task", encoding="utf-8")
    return ResolvedEpisode(
        1,
        name,
        "task",
        "b" * 64,
        "a" * 40,
        str(prompt),
        "env-i",
        "env-v",
        HarnessSpec("fake", "1"),
        VerifierSpec("fake-verifier", "1"),
    )


def test_runner_uses_fresh_runs_and_persists_content_addressed_result(tmp_path: Path) -> None:
    backend = FakeBackend()
    store = EpisodeStore(tmp_path / "state")
    runner = EpisodeRunner(backend=backend, store=store)
    result = runner.run(episode(tmp_path), inference=Inference(), verifier=Verifier())
    record = runner.inspect("ep")
    assert result.verdict == "passed" and record.phase == EpisodePhase.COMPLETED
    assert record.inference is not None and record.verification is not None
    assert record.inference.run_id != record.verification.run_id
    assert f"/candidates/sha256/{record.candidate_digest}/" in record.candidate_manifest
    assert f"/sha256/{record.verification_result_digest}/" in record.verification_result
    assert record.trajectory_manifest == "" and record.trajectory_digest == ""
    assert runner.run(episode(tmp_path), inference=Inference(), verifier=Verifier()) == result
    assert len(backend.executions) == 2


def test_runner_persists_separate_trajectory_bundle_and_verifier_only_gets_patch(
    tmp_path: Path,
) -> None:
    class TrajectoryInference(Inference):
        def plan(self, episode):
            return StagePlan(
                episode.inference_environment_id,
                ("agent",),
                "/workspace",
                (
                    OutputSpec("/outputs/candidate.patch"),
                    OutputSpec("/outputs/trajectory.jsonl", media_type="application/x-ndjson"),
                    OutputSpec("/outputs/usage.json", media_type="application/json"),
                ),
            )

    class TrajectoryBackend(FakeBackend):
        def _result(self, plan, artifact_dir, ref):
            if plan.labels.get("axrun.stage") == "verification" or plan.argv == ("verify",):
                return super()._result(plan, artifact_dir, ref)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            payloads = {
                "/outputs/candidate.patch": b"patch",
                "/outputs/trajectory.jsonl": json.dumps(
                    {
                        "schema_version": 1,
                        "sequence": 0,
                        "event_id": "event-00000000",
                        "timestamp": None,
                        "kind": "session_start",
                        "actor": "runtime",
                        "turn_id": None,
                        "parent_event_id": None,
                        "model": "opaque-model",
                        "data": {
                            "harness": "claude-code",
                            "harness_version": "2.1.205",
                            "runtime_version": "2.1.205",
                            "tools": [],
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n",
                "/outputs/usage.json": (
                    b'{"cache_creation_input_tokens":0,"cache_read_input_tokens":0,'
                    b'"input_tokens":0,"observations":0,"output_tokens":0,'
                    b'"schema_version":1}\n'
                ),
            }
            artifacts = []
            for index, output in enumerate(plan.outputs):
                path = artifact_dir / f"{index}.out"
                payload = payloads[output.path]
                path.write_bytes(payload)
                artifacts.append(
                    Artifact(
                        output.path,
                        str(path),
                        len(payload),
                        hashlib.sha256(payload).hexdigest(),
                        output.media_type,
                    )
                )
            return StageResult(ref, 0, "", tuple(artifacts))

    backend = TrajectoryBackend()
    store = EpisodeStore(tmp_path / "state")
    runner = EpisodeRunner(backend=backend, store=store)
    result = runner.run(
        episode(tmp_path, "with-trajectory"),
        inference=TrajectoryInference(),
        verifier=Verifier(),
        trajectory=ClaudeCodeTrajectoryAdapter(),
    )
    assert result.verdict == "passed"
    record = runner.inspect("with-trajectory")
    bundle = load_trajectory_bundle(Path(record.trajectory_manifest))
    assert bundle.digest == record.trajectory_digest and bundle.event_count == 1
    candidate = load_candidate(Path(record.candidate_manifest))
    assert [item.declared_path for item in candidate.files] == ["/outputs/candidate.patch"]
    verification_plan = backend.plans[1]
    assert "trajectory" not in repr(verification_plan)
    assert "usage.json" not in repr(verification_plan)
    exported = cli._export(store, "with-trajectory", tmp_path / "exported")
    assert (exported / "candidate" / "candidate-manifest.json").is_file()
    assert (exported / "trajectory" / "trajectory-manifest.json").is_file()
    export_record = json.loads((exported / "export.json").read_text())
    assert export_record["trajectory_digest"] == bundle.digest


def test_trajectory_contract_failure_is_infrastructure_failure_without_verification(
    tmp_path: Path,
) -> None:
    class RequiredTrajectoryInference(Inference):
        requires_trajectory = True

    class RejectingTrajectoryAdapter:
        def build_bundle(self, episode, result, *, destination):
            raise ContractError("canonical trajectory rejected")

    backend = FakeBackend()
    runner = EpisodeRunner(backend=backend, store=EpisodeStore(tmp_path / "state"))
    with pytest.raises(ContractError, match="canonical trajectory rejected"):
        runner.run(
            episode(tmp_path, "trajectory-contract-failure"),
            inference=RequiredTrajectoryInference(),
            verifier=Verifier(),
            trajectory=RejectingTrajectoryAdapter(),
        )
    record = runner.inspect("trajectory-contract-failure")
    assert record.phase == EpisodePhase.FAILED
    assert record.diagnostic_code == "AXRUN_STAGE_FAILED"
    assert record.candidate_manifest == "" and record.candidate_digest == ""
    assert record.trajectory_manifest == "" and record.trajectory_digest == ""
    assert record.verification is None and record.verification_result == ""
    assert len(backend.executions) == 1


def test_recover_does_not_duplicate_inference_run(tmp_path: Path) -> None:
    value = episode(tmp_path, "recover")
    store = EpisodeStore(tmp_path / "state")
    record = store.initialize(value)
    record.phase = EpisodePhase.INFERENCE_RUNNING
    record.inference = ExecutionRef("env-i", "existing-run", "existing-allocation")
    store.save(record)
    backend = FakeBackend()
    result = EpisodeRunner(backend=backend, store=store).recover(
        "recover", inference=Inference(), verifier=Verifier()
    )
    assert result.verdict == "passed"
    assert len(backend.executions) == 1
    assert backend.executions[0].environment_id == "env-v"


def test_live_model_recovery_requires_operator_decision_for_original_run(
    tmp_path: Path,
) -> None:
    class LiveInference(Inference):
        requires_live_model_connection = True

    class LiveBackend(FakeBackend):
        def recover(self, execution, plan, *, artifact_dir):
            return None

    value = episode(tmp_path, "live-model")
    store = EpisodeStore(tmp_path / "state")
    record = store.initialize(value)
    record.phase = EpisodePhase.INFERENCE_RUNNING
    record.inference = ExecutionRef("env-i", "original-run", "original-allocation")
    store.save(record)
    runner = EpisodeRunner(backend=LiveBackend(), store=store)
    with pytest.raises(RecoveryRequiredError, match="cannot recreate its ephemeral Tunnel"):
        runner.recover("live-model", inference=LiveInference(), verifier=Verifier())
    assert runner.inspect("live-model").inference.run_id == "original-run"


def test_failed_verdict_is_a_completed_business_result(tmp_path: Path) -> None:
    runner = EpisodeRunner(
        backend=FakeBackend(resolved=False), store=EpisodeStore(tmp_path / "state")
    )
    result = runner.run(episode(tmp_path, "unresolved"), inference=Inference(), verifier=Verifier())
    assert result.verdict == "failed" and result.score == 0.0
    assert runner.inspect("unresolved").phase == EpisodePhase.COMPLETED


def test_verification_transport_failure_recovers_same_run(tmp_path: Path) -> None:
    class PartitionOnceBackend(FakeBackend):
        def execute(self, plan, *, artifact_dir, on_bound, lifecycle=None):
            if len(self.executions) == 1:
                ref = ExecutionRef(plan.environment_id, "run-verification", "alloc-verification")
                self.executions.append(ref)
                on_bound(ref)
                raise ConnectionError("partition")
            return super().execute(
                plan, artifact_dir=artifact_dir, on_bound=on_bound, lifecycle=lifecycle
            )

    backend = PartitionOnceBackend()
    runner = EpisodeRunner(backend=backend, store=EpisodeStore(tmp_path / "state"))
    with pytest.raises(ConnectionError, match="partition"):
        runner.run(episode(tmp_path, "partition"), inference=Inference(), verifier=Verifier())
    before = runner.inspect("partition")
    assert before.phase == EpisodePhase.VERIFICATION_RUNNING
    assert before.verification is not None and before.verification.run_id == "run-verification"
    result = runner.recover("partition", inference=Inference(), verifier=Verifier())
    assert result.verdict == "passed"
    assert [value.run_id for value in backend.executions] == ["run-1", "run-verification"]


def test_cancel_is_not_blocked_by_remote_execution(tmp_path: Path) -> None:
    backend = BlockingBackend()
    runner = EpisodeRunner(backend=backend, store=EpisodeStore(tmp_path / "state"))
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            runner.run(episode(tmp_path, "cancel"), inference=Inference(), verifier=Verifier())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    assert backend.bound.wait(5)
    cancelled = runner.cancel("cancel")
    thread.join(5)
    assert not thread.is_alive()
    assert cancelled.phase == EpisodePhase.CANCELLED
    assert backend.cancelled == ["run-blocked"]
    assert errors and runner.inspect("cancel").phase == EpisodePhase.CANCELLED


def test_terminal_inference_failure_is_not_recoverable(tmp_path: Path) -> None:
    class FailedBackend(FakeBackend):
        def _result(self, plan, artifact_dir, ref):
            return StageResult(ref, 17, "AGENT_FAILED", ())

    runner = EpisodeRunner(backend=FailedBackend(), store=EpisodeStore(tmp_path / "state"))
    with pytest.raises(InfrastructureError, match="inference Run failed"):
        runner.run(episode(tmp_path, "failed"), inference=Inference(), verifier=Verifier())
    assert runner.inspect("failed").phase == EpisodePhase.FAILED


def test_terminal_model_failure_persists_only_safe_proxy_diagnosis(tmp_path: Path) -> None:
    class FailedBackend(FakeBackend):
        def _result(self, plan, artifact_dir, ref):
            return StageResult(
                ref,
                1,
                "",
                (),
                diagnostic_details={
                    "method": "POST",
                    "protocol": "anthropic",
                    "path": "/v1/messages?beta=true",
                    "status": 429,
                    "request_bytes": 100,
                    "response_bytes": 20,
                    "latency_ms": 15,
                    "model": "opaque-model",
                    "usage": {},
                    "reason_code": "upstream_response",
                },
            )

    runner = EpisodeRunner(backend=FailedBackend(), store=EpisodeStore(tmp_path / "state"))
    with pytest.raises(InfrastructureError, match="inference Run failed"):
        runner.run(episode(tmp_path, "model-failed"), inference=Inference(), verifier=Verifier())
    record = runner.inspect("model-failed")
    assert record.phase == EpisodePhase.FAILED
    assert record.diagnostic_code == "upstream_response"
    assert json.loads(record.message) == {
        "method": "POST",
        "protocol": "anthropic",
        "path": "/v1/messages?beta=true",
        "status": 429,
        "request_bytes": 100,
        "response_bytes": 20,
        "latency_ms": 15,
        "model": "opaque-model",
        "usage": {},
        "reason_code": "upstream_response",
    }


def test_prestart_model_failure_persists_stable_diagnosis_without_secret(
    tmp_path: Path,
) -> None:
    class FailedBackend(FakeBackend):
        def execute(self, plan, *, artifact_dir, on_bound, lifecycle=None):
            on_bound(ExecutionRef(plan.environment_id, "run-safe", "alloc-safe"))
            raise DiagnosedInfrastructureError(
                "tunnel_model_preflight_failed",
                {
                    "protocol": "anthropic",
                    "status": 401,
                    "reason_code": "upstream_response",
                    "credential": "must-not-persist",
                    "tunnel_token": "must-not-persist",
                    "response_body": "must-not-persist",
                },
            )

    runner = EpisodeRunner(backend=FailedBackend(), store=EpisodeStore(tmp_path / "state"))
    with pytest.raises(DiagnosedInfrastructureError):
        runner.run(
            episode(tmp_path, "preflight-failed"), inference=Inference(), verifier=Verifier()
        )
    record = runner.inspect("preflight-failed")
    assert record.diagnostic_code == "tunnel_model_preflight_failed"
    assert json.loads(record.message) == {
        "protocol": "anthropic",
        "status": 401,
        "reason_code": "upstream_response",
    }
    assert "credential" not in record.message and "token" not in record.message


def test_progress_observer_failure_is_terminal_infrastructure_not_verdict(
    tmp_path: Path,
) -> None:
    class BrokenObserver:
        def start(self, execution, allocation) -> None:
            return None

        def close(self) -> None:
            raise DiagnosedInfrastructureError(
                "progress_observer_failed", {"reason_code": "invalid_progress_contract"}
            )

    backend = FakeBackend()
    runner = EpisodeRunner(backend=backend, store=EpisodeStore(tmp_path / "state"))
    with pytest.raises(DiagnosedInfrastructureError):
        runner.run(
            episode(tmp_path, "observer-failed"),
            inference=Inference(),
            verifier=Verifier(),
            inference_lifecycle=BrokenObserver(),
        )
    record = runner.inspect("observer-failed")
    assert record.phase == EpisodePhase.FAILED
    assert record.diagnostic_code == "progress_observer_failed"
    assert record.verification is None and record.verification_result == ""


def test_terminal_success_with_missing_declared_output_fails_contract(tmp_path: Path) -> None:
    class MissingOutputBackend(FakeBackend):
        def _result(self, plan, artifact_dir, ref):
            return StageResult(ref, 0, "", ())

    runner = EpisodeRunner(backend=MissingOutputBackend(), store=EpisodeStore(tmp_path / "state"))
    with pytest.raises(ContractError, match="required sealed output is missing"):
        runner.run(episode(tmp_path, "missing"), inference=Inference(), verifier=Verifier())
    assert runner.inspect("missing").phase == EpisodePhase.FAILED
