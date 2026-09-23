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
class WorkspaceFileRequirement:
    path: str
    mode: int

    def __post_init__(self) -> None:
        relative = Path(self.path)
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
            raise ContractError("qualified workspace file path must be a safe top-level path")
        if not 0 <= self.mode <= 0o777:
            raise ContractError(
                "qualified workspace file mode must contain ordinary permission bits"
            )


@dataclass(frozen=True, slots=True)
class TaskQualificationRequirements:
    mode: str
    base_commit: str = ""
    workspace_files: tuple[WorkspaceFileRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"git", "empty", "prepared", "prepared_contains"}:
            raise ContractError("unsupported task qualification mode")
        if (self.mode == "git") != bool(self.base_commit):
            raise ContractError("Git qualification requires exactly one base commit")
        if (self.mode in {"prepared", "prepared_contains"}) != bool(self.workspace_files):
            raise ContractError("prepared qualification requires workspace files")
        paths = tuple(item.path for item in self.workspace_files)
        if len(paths) != len(set(paths)):
            raise ContractError("qualified workspace file paths must be unique")


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
        self, episode: ResolvedEpisode, role: str
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
