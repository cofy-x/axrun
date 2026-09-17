"""Crash-safe local episode metadata store.

The store contains public Axern identities and caller-owned artifact locators. It
never contains credentials or sandbox-local runtime identity.
"""

from __future__ import annotations

import json
import os
from dataclasses import fields
from pathlib import Path
from typing import Any

from axrun.models import EpisodePhase, EpisodeRecord, ExecutionRef, ResolvedEpisode


class EpisodeStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, episode_id: str) -> Path:
        return self.root / "episodes" / f"{episode_id}.json"

    def save(self, record: EpisodeRecord) -> None:
        path = self.path_for(record.episode.episode_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        payload = json.dumps(record.as_dict(), sort_keys=True, indent=2) + "\n"
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def load(self, episode_id: str) -> EpisodeRecord | None:
        path = self.path_for(episode_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        episode = _dataclass_from_dict(ResolvedEpisode, raw["episode"])
        inference = _optional_execution(raw.get("inference"))
        verification = _optional_execution(raw.get("verification"))
        return EpisodeRecord(
            schema_version=int(raw["schema_version"]),
            episode=episode,
            phase=EpisodePhase(raw["phase"]),
            inference=inference,
            candidate_manifest=str(raw.get("candidate_manifest", "")),
            verification=verification,
            verification_result=str(raw.get("verification_result", "")),
            error=str(raw.get("error", "")),
        )


def _optional_execution(raw: Any) -> ExecutionRef | None:
    if raw is None:
        return None
    return _dataclass_from_dict(ExecutionRef, raw)


def _dataclass_from_dict(model: type[Any], raw: dict[str, Any]) -> Any:
    allowed = {item.name for item in fields(model)}
    return model(**{key: value for key, value in raw.items() if key in allowed})
