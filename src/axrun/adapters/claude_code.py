"""Claude Code inference through a pinned, read-only OCI runtime mount."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from axrun.adapters._candidate import persist_candidate
from axrun.adapters._git import canonical_patch_export
from axrun.models import (
    CandidateBundle,
    ImageMountSpec,
    InputFile,
    OutputFormat,
    OutputSpec,
    ResolvedEpisode,
    SecretEnvSpec,
    StagePlan,
    StageResult,
)

_PATCH = "/outputs/candidate.patch"
_TRAJECTORY = "/outputs/trajectory.jsonl"
_RESULT = "/outputs/agent-result.json"
_LOG = "/outputs/claude-code.log"


@dataclass(frozen=True, slots=True)
class ClaudeCodeMountAdapter:
    runtime_image: str
    model_secret_id: str
    model_secret_key: str = "api_key"
    runtime_target: str = "/__claude_code"
    max_turns: int = 100
    timeout_seconds: int = 7200
    environment: tuple[tuple[str, str], ...] = ()
    name: str = "claude-code-mount"

    def plan(self, episode: ResolvedEpisode) -> StagePlan:
        claude = f"{self.runtime_target}/usr/local/bin/claude"
        workdir = "/workspace"
        prompt = "/inputs/prompt.txt"
        script = "\n".join(
            (
                "set +e",
                "mkdir -p /outputs /tmp/axrun-claude",
                f"export HOME={shlex.quote('/tmp/axrun-claude')}",
                "export IS_SANDBOX=1",
                "export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
                f"{shlex.quote(claude)} -p --output-format stream-json --verbose "
                f"--max-turns {self.max_turns} --dangerously-skip-permissions "
                f"< {shlex.quote(prompt)} > {_TRAJECTORY} 2> {_LOG}",
                "agent_rc=$?",
                canonical_patch_export(episode.base_commit, _PATCH),
                "printf "
                f'\'{{"agent_exit_code":%s,"patch_exit_code":%s}}\\n\' '
                f'"$agent_rc" "$patch_rc" > {_RESULT}',
                'test "$patch_rc" -eq 0 || exit 125',
                'exit "$agent_rc"',
            )
        )
        return StagePlan(
            environment_id=episode.inference_environment_id,
            argv=("/bin/sh", "-lc", script),
            cwd=workdir,
            inputs=(InputFile(source=episode.prompt_file, target=prompt),),
            outputs=(
                OutputSpec(_PATCH, OutputFormat.FILE, "text/x-diff"),
                OutputSpec(_TRAJECTORY, OutputFormat.FILE, "application/x-ndjson"),
                OutputSpec(_RESULT, OutputFormat.FILE, "application/json"),
                OutputSpec(_LOG, OutputFormat.FILE, "text/plain"),
            ),
            image_mounts=(ImageMountSpec(self.runtime_image, self.runtime_target, readonly=True),),
            secret_env=(
                SecretEnvSpec("ANTHROPIC_API_KEY", self.model_secret_id, self.model_secret_key),
            ),
            env=dict(self.environment),
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
            required_paths=(_PATCH, _TRAJECTORY, _RESULT, _LOG),
        )
