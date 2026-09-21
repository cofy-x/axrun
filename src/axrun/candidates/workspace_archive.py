"""Whole-workspace candidate capture."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from axrun.adapters._candidate import persist_candidate
from axrun.adapters.base import CandidateQualificationRequirements
from axrun.errors import ContractError
from axrun.models import (
    CandidateBundle,
    CandidateCapturePlan,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StageResult,
)

_TOP_LEVEL_PATH = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class WorkspaceArchiveCandidateAdapter:
    version: str = "1"
    name: str = "workspace-archive"

    def qualification_requirements(
        self, episode: ResolvedEpisode
    ) -> CandidateQualificationRequirements:
        self._validate(episode)
        return CandidateQualificationRequirements(archive_finalizer=True)

    def capture_plan(self, episode: ResolvedEpisode) -> CandidateCapturePlan:
        self._validate(episode)
        package_root = Path(__file__).parents[1]
        module = Path(__file__).with_name("archive.py")
        errors = package_root / "errors.py"
        source = episode.candidate.config.get("source_directory")
        source_mode = episode.candidate.config.get("source_mode", "empty")
        source_manifest_digest = episode.candidate.config.get("source_manifest_digest", "")
        if source_mode not in {"empty", "overlay"}:
            raise ContractError("workspace-archive source_mode must be empty or overlay")
        excluded = _excluded_paths(episode.candidate.config.get("exclude_paths", []))
        workspace = shlex.quote(episode.inference_environment.working_directory)
        remove_excluded = tuple(
            "rm -f -- "
            + shlex.quote(f"{episode.inference_environment.working_directory}/{relative}")
            for relative in excluded
        )
        inputs = [
            InputFile(str(module), "/opt/axrun/axrun/candidates/archive.py"),
            InputFile(str(errors), "/opt/axrun/axrun/errors.py"),
        ]
        setup_script = ""
        if source is None:
            script = "\n".join(
                (
                    *remove_excluded,
                    "PYTHONPATH=/opt/axrun python3 /opt/axrun/axrun/candidates/archive.py create "
                    f"{workspace} /outputs/workspace.tar",
                )
            )
        elif isinstance(source, str) and source:
            source_root = Path(source).resolve()
            if not source_root.is_dir() or source_root.is_symlink():
                raise ContractError("workspace-archive source_directory must be a directory")
            source_files = sorted(
                (path for path in source_root.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(source_root).as_posix(),
            )
            if any(path.is_symlink() for path in source_root.rglob("*")):
                raise ContractError("workspace-archive source_directory rejects symlinks")
            manifest = {
                path.relative_to(source_root).as_posix(): _sha256(path) for path in source_files
            }
            if not isinstance(source_manifest_digest, str):
                raise ContractError("workspace-archive source manifest digest must be a string")
            if source_manifest_digest and _manifest_digest(manifest) != source_manifest_digest:
                raise ContractError("workspace-archive source manifest digest mismatch")
            for path in source_files:
                relative = path.relative_to(source_root).as_posix()
                inputs.append(
                    InputFile(
                        str(path),
                        f"/run/axrun/static-source/{relative}",
                        _sha256(path),
                    )
                )
            setup_lines = [*remove_excluded]
            if source_mode == "empty":
                setup_lines.append(
                    f'test -z "$(find {workspace} -mindepth 1 -maxdepth 1 -print -quit)"'
                )
            setup_lines.extend(
                (
                    "mkdir -p /run/axrun/static-source",
                    f"cp -R /run/axrun/static-source/. {workspace}/",
                )
            )
            setup_script = "\n".join(setup_lines)
            script = "\n".join(
                (
                    *remove_excluded,
                    "PYTHONPATH=/opt/axrun python3 /opt/axrun/axrun/candidates/archive.py create "
                    f"{workspace} /outputs/workspace.tar",
                )
            )
        else:
            raise ContractError("workspace-archive source_directory must be a non-empty string")
        return CandidateCapturePlan(
            setup_script=setup_script,
            finalize_script=script,
            inputs=tuple(inputs),
            outputs=(
                OutputSpec(
                    "/outputs/workspace.tar",
                    media_type="application/x-tar",
                    max_bytes=64 << 20,
                ),
            ),
        )

    def build(
        self, episode: ResolvedEpisode, result: StageResult, *, destination: Path
    ) -> CandidateBundle:
        self._validate(episode)
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_outputs=(("workspace", "/outputs/workspace.tar"),),
            harness=episode.harness.identity,
            harness_version=episode.harness.version,
        )

    def _validate(self, episode: ResolvedEpisode) -> None:
        if episode.candidate.identity != self.name or episode.candidate.version != self.version:
            raise ContractError("workspace archive candidate adapter requires workspace-archive@1")
        unknown = set(episode.candidate.config) - {
            "source_directory",
            "source_manifest_digest",
            "source_mode",
            "exclude_paths",
        }
        if unknown:
            raise ContractError(f"unknown workspace-archive config: {', '.join(sorted(unknown))}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_digest(value: dict[str, str]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _excluded_paths(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractError("workspace-archive exclude_paths must be an array")
    paths: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str):
            raise ContractError("workspace-archive exclude_paths must contain strings")
        relative = Path(item)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) != 1
            or not relative.parts
            or not _TOP_LEVEL_PATH.fullmatch(item)
        ):
            raise ContractError("workspace-archive exclude_paths must be safe top-level paths")
        paths.append(relative.as_posix())
    if len(paths) != len(set(paths)):
        raise ContractError("workspace-archive exclude_paths contains duplicates")
    return tuple(sorted(paths))
