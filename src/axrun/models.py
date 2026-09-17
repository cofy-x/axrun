"""Language-neutral Axrun domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from axrun.errors import ContractError


class EpisodePhase(StrEnum):
    NEW = "new"
    INFERENCE_RUNNING = "inference_running"
    CANDIDATE_READY = "candidate_ready"
    VERIFICATION_RUNNING = "verification_running"
    COMPLETED = "completed"
    FAILED = "failed"


class OutputFormat(StrEnum):
    FILE = "file"
    TAR = "tar"


@dataclass(frozen=True, slots=True)
class OutputSpec:
    path: str
    format: OutputFormat = OutputFormat.FILE
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ContractError("declared output path must be absolute")


@dataclass(frozen=True, slots=True)
class InputFile:
    source: str
    target: str
    sha256: str = ""
    archive: bool = False

    def __post_init__(self) -> None:
        if not self.target.startswith("/"):
            raise ContractError("input target must be absolute")


@dataclass(frozen=True, slots=True)
class ImageMountSpec:
    image: str
    target: str
    readonly: bool = True


@dataclass(frozen=True, slots=True)
class SecretEnvSpec:
    name: str
    secret_id: str
    key: str


@dataclass(frozen=True, slots=True)
class StagePlan:
    environment_id: str
    argv: tuple[str, ...]
    cwd: str
    outputs: tuple[OutputSpec, ...]
    inputs: tuple[InputFile, ...] = ()
    env: dict[str, str] = field(default_factory=dict[str, str])
    image_mounts: tuple[ImageMountSpec, ...] = ()
    secret_env: tuple[SecretEnvSpec, ...] = ()
    network_policy: str = "default"
    timeout_seconds: int = 3600
    labels: dict[str, str] = field(default_factory=dict[str, str])

    def __post_init__(self) -> None:
        if not self.environment_id:
            raise ContractError("stage environment_id is required")
        if not self.argv:
            raise ContractError("stage argv is required")
        paths = [output.path for output in self.outputs]
        if len(paths) != len(set(paths)):
            raise ContractError("declared output paths must be unique")


@dataclass(frozen=True, slots=True)
class ResolvedEpisode:
    schema_version: int
    episode_id: str
    task_id: str
    task_digest: str
    base_commit: str
    prompt_file: str
    inference_environment_id: str
    verification_environment_id: str
    metadata: dict[str, str] = field(default_factory=dict[str, str])

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ContractError(f"unsupported ResolvedEpisode schema {self.schema_version}")
        if not self.episode_id or not self.task_id:
            raise ContractError("episode_id and task_id are required")
        if len(self.base_commit) not in {40, 64} or any(
            value not in "0123456789abcdefABCDEF" for value in self.base_commit
        ):
            raise ContractError("base_commit must be a full 40- or 64-character hex digest")


@dataclass(frozen=True, slots=True)
class ExecutionRef:
    environment_id: str
    run_id: str
    allocation_id: str = ""


@dataclass(frozen=True, slots=True)
class Artifact:
    name: str
    path: str
    size_bytes: int
    sha256: str
    media_type: str


@dataclass(frozen=True, slots=True)
class StageResult:
    execution: ExecutionRef
    exit_code: int
    diagnostic_code: str
    artifacts: tuple[Artifact, ...]

    def artifact_for_path(self, path: str) -> Artifact:
        try:
            return next(artifact for artifact in self.artifacts if artifact.name == path)
        except StopIteration as exc:
            raise ContractError(f"required sealed output is missing: {path}") from exc


@dataclass(frozen=True, slots=True)
class CandidateBundle:
    schema_version: int
    episode_id: str
    task_id: str
    task_digest: str
    base_commit: str
    inference: ExecutionRef
    artifacts: tuple[Artifact, ...]


@dataclass(frozen=True, slots=True)
class VerificationResult:
    schema_version: int
    resolved: bool
    score: float
    verifier: str
    details: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(slots=True)
class EpisodeRecord:
    schema_version: int
    episode: ResolvedEpisode
    phase: EpisodePhase = EpisodePhase.NEW
    inference: ExecutionRef | None = None
    candidate_manifest: str = ""
    verification: ExecutionRef | None = None
    verification_result: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def artifact_path(artifact: Artifact) -> Path:
    return Path(artifact.path)
