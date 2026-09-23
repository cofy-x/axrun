"""Fresh, offline verifier for the repository-owned greenfield archive fixture."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from axrun.adapters.command_verifier import CommandVerifierAdapter
from axrun.errors import ContractError
from axrun.models import CandidateBundle, InputFile, OutputSpec, ResolvedEpisode, StagePlan

_RESULT = "/outputs/verification.json"
_LOG = "/outputs/verifier.log"


@dataclass(frozen=True, slots=True)
class GreenfieldVerifierAdapter(CommandVerifierAdapter):
    version: str = "1"
    name: str = "synthetic-greenfield"

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan:
        if (episode.verifier.identity, episode.verifier.version) != (self.name, self.version):
            raise ContractError("greenfield verifier requires synthetic-greenfield@1")
        workspace = next((item for item in candidate.files if item.role == "workspace"), None)
        if workspace is None:
            raise ContractError("CandidateBundle does not contain workspace role")
        verifier_file = episode.verifier.config.get("verifier_file")
        if not isinstance(verifier_file, str) or not Path(verifier_file).is_file():
            raise ContractError("greenfield verifier_file is missing")
        package_root = Path(__file__).parents[1]
        archive_module = package_root / "candidates" / "archive.py"
        errors_module = package_root / "errors.py"
        init_module = package_root / "fixtures" / "claude" / "runtime_package_init.py"
        verification_root = shlex.quote(episode.verification_environment.working_directory)
        script = "\n".join(
            (
                "set -eu",
                f'test -z "$(find {verification_root} -mindepth 1 -maxdepth 1 -print -quit)"',
                "PYTHONPATH=/opt/axrun python3 /opt/axrun/axrun/candidates/archive.py "
                f"extract /inputs/workspace.tar {verification_root}",
                "python3 /opt/axrun-greenfield/run_verifier.py "
                f"--workspace {verification_root} "
                f"--candidate-digest {candidate.digest} "
                f"--result {_RESULT} --log {_LOG}",
            )
        )
        return StagePlan(
            environment_id=episode.verification_environment.environment_id,
            argv=("/bin/sh", "-lc", script),
            cwd=verification_root,
            inputs=(
                InputFile(
                    str(Path(candidate.root) / workspace.bundle_path),
                    "/inputs/workspace.tar",
                    workspace.sha256,
                ),
                InputFile(str(init_module), "/opt/axrun/axrun/__init__.py"),
                InputFile(str(init_module), "/opt/axrun/axrun/candidates/__init__.py"),
                InputFile(str(errors_module), "/opt/axrun/axrun/errors.py"),
                InputFile(str(archive_module), "/opt/axrun/axrun/candidates/archive.py"),
                InputFile(verifier_file, "/opt/axrun-greenfield/run_verifier.py"),
            ),
            outputs=(
                OutputSpec(_RESULT, media_type="application/json"),
                OutputSpec(_LOG, media_type="text/plain"),
            ),
            resources=episode.verification_resources,
            network_policy="deny_all",
            timeout_seconds=episode.verifier.timeout_seconds,
            labels={"axrun.stage": "verification", "axrun.verifier": self.name},
        )
