"""Official mini-swe-agent conformance adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from axrun.adapters._candidate import persist_candidate
from axrun.adapters._git import canonical_patch_export
from axrun.models import (
    CandidateBundle,
    InputFile,
    OutputFormat,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    StageResult,
)

_PATCH = "/outputs/candidate.patch"
_TRAJECTORY = "/outputs/trajectory.json"
_LOG = "/outputs/mini-swe-agent.log"


@dataclass(frozen=True, slots=True)
class MiniSweAgentAdapter:
    command: tuple[str, ...] = ("mini",)
    version: str = "2.4.6"
    timeout_seconds: int = 7200
    name: str = "mini-swe-agent"

    def plan(self, episode: ResolvedEpisode) -> StagePlan:
        # The official CLI owns its agent loop. The image contract writes its
        # trajectory and the wrapper exports a complete Git delta afterwards.
        quoted = " ".join(__import__("shlex").quote(value) for value in self.command)
        script = "\n".join(
            (
                "set +e",
                "mkdir -p /outputs",
                f'{quoted} -y -t "$(cat /inputs/prompt.txt)" -o {_TRAJECTORY} > {_LOG} 2>&1',
                "agent_rc=$?",
                canonical_patch_export(episode.base_commit, _PATCH),
                'test "$patch_rc" -eq 0 || exit 125',
                'exit "$agent_rc"',
            )
        )
        return StagePlan(
            environment_id=episode.inference_environment_id,
            argv=("/bin/sh", "-lc", script),
            cwd="/workspace",
            inputs=(InputFile(episode.prompt_file, "/inputs/prompt.txt"),),
            outputs=(
                OutputSpec(_PATCH, OutputFormat.FILE, "text/x-diff"),
                OutputSpec(_TRAJECTORY, OutputFormat.FILE, "application/json"),
                OutputSpec(_LOG, OutputFormat.FILE, "text/plain"),
            ),
            resources=episode.inference_resources,
            timeout_seconds=self.timeout_seconds,
            labels={"axrun.stage": "inference", "axrun.agent": self.name},
        )

    def build_candidate(
        self, episode: ResolvedEpisode, result: StageResult, *, destination: Path
    ) -> CandidateBundle:
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_paths=(_PATCH, _TRAJECTORY, _LOG),
            harness=self.name,
            harness_version=self.version,
        )
