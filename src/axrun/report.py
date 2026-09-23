"""Portable integrity verification and safe episode acceptance reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axrun.adapters._candidate import load_candidate
from axrun.errors import ContractError
from axrun.models import EpisodePhase
from axrun.progress.store import ProgressStore
from axrun.qualification import load_qualification_result
from axrun.store import EpisodeStore
from axrun.trajectories.bundle import load_trajectory_bundle

REPORT_FORMAT = "axrun.acceptance@1"


def verify_record(store: EpisodeStore, episode_id: str) -> dict[str, Any]:
    record = store.load(episode_id)
    if record is None:
        raise ContractError(f"episode record does not exist: {episode_id}")
    episode = store.load_spec(episode_id)
    candidate = None
    trajectory = None
    result = None
    qualification = None

    if bool(record.qualification_result) != bool(record.qualification_result_digest):
        raise ContractError("qualification evidence record is incomplete")
    if record.qualification_result:
        qualification = load_qualification_result(store, episode)

    if bool(record.candidate_manifest) != bool(record.candidate_digest):
        raise ContractError("CandidateBundle record is incomplete")
    if record.candidate_manifest:
        candidate = load_candidate(Path(record.candidate_manifest))
        if candidate.digest != record.candidate_digest:
            raise ContractError("CandidateBundle record digest mismatch")
        if (
            candidate.episode_id != episode_id
            or candidate.task_id != episode.task_id
            or candidate.seed_digest != episode.seed_digest
            or candidate.candidate != episode.candidate.identity
            or candidate.candidate_version != episode.candidate.version
            or record.inference is None
            or candidate.inference_run_id != record.inference.run_id
        ):
            raise ContractError("CandidateBundle provenance mismatch")

    if bool(record.trajectory_manifest) != bool(record.trajectory_digest):
        raise ContractError("TrajectoryBundle record is incomplete")
    if record.trajectory_manifest:
        trajectory = load_trajectory_bundle(Path(record.trajectory_manifest))
        if trajectory.digest != record.trajectory_digest:
            raise ContractError("TrajectoryBundle record digest mismatch")
        if (
            trajectory.episode_id != episode_id
            or trajectory.task_id != episode.task_id
            or trajectory.seed_digest != episode.seed_digest
            or record.inference is None
            or trajectory.inference_run_id != record.inference.run_id
        ):
            raise ContractError("TrajectoryBundle provenance mismatch")

    if bool(record.verification_result) != bool(record.verification_result_digest):
        raise ContractError("VerificationResult record is incomplete")
    if record.verification_result:
        result = store.load_result(record.verification_result, record.verification_result_digest)
        if candidate is None or result.candidate_digest != candidate.digest:
            raise ContractError("VerificationResult CandidateBundle mismatch")

    if record.inference is not None and (
        record.inference.environment_id != episode.inference_environment.environment_id
    ):
        raise ContractError("inference Environment mismatch")
    if record.verification is not None:
        if record.verification.environment_id != episode.verification_environment.environment_id:
            raise ContractError("verification Environment mismatch")
        if record.inference is not None and record.verification.run_id == record.inference.run_id:
            raise ContractError("verification did not use a fresh Run")

    progress_revision = 0
    if record.progress_path:
        progress_store = ProgressStore(store.root)
        if Path(record.progress_path) != progress_store.path_for(episode_id):
            raise ContractError("episode progress path is not canonical")
        progress = progress_store.load(episode_id)
        if progress is None or progress.revision != record.progress_revision:
            raise ContractError("episode progress record mismatch")
        if record.inference is None or (
            progress.run_id != record.inference.run_id
            or progress.allocation_id != record.inference.allocation_id
        ):
            raise ContractError("episode progress execution mismatch")
        progress_revision = progress.revision

    if record.phase == EpisodePhase.COMPLETED and (
        qualification is None or candidate is None or result is None or record.verification is None
    ):
        raise ContractError("completed episode is missing accepted outputs")

    report: dict[str, Any] = {
        "schema_version": 1,
        "format": REPORT_FORMAT,
        "episode_id": episode_id,
        "phase": record.phase.value,
        "integrity_verified": True,
        "spec_digest": record.spec_digest,
        "seed_digest": episode.seed_digest,
        "task_id": episode.task_id,
        "task": {"identity": episode.task.identity, "version": episode.task.version},
        "harness": {"identity": episode.harness.identity, "version": episode.harness.version},
        "candidate": {
            "identity": episode.candidate.identity,
            "version": episode.candidate.version,
        },
        "verifier": {
            "identity": episode.verifier.identity,
            "version": episode.verifier.version,
        },
        "qualifications": (
            [
                {
                    **_execution(execution),
                    "role": target.role,
                    "environment_image": target.environment_image,
                    "platform": target.platform,
                    "working_directory": target.working_directory,
                    "checks": target.checks,
                }
                for execution, target in zip(
                    record.qualifications, qualification.targets, strict=True
                )
            ]
            if qualification is not None
            else []
        ),
        "qualification_result_digest": record.qualification_result_digest,
        "inference": _execution(record.inference),
        "inference_termination_reason": record.inference_termination_reason,
        "progress_revision": progress_revision,
        "candidate_digest": candidate.digest if candidate is not None else "",
        "trajectory_digest": trajectory.digest if trajectory is not None else "",
        "trajectory_event_count": trajectory.event_count if trajectory is not None else 0,
        "verification": _execution(record.verification),
        "verification_result_digest": record.verification_result_digest,
        "verdict": result.verdict if result is not None else "",
        "score": result.score if result is not None else None,
        "diagnostic_code": result.diagnostic_code if result is not None else record.diagnostic_code,
        "created_at": record.created_at,
        "completed_at": record.completed_at,
    }
    return report


def report_markdown(report: dict[str, Any]) -> str:
    inference = report["inference"]
    verification = report["verification"]
    qualifications = report["qualifications"]
    qualification_lines = (
        [
            "- Inference qualification Run / Allocation: "
            f"`{qualifications[0]['run_id']}` / `{qualifications[0]['allocation_id']}`",
            "- Verification qualification Run / Allocation: "
            f"`{qualifications[1]['run_id']}` / `{qualifications[1]['allocation_id']}`",
        ]
        if len(qualifications) == 2
        else ["- Qualification: `not available`"]
    )
    lines = [
        f"# Axrun acceptance: {report['episode_id']}",
        "",
        f"- Format: `{report['format']}`",
        f"- Phase: `{report['phase']}`",
        f"- Integrity verified: `{str(report['integrity_verified']).lower()}`",
        f"- Task: `{report['task_id']}`",
        f"- Spec digest: `{report['spec_digest']}`",
        f"- Seed digest: `{report['seed_digest']}`",
        *qualification_lines,
        f"- Qualification evidence: `{report['qualification_result_digest']}`",
        f"- Inference Run / Allocation: `{inference['run_id']}` / `{inference['allocation_id']}`",
        f"- Inference termination: `{report['inference_termination_reason']}`",
        f"- Progress revision: `{report['progress_revision']}`",
        f"- CandidateBundle: `{report['candidate_digest']}`",
        f"- TrajectoryBundle: `{report['trajectory_digest']}`",
        "- Verification Run / Allocation: "
        f"`{verification['run_id']}` / `{verification['allocation_id']}`",
        f"- VerificationResult: `{report['verification_result_digest']}`",
        f"- Verdict / score: `{report['verdict']}` / `{report['score']}`",
        f"- Diagnostic code: `{report['diagnostic_code']}`",
        "",
    ]
    return "\n".join(lines)


def canonical_report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, indent=2) + "\n"


def _execution(value: Any | None) -> dict[str, str]:
    if value is None:
        return {"environment_id": "", "run_id": "", "allocation_id": ""}
    return {
        "environment_id": value.environment_id,
        "run_id": value.run_id,
        "allocation_id": value.allocation_id,
    }
