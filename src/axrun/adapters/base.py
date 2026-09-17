"""Small adapter contracts owned by Axrun."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from axrun.models import (
    CandidateBundle,
    ResolvedEpisode,
    StagePlan,
    StageResult,
    VerificationResult,
)


class InferenceAdapter(Protocol):
    name: str

    def plan(self, episode: ResolvedEpisode) -> StagePlan: ...

    def build_candidate(
        self, episode: ResolvedEpisode, result: StageResult, *, destination: Path
    ) -> CandidateBundle: ...


class VerifierAdapter(Protocol):
    name: str

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan: ...

    def parse_result(self, result: StageResult) -> VerificationResult: ...
