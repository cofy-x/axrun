"""Atomic caller-local storage for non-authoritative progress snapshots."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from axrun.errors import ContractError
from axrun.progress.schema import (
    ProgressSnapshot,
    canonical_progress_bytes,
    progress_snapshot_from_bytes,
)


class ProgressStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, episode_id: str) -> Path:
        if not episode_id or any(value in episode_id for value in ("/", "\\", "..")):
            raise ContractError("progress episode_id must be a safe path component")
        return self.root / "progress" / episode_id / "progress.json"

    def save(self, snapshot: ProgressSnapshot) -> Path:
        path = self.path_for(snapshot.episode_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".progress.json.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(canonical_progress_bytes(snapshot))
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
        return path

    def load(self, episode_id: str) -> ProgressSnapshot | None:
        path = self.path_for(episode_id)
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise ContractError("progress record must be a regular file")
        return progress_snapshot_from_bytes(path.read_bytes())
