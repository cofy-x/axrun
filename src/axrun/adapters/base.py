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
from axrun.trajectories.bundle import TrajectoryBundle


class InferenceAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def plan(self, episode: ResolvedEpisode) -> StagePlan: ...

    def build_candidate(
        self, episode: ResolvedEpisode, result: StageResult, *, destination: Path
    ) -> CandidateBundle: ...


class VerifierAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan: ...

    def parse_result(self, result: StageResult) -> VerificationResult: ...


class TrajectoryAdapter(Protocol):
    def build_bundle(
        self, episode: ResolvedEpisode, result: StageResult, *, destination: Path
    ) -> TrajectoryBundle: ...
