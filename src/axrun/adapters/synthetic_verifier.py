"""No-network verifier for the repository-owned synthetic code task."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from axrun.adapters.command_verifier import CommandVerifierAdapter
from axrun.errors import ContractError
from axrun.models import (
    CandidateBundle,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    task_config_string,
)

_RESULT = "/outputs/verification.json"
_LOG = "/outputs/verifier.log"


@dataclass(frozen=True, slots=True)
class SyntheticVerifierAdapter(CommandVerifierAdapter):
    version: str = "1"
    name: str = "synthetic-code-task"

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan:
        if episode.verifier.identity != self.name:
            raise ContractError("synthetic verifier requires a matching verifier")
        patch = next(
            (item for item in candidate.files if item.role == "patch"),
            None,
        )
        if patch is None:
            raise ContractError("CandidateBundle does not contain candidate.patch")
        config = episode.verifier.config
        verifier_file = config.get("verifier_file")
        if not isinstance(verifier_file, str):
            raise ContractError("synthetic verifier config is incomplete")
        inputs = [
            InputFile(
                str(Path(candidate.root) / patch.bundle_path),
                "/inputs/candidate.patch",
                patch.sha256,
            ),
            InputFile(verifier_file, "/opt/axrun-synthetic/run_verifier.py"),
        ]
        return StagePlan(
            environment_id=episode.verification_environment.environment_id,
            argv=(
                "python3",
                "/opt/axrun-synthetic/run_verifier.py",
                "--workspace",
                "/workspace",
                "--base-commit",
                task_config_string(episode, "base_commit"),
                "--candidate",
                "/inputs/candidate.patch",
                "--candidate-digest",
                candidate.digest,
                "--result",
                _RESULT,
                "--log",
                _LOG,
            ),
            cwd=episode.verification_environment.working_directory,
            inputs=tuple(inputs),
            outputs=(
                OutputSpec(_RESULT, media_type="application/json"),
                OutputSpec(_LOG, media_type="text/plain"),
            ),
            resources=episode.verification_resources,
            network_policy="deny_all",
            timeout_seconds=episode.verifier.timeout_seconds,
            labels={"axrun.stage": "verification", "axrun.verifier": self.name},
        )
