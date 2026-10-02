"""Crash-safe, caller-local episode records and content-addressed results."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError, RecoveryRequiredError
from axrun.models import (
    EpisodePhase,
    EpisodeRecord,
    ExecutionRef,
    ResolvedEpisode,
    VerificationResult,
    canonical_digest,
    canonical_json,
    resolved_episode_from_dict,
)


class EpisodeStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, episode_id: str) -> Path:
        return self.root / "episodes" / _safe_episode_id(episode_id) / "execution.json"

    def spec_path_for(self, episode_id: str) -> Path:
        return self.root / "episodes" / _safe_episode_id(episode_id) / "spec.json"

    def initialize(self, episode: ResolvedEpisode) -> EpisodeRecord:
        existing = self.load(episode.episode_id)
        if existing is not None:
            if existing.spec_digest != episode.digest:
                raise RecoveryRequiredError("persisted episode specification digest differs")
            self.load_spec(episode.episode_id)
            return existing
        spec_path = self.spec_path_for(episode.episode_id)
        if spec_path.exists():
            persisted = self._read_spec(episode.episode_id)
            if (
                persisted.get("episode_id") != episode.episode_id
                or canonical_digest(persisted) != episode.digest
            ):
                raise RecoveryRequiredError("orphaned episode specification differs")
        else:
            atomic_write(spec_path, canonical_json(episode.as_dict()) + b"\n")
        now = _now()
        record = EpisodeRecord(1, episode.episode_id, episode.digest, created_at=now)
        self.save(record)
        return record

    def save(self, record: EpisodeRecord) -> None:
        value = record.as_dict()
        _validate_record(value, record.episode_id)
        payload = json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"
        atomic_write(self.path_for(record.episode_id), payload)

    def load(self, episode_id: str) -> EpisodeRecord | None:
        path = self.path_for(episode_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        _validate_record(raw, episode_id)
        return EpisodeRecord(
            schema_version=raw["schema_version"],
            episode_id=raw["episode_id"],
            spec_digest=raw["spec_digest"],
            phase=EpisodePhase(raw["phase"]),
            qualifications=tuple(ExecutionRef(**item) for item in raw.get("qualifications", [])),
            qualification_result=str(raw.get("qualification_result", "")),
            qualification_result_digest=str(raw.get("qualification_result_digest", "")),
            inference=_optional_execution(raw.get("inference")),
            candidate_manifest=str(raw.get("candidate_manifest", "")),
            candidate_digest=str(raw.get("candidate_digest", "")),
            trajectory_manifest=str(raw.get("trajectory_manifest", "")),
            trajectory_digest=str(raw.get("trajectory_digest", "")),
            progress_path=str(raw.get("progress_path", "")),
            progress_revision=int(raw.get("progress_revision", 0)),
            inference_termination_reason=str(raw.get("inference_termination_reason", "")),
            verification=_optional_execution(raw.get("verification")),
            verification_result=str(raw.get("verification_result", "")),
            verification_result_digest=str(raw.get("verification_result_digest", "")),
            diagnostic_code=str(raw.get("diagnostic_code", "")),
            message=str(raw.get("message", "")),
            created_at=str(raw.get("created_at", "")),
            completed_at=str(raw.get("completed_at", "")),
        )

    def load_spec(self, episode_id: str) -> ResolvedEpisode:
        raw = self._read_spec(episode_id)
        episode = resolved_episode_from_dict(raw)
        if episode.episode_id != episode_id:
            raise ContractError("persisted episode specification identity differs")
        record = self.load(episode_id)
        if record is None or record.spec_digest != episode.digest:
            raise ContractError("episode specification integrity check failed")
        return episode

    def _read_spec(self, episode_id: str) -> dict[str, Any]:
        path = self.spec_path_for(episode_id)
        if not path.exists():
            raise RecoveryRequiredError("persisted episode specification is missing")
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ContractError("persisted episode specification is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise ContractError("persisted episode specification must be an object")
        return cast(dict[str, Any], raw)

    def save_result(self, result: VerificationResult) -> tuple[Path, str]:
        value = asdict(result)
        digest = canonical_digest(value)
        path = self.root / "results" / "sha256" / digest / "verification-result.json"
        atomic_write(path, json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")
        return path, digest

    def load_result(self, path: str, digest: str) -> VerificationResult:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if canonical_digest(raw) != digest:
            raise ContractError("VerificationResult digest mismatch")
        return VerificationResult(**raw)

    @contextmanager
    def lock(self, episode_id: str) -> Generator[None, None, None]:
        lock_path = self.root / "locks" / f"{_safe_episode_id(episode_id)}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as stream:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _optional_execution(raw: Any) -> ExecutionRef | None:
    return None if raw is None else ExecutionRef(**raw)


def _safe_episode_id(episode_id: object) -> str:
    if (
        not isinstance(episode_id, str)
        or not episode_id
        or episode_id == "."
        or ".." in episode_id
        or any(
            character in "/\\" or ord(character) < 32 or ord(character) == 127
            for character in episode_id
        )
    ):
        raise ContractError("episode_id must be a safe path component")
    return episode_id


def _validate_record(raw: object, episode_id: str) -> None:
    _safe_episode_id(episode_id)
    if not isinstance(raw, dict):
        raise ContractError("persisted episode record must be an object")
    record = cast(dict[str, Any], raw)
    if set(record) - {item.name for item in fields(EpisodeRecord)}:
        raise ContractError("persisted episode record has unknown fields")
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise ContractError("unsupported persisted episode record schema")
    if record.get("episode_id") != episode_id:
        raise ContractError("persisted episode record identity differs")
    spec_digest = record.get("spec_digest")
    if (
        not isinstance(spec_digest, str)
        or len(spec_digest) != 64
        or any(character not in "0123456789abcdef" for character in spec_digest)
    ):
        raise ContractError("persisted episode specification digest is invalid")
    phase = record.get("phase")
    if not isinstance(phase, str) or phase not in {value.value for value in EpisodePhase}:
        raise ContractError("persisted episode phase is invalid")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()
