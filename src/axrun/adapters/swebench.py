"""SWE-bench verification in a fresh Axern Allocation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

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
)

_RESULT = "/outputs/verification.json"
_LOG = "/outputs/verifier.log"


@dataclass(frozen=True, slots=True)
class SweBenchVerifierAdapter:
    entrypoint: str = "/opt/axrun/run-swebench-verifier"
    timeout_seconds: int = 7200
    network_policy: str = "deny_all"
    name: str = "swebench"

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan:
        patch = next(
            (
                artifact
                for artifact in candidate.artifacts
                if artifact.name.endswith("candidate.patch")
            ),
            None,
        )
        if patch is None:
            raise ContractError("CandidateBundle does not contain candidate.patch")
        return StagePlan(
            environment_id=episode.verification_environment_id,
            argv=(
                self.entrypoint,
                "--base-commit",
                episode.base_commit,
                "--patch",
                "/inputs/candidate.patch",
                "--result",
                _RESULT,
                "--log",
                _LOG,
            ),
            cwd="/workspace",
            inputs=(InputFile(patch.path, "/inputs/candidate.patch", patch.sha256),),
            outputs=(
                OutputSpec(_RESULT, OutputFormat.FILE, "application/json"),
                OutputSpec(_LOG, OutputFormat.FILE, "text/plain"),
            ),
            network_policy=self.network_policy,
            timeout_seconds=self.timeout_seconds,
            labels={"axrun.stage": "verification", "axrun.verifier": self.name},
        )

    def parse_result(self, result: StageResult) -> VerificationResult:
        artifact = result.artifact_for_path(_RESULT)
        if result.exit_code != 0:
            raise InfrastructureError(
                f"SWE-bench verifier failed with exit code {result.exit_code}: "
                f"{result.diagnostic_code}"
            )
        raw = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
        if not isinstance(raw.get("resolved"), bool):
            raise ContractError("verification result must contain boolean resolved")
        score = raw.get("score", 1.0 if raw["resolved"] else 0.0)
        if not isinstance(score, int | float):
            raise ContractError("verification result score must be numeric")
        return VerificationResult(
            schema_version=1,
            resolved=raw["resolved"],
            score=float(score),
            verifier=self.name,
            details={key: value for key, value in raw.items() if key not in {"resolved", "score"}},
        )
