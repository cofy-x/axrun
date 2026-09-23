"""Content-addressed immutable TrajectoryBundle v1 publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError, InfrastructureError
from axrun.models import ResolvedEpisode, StageResult, canonical_digest, episode_seed_digest
from axrun.trajectories.schema import FORMAT, load_trajectory_jsonl


@dataclass(frozen=True, slots=True)
class TrajectoryArtifact:
    bundle_path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        relative = Path(self.bundle_path)
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
            raise ContractError("TrajectoryBundle artifact path must be a safe filename")
        if self.size_bytes < 0 or not _is_sha256(self.sha256):
            raise ContractError("TrajectoryBundle artifact metadata is invalid")


@dataclass(frozen=True, slots=True)
class TrajectoryBundle:
    schema_version: int
    episode_id: str
    task_id: str
    seed_digest: str
    inference_run_id: str
    harness: str
    harness_version: str
    format: str
    event_count: int
    trajectory: TrajectoryArtifact
    usage: TrajectoryArtifact
    digest: str
    root: str = field(default="", compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.format != FORMAT:
            raise ContractError("TrajectoryBundle must use v1 canonical trajectory format")
        if self.event_count <= 0:
            raise ContractError("TrajectoryBundle event_count must be positive")
        if not _is_sha256(self.seed_digest) or not _is_sha256(self.digest):
            raise ContractError("TrajectoryBundle digests must be lowercase SHA-256")
        if self.trajectory.bundle_path != "trajectory.jsonl":
            raise ContractError("TrajectoryBundle trajectory path is not canonical")
        if self.usage.bundle_path != "usage.json":
            raise ContractError("TrajectoryBundle usage path is not canonical")


def persist_trajectory_bundle(
    episode: ResolvedEpisode,
    result: StageResult,
    *,
    destination: Path,
    trajectory_path: str,
    usage_path: str,
    harness: str,
    harness_version: str,
) -> TrajectoryBundle:
    trajectory_source = result.artifact_for_path(trajectory_path)
    usage_source = result.artifact_for_path(usage_path)
    parent = destination / "sha256"
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".trajectory.", dir=parent))
    try:
        trajectory = _copy_artifact(trajectory_source, temporary / "trajectory.jsonl")
        usage = _copy_artifact(usage_source, temporary / "usage.json")
        events = load_trajectory_jsonl(temporary / trajectory.bundle_path)
        _validate_usage(temporary / usage.bundle_path)
        unsigned = {
            "schema_version": 1,
            "episode_id": episode.episode_id,
            "task_id": episode.task_id,
            "seed_digest": episode_seed_digest(episode),
            "inference_run_id": result.execution.run_id,
            "harness": harness,
            "harness_version": harness_version,
            "format": FORMAT,
            "event_count": len(events),
            "trajectory": asdict(trajectory),
            "usage": asdict(usage),
        }
        digest = canonical_digest(unsigned)
        final = parent / digest
        bundle = TrajectoryBundle(
            schema_version=1,
            episode_id=episode.episode_id,
            task_id=episode.task_id,
            seed_digest=episode_seed_digest(episode),
            inference_run_id=result.execution.run_id,
            harness=harness,
            harness_version=harness_version,
            format=FORMAT,
            event_count=len(events),
            trajectory=trajectory,
            usage=usage,
            digest=digest,
            root=str(final),
        )
        _durable_write(
            temporary / "trajectory-manifest.json",
            json.dumps(_manifest(bundle), sort_keys=True, indent=2) + "\n",
        )
        _fsync_directory(temporary)
        if final.exists():
            existing = load_trajectory_bundle(final / "trajectory-manifest.json")
            if existing != bundle:
                raise ContractError("TrajectoryBundle digest collision")
            return existing
        os.replace(temporary, final)
        _fsync_directory(parent)
        return bundle
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def load_trajectory_bundle(path: Path) -> TrajectoryBundle:
    if not path.is_file() or path.is_symlink():
        raise ContractError("TrajectoryBundle manifest must be a regular file")
    raw_value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_value, dict):
        raise ContractError("TrajectoryBundle manifest must be an object")
    raw = cast(dict[str, Any], raw_value)
    expected = {
        "schema_version",
        "episode_id",
        "task_id",
        "seed_digest",
        "inference_run_id",
        "harness",
        "harness_version",
        "format",
        "event_count",
        "trajectory",
        "usage",
        "digest",
    }
    if set(raw) != expected:
        raise ContractError("TrajectoryBundle manifest fields are invalid")
    trajectory_raw = raw.get("trajectory")
    usage_raw = raw.get("usage")
    if not isinstance(trajectory_raw, dict) or not isinstance(usage_raw, dict):
        raise ContractError("TrajectoryBundle artifacts are invalid")
    trajectory = _artifact_from_dict(cast(dict[str, Any], trajectory_raw))
    usage = _artifact_from_dict(cast(dict[str, Any], usage_raw))
    values = dict(raw)
    values["trajectory"] = trajectory
    values["usage"] = usage
    digest = str(values.pop("digest"))
    unsigned = {
        **values,
        "trajectory": asdict(trajectory),
        "usage": asdict(usage),
    }
    if canonical_digest(unsigned) != digest:
        raise ContractError("TrajectoryBundle manifest digest mismatch")
    bundle = TrajectoryBundle(
        schema_version=_integer(values.get("schema_version"), "schema_version"),
        episode_id=_string(values.get("episode_id"), "episode_id"),
        task_id=_string(values.get("task_id"), "task_id"),
        seed_digest=_string(values.get("seed_digest"), "seed_digest"),
        inference_run_id=_string(values.get("inference_run_id"), "inference_run_id"),
        harness=_string(values.get("harness"), "harness"),
        harness_version=_string(values.get("harness_version"), "harness_version"),
        format=_string(values.get("format"), "format"),
        event_count=_integer(values.get("event_count"), "event_count"),
        trajectory=trajectory,
        usage=usage,
        digest=digest,
        root=str(path.parent),
    )
    root = path.parent.resolve()
    for artifact in (bundle.trajectory, bundle.usage):
        artifact_path = path.parent / artifact.bundle_path
        if (
            not artifact_path.is_file()
            or artifact_path.is_symlink()
            or not artifact_path.resolve().is_relative_to(root)
            or artifact_path.stat().st_size != artifact.size_bytes
            or _sha256(artifact_path) != artifact.sha256
        ):
            raise ContractError(
                f"TrajectoryBundle file integrity check failed: {artifact.bundle_path}"
            )
    events = load_trajectory_jsonl(path.parent / bundle.trajectory.bundle_path)
    if len(events) != bundle.event_count:
        raise ContractError("TrajectoryBundle event count mismatch")
    _validate_usage(path.parent / bundle.usage.bundle_path)
    return bundle


def _copy_artifact(source: Any, target: Path) -> TrajectoryArtifact:
    source_path = Path(source.path)
    if not source_path.is_file() or source_path.is_symlink():
        raise InfrastructureError("sealed trajectory source must be a regular file")
    shutil.copyfile(source_path, target)
    digest = _sha256(target)
    if target.stat().st_size != source.size_bytes or digest != source.sha256:
        raise InfrastructureError(f"TrajectoryBundle integrity verification failed: {source.name}")
    _fsync_file(target)
    return TrajectoryArtifact(target.name, source.size_bytes, source.sha256)


def _validate_usage(path: Path) -> None:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    keys = {
        "schema_version",
        "observations",
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    }
    if not isinstance(raw, dict):
        raise ContractError("TrajectoryBundle usage contract is invalid")
    values = cast(dict[str, object], raw)
    if set(values) != keys or values.get("schema_version") != 1:
        raise ContractError("TrajectoryBundle usage contract is invalid")
    for key in keys - {"schema_version"}:
        value = values.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContractError("TrajectoryBundle usage values must be non-negative integers")


def _manifest(bundle: TrajectoryBundle) -> dict[str, object]:
    value = asdict(bundle)
    value.pop("root")
    return value


def _artifact_from_dict(value: dict[str, Any]) -> TrajectoryArtifact:
    if set(value) != {"bundle_path", "size_bytes", "sha256"}:
        raise ContractError("TrajectoryBundle artifact fields are invalid")
    return TrajectoryArtifact(
        bundle_path=_string(value.get("bundle_path"), "bundle_path"),
        size_bytes=_integer(value.get("size_bytes"), "size_bytes"),
        sha256=_string(value.get("sha256"), "sha256"),
    )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"TrajectoryBundle {name} must be a string")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContractError(f"TrajectoryBundle {name} must be an integer")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _durable_write(path: Path, value: str) -> None:
    with path.open("w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
