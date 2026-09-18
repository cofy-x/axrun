"""Deterministic inference adapter used to qualify the two-stage contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from axrun.adapters._candidate import persist_candidate
from axrun.errors import ContractError
from axrun.models import (
    CandidateBundle,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    StageResult,
)

_PATCH = "/outputs/candidate.patch"


@dataclass(frozen=True, slots=True)
class StaticPatchAdapter:
    version: str = "1"
    name: str = "static-patch"

    def plan(self, episode: ResolvedEpisode) -> StagePlan:
        if episode.harness.identity != self.name:
            raise ContractError("static-patch requires a matching harness")
        candidate = episode.harness.config.get("candidate_file")
        if not isinstance(candidate, str) or not candidate:
            raise ContractError("static-patch candidate_file must be a non-empty string")
        return StagePlan(
            environment_id=episode.inference_environment_id,
            argv=(
                "/bin/sh",
                "-lc",
                "set -eu; mkdir -p /outputs; cp /inputs/candidate.patch /outputs/candidate.patch",
            ),
            cwd="/workspace",
            inputs=(InputFile(candidate, "/inputs/candidate.patch"),),
            outputs=(OutputSpec(_PATCH, media_type="text/x-diff"),),
            resources=episode.inference_resources,
            network_policy="deny_all",
            timeout_seconds=episode.harness.timeout_seconds,
            labels={"axrun.stage": "inference", "axrun.agent": self.name},
        )

    def build_candidate(
        self,
        episode: ResolvedEpisode,
        result: StageResult,
        *,
        destination: Path,
    ) -> CandidateBundle:
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_paths=(_PATCH,),
            harness=self.name,
            harness_version=self.version,
        )
