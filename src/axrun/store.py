"""Crash-safe, caller-local episode records and content-addressed results."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        return self.root / "episodes" / episode_id / "execution.json"

    def spec_path_for(self, episode_id: str) -> Path:
        return self.root / "episodes" / episode_id / "spec.json"

    def initialize(self, episode: ResolvedEpisode) -> EpisodeRecord:
        existing = self.load(episode.episode_id)
        if existing is not None:
            if existing.spec_digest != episode.digest:
                raise RecoveryRequiredError("persisted episode specification digest differs")
            return existing
        now = _now()
        record = EpisodeRecord(1, episode.episode_id, episode.digest, created_at=now)
        _atomic_write(
            self.spec_path_for(episode.episode_id), canonical_json(asdict(episode)) + b"\n"
        )
        self.save(record)
        return record

    def save(self, record: EpisodeRecord) -> None:
        payload = json.dumps(record.as_dict(), sort_keys=True, indent=2).encode() + b"\n"
        _atomic_write(self.path_for(record.episode_id), payload)

    def load(self, episode_id: str) -> EpisodeRecord | None:
        path = self.path_for(episode_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return EpisodeRecord(
            schema_version=int(raw["schema_version"]),
            episode_id=str(raw["episode_id"]),
            spec_digest=str(raw["spec_digest"]),
            phase=EpisodePhase(raw["phase"]),
            inference=_optional_execution(raw.get("inference")),
            candidate_manifest=str(raw.get("candidate_manifest", "")),
            candidate_digest=str(raw.get("candidate_digest", "")),
            trajectory_manifest=str(raw.get("trajectory_manifest", "")),
            trajectory_digest=str(raw.get("trajectory_digest", "")),
            progress_path=str(raw.get("progress_path", "")),
            progress_revision=int(raw.get("progress_revision", 0)),
            verification=_optional_execution(raw.get("verification")),
            verification_result=str(raw.get("verification_result", "")),
            verification_result_digest=str(raw.get("verification_result_digest", "")),
            diagnostic_code=str(raw.get("diagnostic_code", "")),
            message=str(raw.get("message", "")),
            created_at=str(raw.get("created_at", "")),
            completed_at=str(raw.get("completed_at", "")),
        )

    def load_spec(self, episode_id: str) -> ResolvedEpisode:
        raw = json.loads(self.spec_path_for(episode_id).read_text(encoding="utf-8"))
        episode = resolved_episode_from_dict(raw)
        record = self.load(episode_id)
        if record is None or record.spec_digest != episode.digest:
            raise ContractError("episode specification integrity check failed")
        return episode

    def save_result(self, result: VerificationResult) -> tuple[Path, str]:
        value = asdict(result)
        digest = canonical_digest(value)
        path = self.root / "results" / "sha256" / digest / "verification-result.json"
        _atomic_write(path, json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")
        return path, digest

    def load_result(self, path: str, digest: str) -> VerificationResult:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if canonical_digest(raw) != digest:
            raise ContractError("VerificationResult digest mismatch")
        return VerificationResult(**raw)

    @contextmanager
    def lock(self, episode_id: str) -> Generator[None, None, None]:
        lock_path = self.root / "locks" / f"{episode_id}.lock"
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


def _atomic_write(path: Path, payload: bytes) -> None:
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
