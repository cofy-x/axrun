"""Semantic identity checks shared by recovery and independent record verification."""

from __future__ import annotations

from axrun.errors import ContractError
from axrun.models import CandidateBundle, ExecutionRef, ResolvedEpisode, VerificationResult


def validate_candidate_provenance(
    candidate: CandidateBundle,
    episode: ResolvedEpisode,
    inference: ExecutionRef | None,
) -> None:
    if (
        candidate.episode_id != episode.episode_id
        or candidate.task_id != episode.task_id
        or candidate.seed_digest != episode.seed_digest
        or (candidate.harness, candidate.harness_version)
        != (episode.harness.identity, episode.harness.version)
        or (candidate.candidate, candidate.candidate_version)
        != (episode.candidate.identity, episode.candidate.version)
        or inference is None
        or candidate.inference_run_id != inference.run_id
        or inference.environment_id != episode.inference_environment.environment_id
    ):
        raise ContractError("CandidateBundle provenance mismatch")


def validate_result_provenance(
    result: VerificationResult,
    episode: ResolvedEpisode,
    candidate: CandidateBundle,
) -> None:
    if result.candidate_digest != candidate.digest:
        raise ContractError("VerificationResult CandidateBundle mismatch")
    if (result.verifier, result.verifier_version) != (
        episode.verifier.identity,
        episode.verifier.version,
    ):
        raise ContractError("VerificationResult verifier identity mismatch")
