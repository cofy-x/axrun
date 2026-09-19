"""Git patch candidate capture independent from the producing harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from axrun.adapters._candidate import persist_candidate
from axrun.errors import ContractError
from axrun.models import CandidateBundle, ResolvedEpisode, StageResult


@dataclass(frozen=True, slots=True)
class GitPatchCandidateAdapter:
    version: str = "1"
    name: str = "git-patch"

    def build(
        self,
        episode: ResolvedEpisode,
        result: StageResult,
        *,
        destination: Path,
    ) -> CandidateBundle:
        if episode.candidate.identity != self.name or episode.candidate.version != self.version:
            raise ContractError("Git patch candidate adapter requires git-patch@1")
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_outputs=(("patch", "/outputs/candidate.patch"),),
            harness=episode.harness.identity,
            harness_version=episode.harness.version,
        )
