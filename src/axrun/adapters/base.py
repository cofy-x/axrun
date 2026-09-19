"""Small adapter contracts owned by Axrun."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from axrun.errors import ContractError
from axrun.models import (
    CandidateBundle,
    CandidateCapturePlan,
    HarnessRuntimeRequirements,
    ResolvedEpisode,
    StagePlan,
    StageResult,
    VerificationResult,
)
from axrun.trajectories.bundle import TrajectoryBundle


@dataclass(frozen=True, slots=True)
class TaskQualificationRequirements:
    mode: str
    base_commit: str = ""

    def __post_init__(self) -> None:
        if self.mode not in {"git", "empty"}:
            raise ContractError("unsupported task qualification mode")
        if (self.mode == "git") != bool(self.base_commit):
            raise ContractError("Git qualification requires exactly one base commit")


@dataclass(frozen=True, slots=True)
class HarnessQualificationRequirements:
    claude_mount_image: str = ""


@dataclass(frozen=True, slots=True)
class CandidateQualificationRequirements:
    archive_finalizer: bool = False


@dataclass(frozen=True, slots=True)
class VerifierQualificationRequirements:
    verifier_file: str = ""


class TaskAdapter(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def qualification_requirements(
        self, episode: ResolvedEpisode
    ) -> TaskQualificationRequirements: ...


class InferenceAdapter(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def runtime_requirements(self) -> HarnessRuntimeRequirements: ...

    def qualification_requirements(
        self, episode: ResolvedEpisode
    ) -> HarnessQualificationRequirements: ...

    def plan(self, episode: ResolvedEpisode, capture: CandidateCapturePlan) -> StagePlan: ...


class CandidateAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def capture_plan(self, episode: ResolvedEpisode) -> CandidateCapturePlan: ...

    def qualification_requirements(
        self, episode: ResolvedEpisode
    ) -> CandidateQualificationRequirements: ...

    def build(
        self, episode: ResolvedEpisode, result: StageResult, *, destination: Path
    ) -> CandidateBundle: ...


class VerifierAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan: ...

    def qualification_requirements(
        self, episode: ResolvedEpisode
    ) -> VerifierQualificationRequirements: ...

    def parse_result(self, result: StageResult) -> VerificationResult: ...


class TrajectoryAdapter(Protocol):
    def build_bundle(
        self, episode: ResolvedEpisode, result: StageResult, *, destination: Path
    ) -> TrajectoryBundle: ...
