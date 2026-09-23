"""Immutable CandidateBundle construction shared by inference adapters."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from axrun.errors import ContractError, InfrastructureError
from axrun.models import (
    CandidateBundle,
    CandidateFile,
    ResolvedEpisode,
    StageResult,
    canonical_digest,
    episode_seed_digest,
)


def persist_candidate(
    episode: ResolvedEpisode,
    result: StageResult,
    *,
    destination: Path,
    required_outputs: tuple[tuple[str, str], ...],
    harness: str,
    harness_version: str,
) -> CandidateBundle:
    parent = destination / "sha256"
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".candidate.", dir=parent))
    try:
        files: list[CandidateFile] = []
        for index, (role, required_path) in enumerate(required_outputs):
            source = result.artifact_for_path(required_path)
            source_path = Path(source.path)
            bundle_path = f"files/{index:02d}-{Path(required_path).name}"
            target = temporary / bundle_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
            digest = _sha256(target)
            if target.stat().st_size != source.size_bytes or digest != source.sha256:
                raise InfrastructureError(
                    f"CandidateBundle integrity verification failed: {required_path}"
                )
            _fsync_file(target)
            files.append(
                CandidateFile(
                    role=role,
                    declared_path=source.name,
                    bundle_path=bundle_path,
                    size_bytes=source.size_bytes,
                    sha256=source.sha256,
                    media_type=source.media_type,
                )
            )
        unsigned = {
            "schema_version": 1,
            "episode_id": episode.episode_id,
            "task_id": episode.task_id,
            "seed_digest": episode_seed_digest(episode),
            "inference_run_id": result.execution.run_id,
            "harness": harness,
            "harness_version": harness_version,
            "candidate": episode.candidate.identity,
            "candidate_version": episode.candidate.version,
            "files": [asdict(value) for value in files],
        }
        digest = canonical_digest(unsigned)
        final = parent / digest
        bundle = CandidateBundle(
            schema_version=1,
            episode_id=episode.episode_id,
            task_id=episode.task_id,
            seed_digest=episode_seed_digest(episode),
            inference_run_id=result.execution.run_id,
            harness=harness,
            harness_version=harness_version,
            candidate=episode.candidate.identity,
            candidate_version=episode.candidate.version,
            files=tuple(files),
            digest=digest,
            root=str(final),
        )
        manifest = temporary / "candidate-manifest.json"
        _durable_write(manifest, json.dumps(_manifest(bundle), indent=2, sort_keys=True) + "\n")
        _fsync_directory(temporary)
        if final.exists():
            existing = load_candidate(final / "candidate-manifest.json")
            if existing != bundle:
                raise ContractError("CandidateBundle digest collision")
            return existing
        os.replace(temporary, final)
        _fsync_directory(parent)
        return bundle
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def load_candidate(path: Path) -> CandidateBundle:
    if path.is_symlink():
        raise ContractError("CandidateBundle manifest must not be a symlink")
    raw = json.loads(path.read_text(encoding="utf-8"))
    files = tuple(CandidateFile(**value) for value in raw.pop("files"))
    digest = str(raw.pop("digest"))
    if canonical_digest({**raw, "files": [asdict(value) for value in files]}) != digest:
        raise ContractError("CandidateBundle manifest digest mismatch")
    bundle = CandidateBundle(**raw, files=files, digest=digest, root=str(path.parent))
    root = path.parent.resolve()
    for item in bundle.files:
        file_path = path.parent / item.bundle_path
        if (
            not file_path.is_file()
            or file_path.is_symlink()
            or not file_path.resolve().is_relative_to(root)
            or file_path.stat().st_size != item.size_bytes
            or _sha256(file_path) != item.sha256
        ):
            raise ContractError(f"CandidateBundle file integrity check failed: {item.bundle_path}")
    return bundle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(bundle: CandidateBundle) -> dict[str, object]:
    value = asdict(bundle)
    value.pop("root")
    return value


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
