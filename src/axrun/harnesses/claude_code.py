"""Claude Code 2.1.205 harness using the repository-owned rootfs mount ABI."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axrun.adapters._candidate import persist_candidate
from axrun.adapters._git import canonical_patch_export
from axrun.errors import ContractError
from axrun.models import (
    CandidateBundle,
    ImageMountSpec,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    StageResult,
)

_VERSION = "2.1.205"
_MOUNT = "/__claude_code"
_CLAUDE = f"{_MOUNT}/usr/local/bin/claude"
_REMOTE_PORT = 8765
_PATCH = "/outputs/candidate.patch"
_TRAJECTORY = "/outputs/trajectory.jsonl"
_LOG = "/outputs/harness.log"
_USAGE = "/outputs/usage.json"
_DIGEST_IMAGE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ClaudeCodeHarness:
    version: str = _VERSION
    name: str = "claude-code"
    requires_live_model_connection: bool = True

    def plan(self, episode: ResolvedEpisode) -> StagePlan:
        if episode.harness.identity != self.name or episode.harness.version != self.version:
            raise ContractError(f"Claude Code adapter requires {self.name}@{self.version}")
        config = episode.harness.config
        image = _required_string(config, "mount_image")
        model = _required_string(config, "model")
        default_opus_model = _optional_string(config, "default_opus_model", model)
        default_sonnet_model = _optional_string(config, "default_sonnet_model", model)
        default_haiku_model = _optional_string(config, "default_haiku_model", model)
        subagent_model = _optional_string(config, "subagent_model", model)
        if not _DIGEST_IMAGE.fullmatch(image):
            raise ContractError("Claude Code mount_image must use an OCI sha256 digest")
        max_turns = config.get("max_turns", 40)
        if (
            not isinstance(max_turns, int)
            or isinstance(max_turns, bool)
            or not 1 <= max_turns <= 200
        ):
            raise ContractError("Claude Code max_turns must be an integer from 1 to 200")
        normalizer = Path(__file__).parents[1] / "fixtures" / "claude" / "normalize_output.py"
        if not normalizer.is_file():
            raise ContractError("packaged Claude output normalizer is missing")
        command = " ".join(
            (
                shlex.quote(_CLAUDE),
                "-p",
                "--output-format stream-json",
                "--verbose",
                f"--max-turns {max_turns}",
                "--dangerously-skip-permissions",
            )
        )
        script = "\n".join(
            (
                "set -eu",
                "mkdir -p /outputs /run/axrun/claude-home",
                f'test "$(git rev-parse HEAD)" = {shlex.quote(episode.base_commit)}',
                'test -z "$(git status --porcelain --untracked-files=all)"',
                "set +e",
                f"{command} < /inputs/prompt.txt > /run/axrun/claude-raw.jsonl 2> {_LOG}",
                "agent_rc=$?",
                "set -e",
                canonical_patch_export(episode.base_commit, _PATCH),
                'test "$patch_rc" -eq 0 || exit 125',
                "python3 /opt/axrun/normalize-claude-output.py \\",
                "  --input /run/axrun/claude-raw.jsonl \\",
                f"  --trajectory {_TRAJECTORY} --usage {_USAGE} \\",
                "  --redact-value axrun-local-tunnel",
                'exit "$agent_rc"',
            )
        )
        env = {
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{_REMOTE_PORT}",
            "ANTHROPIC_AUTH_TOKEN": "axrun-local-tunnel",
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": default_opus_model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": default_sonnet_model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": default_haiku_model,
            "CLAUDE_CODE_SUBAGENT_MODEL": subagent_model,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK": "1",
            "CLAUDE_CODE_MAX_RETRIES": "0",
            "HOME": "/run/axrun/claude-home",
            "IS_SANDBOX": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        effort_level = config.get("effort_level")
        if effort_level is not None:
            if effort_level not in {"low", "medium", "high", "max"}:
                raise ContractError("Claude Code effort_level must be low, medium, high, or max")
            env["CLAUDE_CODE_EFFORT_LEVEL"] = effort_level
        auto_compact_window = config.get("auto_compact_window")
        if auto_compact_window is not None:
            if (
                not isinstance(auto_compact_window, int)
                or isinstance(auto_compact_window, bool)
                or auto_compact_window <= 0
            ):
                raise ContractError("Claude Code auto_compact_window must be a positive integer")
            env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(auto_compact_window)
        return StagePlan(
            environment_id=episode.inference_environment_id,
            argv=("/bin/sh", "-lc", script),
            cwd="/workspace",
            inputs=(
                InputFile(episode.prompt_file, "/inputs/prompt.txt"),
                InputFile(str(normalizer), "/opt/axrun/normalize-claude-output.py"),
            ),
            outputs=(
                OutputSpec(_PATCH, media_type="text/x-diff", max_bytes=16 << 20),
                OutputSpec(_TRAJECTORY, media_type="application/x-ndjson", max_bytes=32 << 20),
                OutputSpec(_LOG, media_type="text/plain", max_bytes=16 << 20),
                OutputSpec(_USAGE, media_type="application/json", max_bytes=1 << 20),
            ),
            env=env,
            image_mounts=(ImageMountSpec(image=image, target=_MOUNT),),
            resources=episode.inference_resources,
            network_policy="deny_all",
            timeout_seconds=episode.harness.timeout_seconds,
            labels={"axrun.stage": "inference", "axrun.agent": self.name},
        )

    def build_candidate(
        self,
        episode: ResolvedEpisode,
        result: StageResult,
        *,
        destination: Path,
    ) -> CandidateBundle:
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_paths=(_PATCH, _TRAJECTORY, _LOG, _USAGE),
            harness=self.name,
            harness_version=self.version,
        )


def _required_string(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ContractError(f"Claude Code {key} must be a non-empty string")
    return value


def _optional_string(config: dict[str, Any], key: str, default: str) -> str:
    value = config.get(key, default)
    if not isinstance(value, str) or not value:
        raise ContractError(f"Claude Code {key} must be a non-empty string")
    return value
