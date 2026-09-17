"""CandidateBundle construction shared by inference adapters."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from axrun.errors import InfrastructureError
from axrun.models import Artifact, CandidateBundle, ResolvedEpisode, StageResult


def persist_candidate(
    episode: ResolvedEpisode,
    result: StageResult,
    *,
    destination: Path,
    required_paths: tuple[str, ...],
) -> CandidateBundle:
    destination.mkdir(parents=True, exist_ok=True)
    artifacts: list[Artifact] = []
    for index, required_path in enumerate(required_paths):
        source = result.artifact_for_path(required_path)
        source_path = Path(source.path)
        target = destination / f"{index:02d}-{Path(required_path).name}"
        shutil.copyfile(source_path, target)
        digest = _sha256(target)
        if target.stat().st_size != source.size_bytes or digest != source.sha256:
            target.unlink(missing_ok=True)
            raise InfrastructureError(
                f"CandidateBundle copy failed integrity verification: {required_path}"
            )
        artifacts.append(
            Artifact(
                name=source.name,
                path=str(target),
                size_bytes=source.size_bytes,
                sha256=source.sha256,
                media_type=source.media_type,
            )
        )
    bundle = CandidateBundle(
        schema_version=1,
        episode_id=episode.episode_id,
        task_id=episode.task_id,
        task_digest=episode.task_digest,
        base_commit=episode.base_commit,
        inference=result.execution,
        artifacts=tuple(artifacts),
    )
    manifest = destination / "candidate-manifest.json"
    manifest.write_text(
        json.dumps(asdict(bundle), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return bundle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
