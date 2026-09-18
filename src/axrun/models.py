"""Versioned, language-neutral Axrun domain contracts."""

from __future__ import annotations

import hashlib
import json
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
    CANCELLED = "cancelled"
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
class ResourceSpec:
    request_cpu: str = ""
    request_memory: str = ""
    request_ephemeral_storage: str = ""
    limit_cpu: str = ""
    limit_memory: str = ""
    limit_ephemeral_storage: str = ""


@dataclass(frozen=True, slots=True)
class MiniSweAgentSpec:
    command: tuple[str, ...] = ("mini",)
    version: str = "2.4.6"
    timeout_seconds: int = 7200

    def __post_init__(self) -> None:
        if not self.command or not self.version or self.timeout_seconds <= 0:
            raise ContractError("mini-swe-agent command and version are required")


@dataclass(frozen=True, slots=True)
class VerifierSpec:
    command: tuple[str, ...] = ("/opt/axrun/run-verifier",)
    identity: str = "command-verifier"
    version: str = "1"
    timeout_seconds: int = 7200

    def __post_init__(self) -> None:
        if not self.command or not self.identity or not self.version or self.timeout_seconds <= 0:
            raise ContractError("verifier command, identity, and version are required")


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
    resources: ResourceSpec = field(default_factory=ResourceSpec)
    network_policy: str = "default"
    timeout_seconds: int = 3600
    labels: dict[str, str] = field(default_factory=dict[str, str])

    def __post_init__(self) -> None:
        if not self.environment_id or not self.argv:
            raise ContractError("stage environment_id and argv are required")
        if self.timeout_seconds <= 0:
            raise ContractError("stage timeout_seconds must be positive")
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
    harness: MiniSweAgentSpec = field(default_factory=MiniSweAgentSpec)
    verifier: VerifierSpec = field(default_factory=VerifierSpec)
    inference_resources: ResourceSpec = field(default_factory=ResourceSpec)
    verification_resources: ResourceSpec = field(default_factory=ResourceSpec)
    metadata: dict[str, str] = field(default_factory=dict[str, str])

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ContractError(f"unsupported ResolvedEpisode schema {self.schema_version}")
        if not self.episode_id or not self.task_id or not self.task_digest:
            raise ContractError("episode_id, task_id, and task_digest are required")
        if any(value in self.episode_id for value in ("/", "\\", "..")):
            raise ContractError("episode_id must be a safe path component")
        if len(self.base_commit) not in {40, 64} or any(
            value not in "0123456789abcdefABCDEF" for value in self.base_commit
        ):
            raise ContractError("base_commit must be a full 40- or 64-character hex digest")

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class ExecutionRef:
    environment_id: str
    run_id: str
    allocation_id: str = ""


@dataclass(frozen=True, slots=True)
class Artifact:
    """One Axern sealed output downloaded and verified by the SDK."""

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
    stdout_path: str = ""
    stderr_path: str = ""

    def artifact_for_path(self, path: str) -> Artifact:
        try:
            return next(artifact for artifact in self.artifacts if artifact.name == path)
        except StopIteration as exc:
            raise ContractError(f"required sealed output is missing: {path}") from exc


@dataclass(frozen=True, slots=True)
class CandidateFile:
    declared_path: str
    bundle_path: str
    size_bytes: int
    sha256: str
    media_type: str

    def __post_init__(self) -> None:
        relative = Path(self.bundle_path)
        if not self.declared_path.startswith("/"):
            raise ContractError("candidate declared path must be absolute")
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ContractError("candidate bundle path must be a safe relative path")
        if len(self.sha256) != 64 or any(value not in "0123456789abcdef" for value in self.sha256):
            raise ContractError("candidate file sha256 must be lowercase hexadecimal")


@dataclass(frozen=True, slots=True)
class CandidateBundle:
    schema_version: int
    episode_id: str
    task_id: str
    task_digest: str
    base_commit: str
    inference_run_id: str
    harness: str
    harness_version: str
    files: tuple[CandidateFile, ...]
    digest: str
    root: str = field(default="", compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.files:
            raise ContractError("CandidateBundle v1 requires at least one file")
        if len(self.digest) != 64 or any(value not in "0123456789abcdef" for value in self.digest):
            raise ContractError("CandidateBundle digest must be lowercase hexadecimal")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    schema_version: int
    candidate_digest: str
    verifier: str
    verifier_version: str
    verdict: str
    diagnostic_code: str
    verifier_exit_code: int
    output_digest: str
    started_at: str
    completed_at: str
    score: float | None = None
    details: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.verdict not in {"passed", "failed"}:
            raise ContractError("VerificationResult v1 verdict must be passed or failed")
        for name, value in (
            ("candidate_digest", self.candidate_digest),
            ("output_digest", self.output_digest),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ContractError(f"{name} must be lowercase hexadecimal")


@dataclass(slots=True)
class EpisodeRecord:
    schema_version: int
    episode_id: str
    spec_digest: str
    phase: EpisodePhase = EpisodePhase.NEW
    inference: ExecutionRef | None = None
    candidate_manifest: str = ""
    candidate_digest: str = ""
    verification: ExecutionRef | None = None
    verification_result: str = ""
    verification_result_digest: str = ""
    diagnostic_code: str = ""
    message: str = ""
    created_at: str = ""
    completed_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def resolved_episode_from_dict(raw: dict[str, Any]) -> ResolvedEpisode:
    """Decode the versioned public JSON contract without accepting unknown fields."""
    expected = {
        "schema_version",
        "episode_id",
        "task_id",
        "task_digest",
        "base_commit",
        "prompt_file",
        "inference_environment_id",
        "verification_environment_id",
        "harness",
        "verifier",
        "inference_resources",
        "verification_resources",
        "metadata",
    }
    unknown = set(raw) - expected
    if unknown:
        raise ContractError(f"unknown ResolvedEpisode fields: {', '.join(sorted(unknown))}")
    values = dict(raw)
    harness = dict(values.pop("harness", {}))
    verifier = dict(values.pop("verifier", {}))
    inference_resources = dict(values.pop("inference_resources", {}))
    verification_resources = dict(values.pop("verification_resources", {}))
    if "command" in harness:
        harness["command"] = tuple(harness["command"])
    if "command" in verifier:
        verifier["command"] = tuple(verifier["command"])
    return ResolvedEpisode(
        **values,
        harness=MiniSweAgentSpec(**harness),
        verifier=VerifierSpec(**verifier),
        inference_resources=ResourceSpec(**inference_resources),
        verification_resources=ResourceSpec(**verification_resources),
    )


def artifact_path(artifact: Artifact) -> Path:
    return Path(artifact.path)
