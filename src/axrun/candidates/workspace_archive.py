"""Whole-workspace candidate capture."""

from __future__ import annotations

import hashlib
import shlex
from dataclasses import dataclass
from pathlib import Path

from axrun.adapters._candidate import persist_candidate
from axrun.errors import ContractError
from axrun.models import (
    CandidateBundle,
    CandidateCapturePlan,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StageResult,
)


@dataclass(frozen=True, slots=True)
class WorkspaceArchiveCandidateAdapter:
    version: str = "1"
    name: str = "workspace-archive"

    def capture_plan(self, episode: ResolvedEpisode) -> CandidateCapturePlan:
        if episode.candidate.identity != self.name or episode.candidate.version != self.version:
            raise ContractError("workspace archive candidate adapter requires workspace-archive@1")
        module = Path(__file__).with_name("archive.py")
        source = episode.candidate.config.get("source_directory")
        inputs = [InputFile(str(module), "/opt/axrun/candidates/archive.py")]
        setup_script = ""
        if source is None:
            script = (
                "python3 /opt/axrun/candidates/archive.py create "
                f"{episode.inference_environment.working_directory} /outputs/workspace.tar"
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
            for path in source_files:
                relative = path.relative_to(source_root).as_posix()
                inputs.append(
                    InputFile(
                        str(path),
                        f"/run/axrun/static-source/{relative}",
                        _sha256(path),
                    )
                )
            workspace = shlex.quote(episode.inference_environment.working_directory)
            setup_script = "\n".join(
                (
                    f'test -z "$(find {workspace} -mindepth 1 -maxdepth 1 -print -quit)"',
                    "mkdir -p /run/axrun/static-source",
                    f"cp -R /run/axrun/static-source/. {workspace}/",
                )
            )
            script = (
                "python3 /opt/axrun/candidates/archive.py create "
                f"{workspace} /outputs/workspace.tar"
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
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_outputs=(("workspace", "/outputs/workspace.tar"),),
            harness=episode.harness.identity,
            harness_version=episode.harness.version,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
