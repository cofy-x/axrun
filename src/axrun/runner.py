"""Recoverable two-stage episode runner."""

from __future__ import annotations

from pathlib import Path

from axrun.adapters._candidate import load_candidate
from axrun.adapters.base import InferenceAdapter, VerifierAdapter
from axrun.backend import ExecutionBackend
from axrun.errors import ContractError, InfrastructureError, RecoveryRequiredError
from axrun.lifecycle.base import PreStartLifecycle
from axrun.models import (
    CandidateBundle,
    EpisodePhase,
    EpisodeRecord,
    ExecutionRef,
    ResolvedEpisode,
    StageResult,
    VerificationResult,
)
from axrun.store import EpisodeStore


class EpisodeRunner:
    """Own caller-local orchestration; Axern remains execution fact source."""

    def __init__(self, *, backend: ExecutionBackend, store: EpisodeStore) -> None:
        self.backend = backend
        self.store = store

    def run(
        self,
        episode: ResolvedEpisode,
        *,
        inference: InferenceAdapter,
        verifier: VerifierAdapter,
        inference_lifecycle: PreStartLifecycle | None = None,
    ) -> VerificationResult:
        with self.store.lock(episode.episode_id):
            record = self.store.initialize(episode)
            if record.phase == EpisodePhase.COMPLETED:
                return self._load_verification(record)
            if record.phase != EpisodePhase.NEW:
                raise RecoveryRequiredError(
                    f"episode is {record.phase.value}; use wait or inspect it"
                )
            record.phase = EpisodePhase.INFERENCE_RUNNING
            self.store.save(record)
        try:
            plan = inference.plan(episode)
            destination = self.store.root / "artifacts" / episode.episode_id / "inference"
            stage = self.backend.execute(
                plan,
                artifact_dir=destination,
                on_bound=lambda execution: self._bind(
                    episode.episode_id, EpisodePhase.INFERENCE_RUNNING, execution
                ),
                lifecycle=inference_lifecycle,
            )
            candidate = self._commit_candidate(episode, inference, stage)
            return self._start_verification(episode, candidate, verifier)
        except Exception as exc:
            self._record_failure(episode.episode_id, exc)
            raise

    def recover(
        self, episode_id: str, *, inference: InferenceAdapter, verifier: VerifierAdapter
    ) -> VerificationResult:
        with self.store.lock(episode_id):
            record = self._required_record(episode_id)
            episode = self.store.load_spec(episode_id)
            phase = record.phase
            execution = (
                record.inference if phase == EpisodePhase.INFERENCE_RUNNING else record.verification
            )
        if phase == EpisodePhase.COMPLETED:
            return self._load_verification(record)
        if phase == EpisodePhase.CANDIDATE_READY:
            try:
                candidate = self._load_candidate(record)
            except ContractError as exc:
                self._record_failure(episode_id, exc)
                raise
            return self._start_verification(episode, candidate, verifier)
        if phase not in {EpisodePhase.INFERENCE_RUNNING, EpisodePhase.VERIFICATION_RUNNING}:
            raise RecoveryRequiredError(f"episode phase {phase.value} cannot be recovered")
        if execution is None:
            raise RecoveryRequiredError(f"{phase.value} Run identity was not persisted")
        if phase == EpisodePhase.INFERENCE_RUNNING:
            plan = inference.plan(episode)
            destination = self.store.root / "artifacts" / episode_id / "inference"
        else:
            try:
                candidate = self._load_candidate(record)
            except ContractError as exc:
                self._record_failure(episode_id, exc)
                raise
            plan = verifier.plan(episode, candidate)
            destination = self.store.root / "artifacts" / episode_id / "verification"
        stage = self.backend.recover(execution, plan, artifact_dir=destination)
        if stage is None:
            if phase == EpisodePhase.INFERENCE_RUNNING and bool(
                getattr(inference, "requires_live_model_connection", False)
            ):
                raise RecoveryRequiredError(
                    "live model inference cannot recreate its ephemeral Tunnel; "
                    "inspect or cancel the persisted Run"
                )
            raise RecoveryRequiredError(f"{phase.value} Run is still active")
        if phase == EpisodePhase.INFERENCE_RUNNING:
            candidate = self._commit_candidate(episode, inference, stage)
            return self._start_verification(episode, candidate, verifier)
        return self._finish_verification(episode_id, stage, verifier)

    def wait(
        self,
        episode_id: str,
        *,
        inference: InferenceAdapter,
        verifier: VerifierAdapter,
        timeout: float | None = None,
    ) -> VerificationResult:
        record = self._required_record(episode_id)
        execution = (
            record.inference
            if record.phase == EpisodePhase.INFERENCE_RUNNING
            else record.verification
            if record.phase == EpisodePhase.VERIFICATION_RUNNING
            else None
        )
        if execution is not None:
            self.backend.wait(execution, timeout=timeout)
        return self.recover(episode_id, inference=inference, verifier=verifier)

    def cancel(self, episode_id: str) -> EpisodeRecord:
        with self.store.lock(episode_id):
            record = self._required_record(episode_id)
            if record.phase in {
                EpisodePhase.COMPLETED,
                EpisodePhase.FAILED,
                EpisodePhase.CANCELLED,
            }:
                return record
            execution = (
                record.verification
                if record.phase == EpisodePhase.VERIFICATION_RUNNING
                else record.inference
                if record.phase == EpisodePhase.INFERENCE_RUNNING
                else None
            )
            # Serialize the accepted cancellation with terminal publication. The
            # lock covers only the bounded control RPC, never the Run lifetime.
            if execution is not None:
                self.backend.cancel(execution)
            record.phase = EpisodePhase.CANCELLED
            record.diagnostic_code = "AXRUN_CANCELLED"
            record.completed_at = _now()
            self.store.save(record)
            return record

    def inspect(self, episode_id: str) -> EpisodeRecord:
        return self._required_record(episode_id)

    def _bind(self, episode_id: str, expected_phase: EpisodePhase, execution: ExecutionRef) -> None:
        cancel = False
        with self.store.lock(episode_id):
            record = self._required_record(episode_id)
            if record.phase != expected_phase:
                cancel = record.phase == EpisodePhase.CANCELLED
            elif expected_phase == EpisodePhase.INFERENCE_RUNNING:
                record.inference = _merge_execution(record.inference, execution)
                self.store.save(record)
                return
            else:
                if record.inference is not None and execution.run_id == record.inference.run_id:
                    raise InfrastructureError("verification must use a fresh Axern Run")
                record.verification = _merge_execution(record.verification, execution)
                self.store.save(record)
                return
        if cancel:
            self.backend.cancel(execution)
        raise RecoveryRequiredError(f"episode no longer accepts {expected_phase.value} binding")

    def _commit_candidate(
        self, episode: ResolvedEpisode, adapter: InferenceAdapter, result: StageResult
    ) -> CandidateBundle:
        if result.exit_code != 0:
            with self.store.lock(episode.episode_id):
                record = self._required_record(episode.episode_id)
                self._require_execution(record, EpisodePhase.INFERENCE_RUNNING, result.execution)
                record.inference = result.execution
                record.phase = EpisodePhase.FAILED
                record.diagnostic_code = result.diagnostic_code or "AXRUN_INFERENCE_FAILED"
                record.message = f"inference Run exited with code {result.exit_code}"
                record.completed_at = _now()
                self.store.save(record)
            raise InfrastructureError(
                f"inference Run failed: exit={result.exit_code} diagnostic={result.diagnostic_code}"
            )
        candidate_dir = self.store.root / "candidates"
        candidate = adapter.build_candidate(episode, result, destination=candidate_dir)
        with self.store.lock(episode.episode_id):
            record = self._required_record(episode.episode_id)
            self._require_execution(record, EpisodePhase.INFERENCE_RUNNING, result.execution)
            record.inference = result.execution
            record.candidate_manifest = str(Path(candidate.root) / "candidate-manifest.json")
            record.candidate_digest = candidate.digest
            record.phase = EpisodePhase.CANDIDATE_READY
            record.diagnostic_code = ""
            record.message = ""
            self.store.save(record)
        return candidate

    def _start_verification(
        self, episode: ResolvedEpisode, candidate: CandidateBundle, adapter: VerifierAdapter
    ) -> VerificationResult:
        plan = adapter.plan(episode, candidate)
        with self.store.lock(episode.episode_id):
            record = self._required_record(episode.episode_id)
            if record.phase != EpisodePhase.CANDIDATE_READY:
                raise RecoveryRequiredError(f"cannot start verification from {record.phase.value}")
            record.phase = EpisodePhase.VERIFICATION_RUNNING
            self.store.save(record)
        try:
            destination = self.store.root / "artifacts" / episode.episode_id / "verification"
            stage = self.backend.execute(
                plan,
                artifact_dir=destination,
                on_bound=lambda execution: self._bind(
                    episode.episode_id, EpisodePhase.VERIFICATION_RUNNING, execution
                ),
                lifecycle=None,
            )
            return self._finish_verification(episode.episode_id, stage, adapter)
        except Exception as exc:
            self._record_failure(episode.episode_id, exc)
            raise

    def _finish_verification(
        self, episode_id: str, stage: StageResult, adapter: VerifierAdapter
    ) -> VerificationResult:
        try:
            verification = adapter.parse_result(stage)
        except Exception as exc:
            with self.store.lock(episode_id):
                record = self._required_record(episode_id)
                self._require_execution(record, EpisodePhase.VERIFICATION_RUNNING, stage.execution)
                record.verification = stage.execution
                record.phase = EpisodePhase.FAILED
                record.diagnostic_code = stage.diagnostic_code or "AXRUN_VERIFICATION_FAILED"
                record.message = f"{type(exc).__name__}: {exc}"
                record.completed_at = _now()
                self.store.save(record)
            raise
        with self.store.lock(episode_id):
            record = self._required_record(episode_id)
            self._require_execution(record, EpisodePhase.VERIFICATION_RUNNING, stage.execution)
            if verification.candidate_digest != record.candidate_digest:
                record.verification = stage.execution
                record.phase = EpisodePhase.FAILED
                record.diagnostic_code = "AXRUN_CANDIDATE_MISMATCH"
                record.message = "VerificationResult references the wrong CandidateBundle"
                record.completed_at = _now()
                self.store.save(record)
                raise ContractError("VerificationResult references the wrong CandidateBundle")
            result_path, result_digest = self.store.save_result(verification)
            record.verification = stage.execution
            record.verification_result = str(result_path)
            record.verification_result_digest = result_digest
            record.phase = EpisodePhase.COMPLETED
            record.diagnostic_code = verification.diagnostic_code
            record.message = ""
            record.completed_at = verification.completed_at
            self.store.save(record)
        return verification

    def _record_failure(self, episode_id: str, exc: Exception) -> None:
        with self.store.lock(episode_id):
            record = self._required_record(episode_id)
            if record.phase in {
                EpisodePhase.CANCELLED,
                EpisodePhase.COMPLETED,
                EpisodePhase.FAILED,
            }:
                return
            if isinstance(exc, ContractError) or not self._has_recoverable_identity(record):
                record.phase = EpisodePhase.FAILED
                record.diagnostic_code = "AXRUN_STAGE_FAILED"
            record.message = f"{type(exc).__name__}: {exc}"
            self.store.save(record)

    @staticmethod
    def _require_execution(
        record: EpisodeRecord, phase: EpisodePhase, execution: ExecutionRef
    ) -> None:
        if record.phase != phase:
            raise RecoveryRequiredError(f"episode moved to {record.phase.value}")
        persisted = (
            record.inference if phase == EpisodePhase.INFERENCE_RUNNING else record.verification
        )
        if persisted is not None and persisted.run_id != execution.run_id:
            raise InfrastructureError("stage result does not match the persisted Axern Run")

    def _load_candidate(self, record: EpisodeRecord) -> CandidateBundle:
        candidate = load_candidate(Path(record.candidate_manifest))
        if candidate.digest != record.candidate_digest:
            raise InfrastructureError("CandidateBundle record digest mismatch")
        return candidate

    def _load_verification(self, record: EpisodeRecord) -> VerificationResult:
        return self.store.load_result(record.verification_result, record.verification_result_digest)

    def _required_record(self, episode_id: str) -> EpisodeRecord:
        record = self.store.load(episode_id)
        if record is None:
            raise RecoveryRequiredError(f"episode record does not exist: {episode_id}")
        return record

    @staticmethod
    def _has_recoverable_identity(record: EpisodeRecord) -> bool:
        return (
            record.phase == EpisodePhase.INFERENCE_RUNNING and record.inference is not None
        ) or (record.phase == EpisodePhase.VERIFICATION_RUNNING and record.verification is not None)


def _merge_execution(current: ExecutionRef | None, update: ExecutionRef) -> ExecutionRef:
    if current is not None and current.run_id != update.run_id:
        raise InfrastructureError("Axern Run identity changed during stage execution")
    return update


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
