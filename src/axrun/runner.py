"""Recoverable two-stage episode runner."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from axrun.adapters.base import InferenceAdapter, VerifierAdapter
from axrun.backend import ExecutionBackend
from axrun.errors import RecoveryRequiredError
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
    def __init__(self, *, backend: ExecutionBackend, store: EpisodeStore) -> None:
        self.backend = backend
        self.store = store

    def run(
        self,
        episode: ResolvedEpisode,
        *,
        inference: InferenceAdapter,
        verifier: VerifierAdapter,
    ) -> VerificationResult:
        record = self.store.load(episode.episode_id) or EpisodeRecord(
            schema_version=1, episode=episode
        )
        if record.episode != episode:
            raise RecoveryRequiredError("persisted episode differs from the requested episode")
        if record.phase == EpisodePhase.COMPLETED:
            return self._load_verification(record)
        if record.phase in {EpisodePhase.INFERENCE_RUNNING, EpisodePhase.VERIFICATION_RUNNING}:
            raise RecoveryRequiredError(
                f"episode has an in-flight {record.phase.value} stage; call recover explicitly"
            )
        if record.phase == EpisodePhase.FAILED:
            raise RecoveryRequiredError("failed episodes are not silently rerun")

        try:
            candidate = self._ensure_candidate(record, inference)
            return self._verify(record, candidate, verifier)
        except Exception as exc:
            recoverable_inference = (
                record.phase == EpisodePhase.INFERENCE_RUNNING and record.inference is not None
            )
            recoverable_verification = (
                record.phase == EpisodePhase.VERIFICATION_RUNNING
                and record.verification is not None
            )
            if not recoverable_inference and not recoverable_verification:
                record.phase = EpisodePhase.FAILED
            record.error = f"{type(exc).__name__}: {exc}"
            self.store.save(record)
            raise

    def recover(
        self,
        episode_id: str,
        *,
        inference: InferenceAdapter,
        verifier: VerifierAdapter,
    ) -> VerificationResult:
        record = self.store.load(episode_id)
        if record is None:
            raise RecoveryRequiredError(f"episode record does not exist: {episode_id}")
        if record.phase == EpisodePhase.COMPLETED:
            return self._load_verification(record)
        if record.phase == EpisodePhase.INFERENCE_RUNNING:
            if record.inference is None:
                raise RecoveryRequiredError("inference Run identity was not persisted")
            plan = inference.plan(record.episode)
            destination = self.store.root / "artifacts" / episode_id / "inference"
            stage = self.backend.recover(record.inference, plan, artifact_dir=destination)
            if stage is None:
                raise RecoveryRequiredError("inference Run is still active")
            candidate_dir = self.store.root / "candidates" / episode_id
            candidate = inference.build_candidate(record.episode, stage, destination=candidate_dir)
            record.candidate_manifest = str(candidate_dir / "candidate-manifest.json")
            record.phase = EpisodePhase.CANDIDATE_READY
            record.error = ""
            self.store.save(record)
            return self._verify(record, candidate, verifier)
        if record.phase == EpisodePhase.VERIFICATION_RUNNING:
            if record.verification is None:
                raise RecoveryRequiredError("verification Run identity was not persisted")
            candidate = self._load_candidate(record)
            plan = verifier.plan(record.episode, candidate)
            destination = self.store.root / "artifacts" / episode_id / "verification"
            stage = self.backend.recover(record.verification, plan, artifact_dir=destination)
            if stage is None:
                raise RecoveryRequiredError("verification Run is still active")
            return self._finish_verification(record, stage, verifier)
        raise RecoveryRequiredError(
            f"episode phase {record.phase.value} cannot be recovered automatically"
        )

    def _ensure_candidate(
        self, record: EpisodeRecord, adapter: InferenceAdapter
    ) -> CandidateBundle:
        episode = record.episode
        if record.phase == EpisodePhase.CANDIDATE_READY:
            return self._load_candidate(record)
        plan = adapter.plan(episode)
        record.phase = EpisodePhase.INFERENCE_RUNNING
        self.store.save(record)

        def bound(execution: ExecutionRef) -> None:
            record.inference = execution
            self.store.save(record)

        destination = self.store.root / "artifacts" / episode.episode_id / "inference"
        result = self.backend.execute(plan, artifact_dir=destination, on_bound=bound)
        candidate_dir = self.store.root / "candidates" / episode.episode_id
        candidate = adapter.build_candidate(episode, result, destination=candidate_dir)
        record.candidate_manifest = str(candidate_dir / "candidate-manifest.json")
        record.phase = EpisodePhase.CANDIDATE_READY
        self.store.save(record)
        return candidate

    def _verify(
        self,
        record: EpisodeRecord,
        candidate: CandidateBundle,
        adapter: VerifierAdapter,
    ) -> VerificationResult:
        plan = adapter.plan(record.episode, candidate)
        record.phase = EpisodePhase.VERIFICATION_RUNNING
        self.store.save(record)

        def bound(execution: ExecutionRef) -> None:
            record.verification = execution
            self.store.save(record)

        destination = self.store.root / "artifacts" / record.episode.episode_id / "verification"
        stage = self.backend.execute(plan, artifact_dir=destination, on_bound=bound)
        return self._finish_verification(record, stage, adapter)

    def _finish_verification(
        self,
        record: EpisodeRecord,
        stage: StageResult,
        adapter: VerifierAdapter,
    ) -> VerificationResult:
        verification = adapter.parse_result(stage)
        result_path = self.store.root / "results" / f"{record.episode.episode_id}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(asdict(verification), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record.verification_result = str(result_path)
        record.phase = EpisodePhase.COMPLETED
        self.store.save(record)
        return verification

    @staticmethod
    def _load_candidate(record: EpisodeRecord) -> CandidateBundle:
        raw = json.loads(Path(record.candidate_manifest).read_text(encoding="utf-8"))
        from axrun.models import Artifact

        return CandidateBundle(
            schema_version=raw["schema_version"],
            episode_id=raw["episode_id"],
            task_id=raw["task_id"],
            task_digest=raw["task_digest"],
            base_commit=raw["base_commit"],
            inference=ExecutionRef(**raw["inference"]),
            artifacts=tuple(Artifact(**value) for value in raw["artifacts"]),
        )

    @staticmethod
    def _load_verification(record: EpisodeRecord) -> VerificationResult:
        raw = json.loads(Path(record.verification_result).read_text(encoding="utf-8"))
        return VerificationResult(**raw)
