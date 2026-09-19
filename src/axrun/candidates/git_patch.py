"""Git patch candidate capture independent from the producing harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from axrun.adapters._candidate import persist_candidate
from axrun.adapters._git import canonical_patch_export
from axrun.errors import ContractError
from axrun.models import (
    CandidateBundle,
    CandidateCapturePlan,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StageResult,
    task_config_string,
)


@dataclass(frozen=True, slots=True)
class GitPatchCandidateAdapter:
    version: str = "1"
    name: str = "git-patch"

    def capture_plan(self, episode: ResolvedEpisode) -> CandidateCapturePlan:
        if episode.candidate.identity != self.name or episode.candidate.version != self.version:
            raise ContractError("Git patch candidate adapter requires git-patch@1")
        base_commit = task_config_string(episode, "base_commit")
        source = episode.candidate.config.get("source_file")
        inputs: tuple[InputFile, ...] = ()
        if source is None:
            setup_script = "\n".join(
                (
                    f'test "$(git rev-parse HEAD)" = "{base_commit}"',
                    'test -z "$(git status --porcelain --untracked-files=all)"',
                )
            )
            finalize_script = "\n".join(
                (
                    canonical_patch_export(base_commit, "/outputs/candidate.patch"),
                    'test "$patch_rc" -eq 0',
                )
            )
        elif isinstance(source, str) and source:
            inputs = (InputFile(source, "/run/axrun/static-candidate.patch"),)
            setup_script = ""
            finalize_script = "cp /run/axrun/static-candidate.patch /outputs/candidate.patch"
        else:
            raise ContractError("git-patch source_file must be a non-empty string")
        return CandidateCapturePlan(
            setup_script=setup_script,
            finalize_script=finalize_script,
            inputs=inputs,
            outputs=(OutputSpec("/outputs/candidate.patch", media_type="text/x-diff"),),
        )

    def build(
        self,
        episode: ResolvedEpisode,
        result: StageResult,
        *,
        destination: Path,
    ) -> CandidateBundle:
        if episode.candidate.identity != self.name or episode.candidate.version != self.version:
            raise ContractError("Git patch candidate adapter requires git-patch@1")
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_outputs=(("patch", "/outputs/candidate.patch"),),
            harness=episode.harness.identity,
            harness_version=episode.harness.version,
        )
