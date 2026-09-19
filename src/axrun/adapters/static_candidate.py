"""Deterministic model-free harness used for candidate contract acceptance."""

from __future__ import annotations

from dataclasses import dataclass

from axrun.errors import ContractError
from axrun.models import CandidateCapturePlan, ResolvedEpisode, StagePlan


@dataclass(frozen=True, slots=True)
class StaticCandidateHarness:
    version: str = "1"
    name: str = "static-candidate"

    def plan(self, episode: ResolvedEpisode, capture: CandidateCapturePlan) -> StagePlan:
        if (episode.harness.identity, episode.harness.version) != (self.name, self.version):
            raise ContractError("static candidate harness requires static-candidate@1")
        return StagePlan(
            environment_id=episode.inference_environment.environment_id,
            argv=(
                "/bin/sh",
                "-lc",
                "\n".join(
                    (
                        "set -eu",
                        "mkdir -p /outputs /run/axrun",
                        capture.setup_script,
                        capture.finalize_script,
                    )
                ),
            ),
            cwd=episode.inference_environment.working_directory,
            inputs=capture.inputs,
            outputs=capture.outputs,
            resources=episode.inference_resources,
            network_policy="deny_all",
            timeout_seconds=episode.harness.timeout_seconds,
            labels={"axrun.stage": "inference", "axrun.agent": self.name},
        )
