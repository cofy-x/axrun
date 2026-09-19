"""Claude Code 2.1.205 harness using the repository-owned rootfs mount ABI."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from axrun.adapters._candidate import persist_candidate
from axrun.adapters._git import canonical_patch_export
from axrun.errors import ContractError
from axrun.models import (
    CandidateBundle,
    HarnessSpec,
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
_PROGRESS = "/run/axrun/progress.json"
_DIGEST_IMAGE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_OFFLINE_DISALLOWED_TOOLS = ("WebFetch", "WebSearch")
_CONFIG_KEYS = frozenset(
    {
        "mount_image",
        "model",
        "default_opus_model",
        "default_sonnet_model",
        "default_haiku_model",
        "subagent_model",
        "effort_level",
        "auto_compact_window",
        "max_turns",
        "working_directory",
        "disallowed_tools",
    }
)
_MODEL_ALIAS_KEYS = (
    "default_opus_model",
    "default_sonnet_model",
    "default_haiku_model",
    "subagent_model",
)


def resolve_claude_code_spec(harness: HarnessSpec) -> HarnessSpec:
    """Validate and materialize the canonical Claude Code harness configuration."""
    if harness.identity != "claude-code" or harness.version != _VERSION:
        raise ContractError(f"Claude Code adapter requires claude-code@{_VERSION}")
    config = dict(harness.config)
    unknown = set(config) - _CONFIG_KEYS
    if unknown:
        raise ContractError(f"unknown Claude Code config: {', '.join(sorted(unknown))}")
    image = _required_string(config, "mount_image")
    if not _DIGEST_IMAGE.fullmatch(image):
        raise ContractError("Claude Code mount_image must use an OCI sha256 digest")
    model = _required_string(config, "model")
    for key in _MODEL_ALIAS_KEYS:
        value = config.get(key, model)
        if not isinstance(value, str) or not value:
            raise ContractError(f"Claude Code {key} must be a non-empty string")
        config[key] = value
    max_turns = config.get("max_turns", 40)
    _validate_max_turns(max_turns)
    config["max_turns"] = max_turns
    working_directory = config.get("working_directory", "/workspace")
    if not isinstance(working_directory, str) or not working_directory.startswith("/"):
        raise ContractError("Claude Code working_directory must be an absolute path")
    config["working_directory"] = working_directory
    config["disallowed_tools"] = list(
        _validate_disallowed_tools(config.get("disallowed_tools", _OFFLINE_DISALLOWED_TOOLS))
    )
    _validate_optional_runtime_config(config)
    return HarnessSpec(
        identity=harness.identity,
        version=harness.version,
        timeout_seconds=harness.timeout_seconds,
        config=config,
    )


@dataclass(frozen=True, slots=True)
class ClaudeCodeHarness:
    version: str = _VERSION
    name: str = "claude-code"
    requires_live_model_connection: bool = True
    requires_trajectory: bool = True

    def plan(self, episode: ResolvedEpisode) -> StagePlan:
        if episode.harness.identity != self.name or episode.harness.version != self.version:
            raise ContractError(f"Claude Code adapter requires {self.name}@{self.version}")
        config = episode.harness.config
        image = _required_string(config, "mount_image")
        model = _required_string(config, "model")
        default_opus_model = _required_string(config, "default_opus_model")
        default_sonnet_model = _required_string(config, "default_sonnet_model")
        default_haiku_model = _required_string(config, "default_haiku_model")
        subagent_model = _required_string(config, "subagent_model")
        if not _DIGEST_IMAGE.fullmatch(image):
            raise ContractError("Claude Code mount_image must use an OCI sha256 digest")
        max_turns = config.get("max_turns")
        _validate_max_turns(max_turns)
        working_directory = _required_string(config, "working_directory")
        if not working_directory.startswith("/"):
            raise ContractError("Claude Code working_directory must be an absolute path")
        disallowed_tools = _validate_disallowed_tools(config.get("disallowed_tools"))
        package_root = Path(__file__).parents[1]
        runtime_init = package_root / "fixtures" / "claude" / "runtime_package_init.py"
        runtime_supervisor = package_root / "fixtures" / "claude" / "runtime_supervisor.py"
        progress_schema = package_root / "progress" / "schema.py"
        errors = package_root / "errors.py"
        trajectory_schema = package_root / "trajectories" / "schema.py"
        trajectory_policy = package_root / "trajectories" / "policy.py"
        trajectory_adapter = package_root / "trajectories" / "adapters" / "claude_code.py"
        for source in (
            runtime_init,
            runtime_supervisor,
            progress_schema,
            errors,
            trajectory_schema,
            trajectory_policy,
            trajectory_adapter,
        ):
            if not source.is_file():
                raise ContractError(f"packaged Claude trajectory runtime is missing: {source.name}")
        command_parts = [
            shlex.quote(_CLAUDE),
            "-p",
            "--output-format stream-json",
            "--verbose",
            f"--max-turns {max_turns}",
            "--dangerously-skip-permissions",
        ]
        if disallowed_tools:
            command_parts.extend(("--disallowedTools", *(shlex.quote(v) for v in disallowed_tools)))
        command = " ".join(command_parts)
        supervisor = " ".join(
            (
                "PYTHONPATH=/opt/axrun",
                '"$control_python"',
                "/opt/axrun/axrun/fixtures/claude/runtime_supervisor.py",
                "--prompt /inputs/prompt.txt",
                "--native /run/axrun/claude-raw.jsonl",
                f"--trajectory {_TRAJECTORY}",
                f"--usage {_USAGE}",
                f"--progress {_PROGRESS}",
                f"--harness-log {_LOG}",
                "--redact-value axrun-local-tunnel",
                "--",
                command,
            )
        )
        script = "\n".join(
            (
                "set -eu",
                "mkdir -p /outputs /run/axrun/claude-home",
                f'test "$(git rev-parse HEAD)" = {shlex.quote(episode.base_commit)}',
                'test -z "$(git status --porcelain --untracked-files=all)"',
                "if [ -x /usr/bin/python3 ]; then "
                "control_python=/usr/bin/python3; else control_python=python3; fi",
                "set +e",
                supervisor,
                "agent_rc=$?",
                "set -e",
                canonical_patch_export(episode.base_commit, _PATCH),
                'test "$patch_rc" -eq 0 || exit 125',
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
        _validate_optional_runtime_config(config)
        effort_level = config.get("effort_level")
        if effort_level is not None:
            env["CLAUDE_CODE_EFFORT_LEVEL"] = effort_level
        auto_compact_window = config.get("auto_compact_window")
        if auto_compact_window is not None:
            env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(auto_compact_window)
        return StagePlan(
            environment_id=episode.inference_environment_id,
            argv=("/bin/sh", "-lc", script),
            cwd=working_directory,
            inputs=(
                InputFile(episode.prompt_file, "/inputs/prompt.txt"),
                InputFile(str(runtime_init), "/opt/axrun/axrun/__init__.py"),
                InputFile(str(runtime_init), "/opt/axrun/axrun/fixtures/__init__.py"),
                InputFile(str(runtime_init), "/opt/axrun/axrun/fixtures/claude/__init__.py"),
                InputFile(str(runtime_init), "/opt/axrun/axrun/progress/__init__.py"),
                InputFile(str(runtime_init), "/opt/axrun/axrun/trajectories/__init__.py"),
                InputFile(str(runtime_init), "/opt/axrun/axrun/trajectories/adapters/__init__.py"),
                InputFile(
                    str(runtime_supervisor),
                    "/opt/axrun/axrun/fixtures/claude/runtime_supervisor.py",
                ),
                InputFile(str(progress_schema), "/opt/axrun/axrun/progress/schema.py"),
                InputFile(str(errors), "/opt/axrun/axrun/errors.py"),
                InputFile(str(trajectory_schema), "/opt/axrun/axrun/trajectories/schema.py"),
                InputFile(str(trajectory_policy), "/opt/axrun/axrun/trajectories/policy.py"),
                InputFile(
                    str(trajectory_adapter),
                    "/opt/axrun/axrun/trajectories/adapters/claude_code.py",
                ),
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
            required_paths=(_PATCH,),
            harness=self.name,
            harness_version=self.version,
        )


def _required_string(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ContractError(f"Claude Code {key} must be a non-empty string")
    return value


def _validate_max_turns(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 200:
        raise ContractError("Claude Code max_turns must be an integer from 1 to 200")


def _validate_optional_runtime_config(config: dict[str, Any]) -> None:
    effort_level = config.get("effort_level")
    if effort_level is not None and effort_level not in {"low", "medium", "high", "max"}:
        raise ContractError("Claude Code effort_level must be low, medium, high, or max")
    auto_compact_window = config.get("auto_compact_window")
    if auto_compact_window is not None and (
        not isinstance(auto_compact_window, int)
        or isinstance(auto_compact_window, bool)
        or auto_compact_window <= 0
    ):
        raise ContractError("Claude Code auto_compact_window must be a positive integer")


def _validate_disallowed_tools(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError("Claude Code disallowed_tools must be an array")
    tools: list[str] = []
    for raw_tool in cast(list[object] | tuple[object, ...], value):
        if not isinstance(raw_tool, str) or not _TOOL_NAME.fullmatch(raw_tool):
            raise ContractError("Claude Code disallowed_tools contains an invalid tool name")
        tools.append(raw_tool)
    if len(tools) != len(set(tools)):
        raise ContractError("Claude Code disallowed_tools contains duplicates")
    return tuple(sorted(tools))
