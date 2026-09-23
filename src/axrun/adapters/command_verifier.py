"""Image-owned verifier command executed in a fresh Axern Allocation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from axrun.adapters.base import VerifierQualificationRequirements
from axrun.errors import ContractError, InfrastructureError
from axrun.models import (
    CandidateBundle,
    InputFile,
    OutputFormat,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    StageResult,
    VerificationResult,
    task_config_string,
)

_RESULT = "/outputs/verification.json"
_LOG = "/outputs/verifier.log"


@dataclass(frozen=True, slots=True)
class CommandVerifierAdapter:
    command: tuple[str, ...] = ("/opt/axrun/run-verifier",)
    version: str = "1"
    timeout_seconds: int = 7200
    network_policy: str = "deny_all"
    name: str = "command-verifier"

    def qualification_requirements(
        self, episode: ResolvedEpisode
    ) -> VerifierQualificationRequirements:
        value = episode.verifier.config.get("verifier_file", "")
        if not isinstance(value, str):
            raise ContractError("verifier qualification file must be a string")
        return VerifierQualificationRequirements(verifier_file=value)

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan:
        patch = next(
            (item for item in candidate.files if item.role == "patch"),
            None,
        )
        if patch is None:
            raise ContractError("CandidateBundle does not contain candidate.patch")
        return StagePlan(
            environment_id=episode.verification_environment.environment_id,
            argv=(
                *self.command,
                "--base-commit",
                task_config_string(episode, "base_commit"),
                "--candidate",
                "/inputs/candidate.patch",
                "--result",
                _RESULT,
                "--log",
                _LOG,
            ),
            cwd=episode.verification_environment.working_directory,
            inputs=(
                InputFile(
                    str(Path(candidate.root) / patch.bundle_path),
                    "/inputs/candidate.patch",
                    patch.sha256,
                ),
            ),
            env={"AXRUN_CANDIDATE_DIGEST": candidate.digest},
            outputs=(
                OutputSpec(_RESULT, OutputFormat.FILE, "application/json"),
                OutputSpec(_LOG, OutputFormat.FILE, "text/plain"),
            ),
            resources=episode.verification_resources,
            network_policy=self.network_policy,
            timeout_seconds=self.timeout_seconds,
            labels={"axrun.stage": "verification", "axrun.verifier": self.name},
        )

    def parse_result(self, result: StageResult) -> VerificationResult:
        if result.exit_code != 0:
            raise InfrastructureError(
                f"verifier failed with exit code {result.exit_code}: {result.diagnostic_code}"
            )
        artifact = result.artifact_for_path(_RESULT)
        try:
            raw = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError("verification result is not valid JSON") from exc
        if not isinstance(raw.get("resolved"), bool):
            raise ContractError("verification result must contain boolean resolved")
        score = raw.get("score", 1.0 if raw["resolved"] else 0.0)
        if not isinstance(score, int | float):
            raise ContractError("verification result score must be numeric")
        completed_at = datetime.now(UTC).isoformat()
        contract_fields = {
            "resolved",
            "score",
            "candidate_digest",
            "diagnostic_code",
            "started_at",
            "completed_at",
        }
        return VerificationResult(
            schema_version=1,
            candidate_digest=str(raw.get("candidate_digest", "")),
            verifier=self.name,
            verifier_version=self.version,
            verdict="passed" if raw["resolved"] else "failed",
            diagnostic_code=str(raw.get("diagnostic_code", "")),
            verifier_exit_code=result.exit_code,
            output_digest=artifact.sha256,
            started_at=str(raw.get("started_at", completed_at)),
            completed_at=str(raw.get("completed_at", completed_at)),
            score=float(score),
            details={key: value for key, value in raw.items() if key not in contract_fields},
        )
