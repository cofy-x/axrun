"""Fresh, offline verifier adapter for one SWE-bench Verified vertical."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

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
class SweBenchVerifiedVerifierAdapter(CommandVerifierAdapter):
    version: str = "1"
    name: str = "swebench-verified"

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan:
        if episode.verifier.identity != self.name or episode.verifier.version != self.version:
            raise ContractError("SWE-bench Verified adapter requires swebench-verified@1")
        patch = next(
            (item for item in candidate.files if item.role == "patch"),
            None,
        )
        if patch is None:
            raise ContractError("CandidateBundle does not contain candidate.patch")
        config = episode.verifier.config
        verifier_file = _required_file(config, "verifier_file")
        eval_script = _required_file(config, "eval_script_file")
        log_parser = config.get("log_parser")
        if log_parser != "parse_log_django":
            raise ContractError("minimal SWE-bench Verified vertical supports parse_log_django")
        fail_to_pass = _string_array(config, "fail_to_pass", require_nonempty=True)
        pass_to_pass = _string_array(config, "pass_to_pass", require_nonempty=False)
        return StagePlan(
            environment_id=episode.verification_environment.environment_id,
            argv=(
                "python3",
                "/opt/axrun-swebench/run_verifier.py",
                "--workspace",
                "/testbed",
                "--base-commit",
                task_config_string(episode, "base_commit"),
                "--candidate",
                "/inputs/candidate.patch",
                "--candidate-digest",
                candidate.digest,
                "--eval-script",
                "/opt/axrun-swebench/eval.sh",
                "--log-parser",
                log_parser,
                "--fail-to-pass",
                json.dumps(fail_to_pass, separators=(",", ":")),
                "--pass-to-pass",
                json.dumps(pass_to_pass, separators=(",", ":")),
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
                InputFile(verifier_file, "/opt/axrun-swebench/run_verifier.py"),
                InputFile(eval_script, "/opt/axrun-swebench/eval.sh"),
            ),
            outputs=(
                OutputSpec(_RESULT, media_type="application/json"),
                OutputSpec(_LOG, media_type="text/plain", max_bytes=64 << 20),
            ),
            resources=episode.verification_resources,
            network_policy="deny_all",
            timeout_seconds=episode.verifier.timeout_seconds,
            labels={"axrun.stage": "verification", "axrun.verifier": self.name},
        )


def _required_file(config: dict[str, object], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not Path(value).is_file():
        raise ContractError(f"SWE-bench Verified {key} is missing")
    return value


def _string_array(config: dict[str, object], key: str, *, require_nonempty: bool) -> list[str]:
    value = config.get(key)
    if not isinstance(value, list) or (require_nonempty and not value):
        raise ContractError(f"SWE-bench Verified {key} must be a string array")
    items = cast(list[object], value)
    if any(not isinstance(item, str) or not item for item in items):
        raise ContractError(f"SWE-bench Verified {key} must be a string array")
    return list(cast(list[str], items))
