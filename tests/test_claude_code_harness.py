from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from axrun.candidates import GitPatchCandidateAdapter, WorkspaceArchiveCandidateAdapter
from axrun.datasets import SyntheticCodeTaskResolver
from axrun.errors import ContractError
from axrun.harnesses import ClaudeCodeHarness
from axrun.models import (
    Artifact,
    CandidateSpec,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageResult,
    TaskSpec,
)


def _episode() -> ResolvedEpisode:
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "code-task-v1"
    raw: object = json.loads((fixture / "row.json").read_text())
    assert isinstance(raw, dict)
    return SyntheticCodeTaskResolver().resolve(
        cast(dict[str, Any], raw),
        source_dir=fixture,
        episode_id="synthetic-claude",
        inference_environment_id="env-inference",
        verification_environment_id="env-verification",
        task_image=f"registry.invalid/task@sha256:{'f' * 64}",
        task_platform="linux/amd64",
        harness=HarnessSpec(
            identity="claude-code",
            version="2.1.205",
            config={
                "mount_image": f"registry.invalid/axrun/claude@sha256:{'a' * 64}",
                "model": "test-model[1m]",
                "default_haiku_model": "test-model",
                "subagent_model": "test-model",
                "effort_level": "max",
                "auto_compact_window": 786432,
                "max_turns": 7,
            },
        ),
    )


def test_claude_harness_uses_fixed_mount_tunnel_and_output_contract(tmp_path: Path) -> None:
    episode = _episode()
    assert episode.harness.config["default_opus_model"] == "test-model[1m]"
    assert episode.harness.config["default_sonnet_model"] == "test-model[1m]"
    assert episode.harness.config["default_haiku_model"] == "test-model"
    assert episode.harness.config["subagent_model"] == "test-model"
    assert episode.harness.config["disallowed_tools"] == ["WebFetch", "WebSearch"]
    plan = ClaudeCodeHarness().plan(episode, GitPatchCandidateAdapter().capture_plan(episode))
    assert plan.image_mounts[0].target == "/__claude_code"
    assert plan.image_mounts[0].image.endswith(f"@sha256:{'a' * 64}")
    assert "control_python=/usr/bin/python3; else control_python=python3" in plan.argv[2]
    assert 'PYTHONPATH=/opt/axrun "$control_python"' in plan.argv[2]
    assert "/opt/axrun/axrun/fixtures/claude/runtime_supervisor.py" in plan.argv[2]
    assert "--progress /run/axrun/progress.json" in plan.argv[2]
    assert "--native /run/axrun/claude-raw.jsonl" in plan.argv[2]
    assert 'exit "$agent_rc"' in plan.argv[2]
    assert plan.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8765"
    assert "ANTHROPIC_API_KEY" not in plan.env
    assert plan.env["ANTHROPIC_AUTH_TOKEN"] == "axrun-local-tunnel"
    assert plan.env["ANTHROPIC_MODEL"] == "test-model[1m]"
    assert plan.env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "test-model[1m]"
    assert plan.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "test-model[1m]"
    assert plan.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "test-model"
    assert plan.env["CLAUDE_CODE_SUBAGENT_MODEL"] == "test-model"
    assert plan.env["CLAUDE_CODE_EFFORT_LEVEL"] == "max"
    assert plan.env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "786432"
    assert "DEEPSEEK_API_KEY" not in repr(plan)
    assert plan.network_policy == "deny_all"
    assert "credential-must-stay-in-memory" not in repr(plan)
    assert "/__claude_code/usr/local/bin/claude" in plan.argv[-1]
    assert "--disallowedTools WebFetch WebSearch" in plan.argv[-1]
    assert [item.path for item in plan.outputs] == [
        "/outputs/candidate.patch",
        "/outputs/trajectory.jsonl",
        "/outputs/harness.log",
        "/outputs/usage.json",
    ]
    assert "/run/axrun/progress.json" not in [item.path for item in plan.outputs]
    assert "/run/axrun/claude-raw.jsonl" not in [item.path for item in plan.outputs]
    assert any(item.target == "/opt/axrun/axrun/errors.py" for item in plan.inputs)
    artifacts = []
    for index, output in enumerate(plan.outputs):
        path = tmp_path / str(index)
        payload = b"{}\n" if output.path.endswith((".json", ".jsonl")) else b"content"
        path.write_bytes(payload)
        artifacts.append(
            Artifact(
                output.path,
                str(path),
                len(payload),
                hashlib.sha256(payload).hexdigest(),
                output.media_type,
            )
        )
    bundle = GitPatchCandidateAdapter().build(
        episode,
        StageResult(
            ExecutionRef("env-inference", "run-claude", "alloc-claude"), 0, "", tuple(artifacts)
        ),
        destination=tmp_path / "candidates",
    )
    assert bundle.harness == "claude-code" and len(bundle.files) == 1
    assert bundle.files[0].declared_path == "/outputs/candidate.patch"


def test_claude_harness_composes_workspace_archive_without_candidate_semantics() -> None:
    episode = replace(
        _episode(),
        task=TaskSpec("axrun.synthetic.greenfield-task", "1"),
        candidate=CandidateSpec("workspace-archive", "1"),
    )
    capture = WorkspaceArchiveCandidateAdapter().capture_plan(episode)
    plan = ClaudeCodeHarness().plan(episode, capture)
    script = plan.argv[-1]
    assert "git " not in script and "candidate.patch" not in script
    assert "/outputs/workspace.tar" in [output.path for output in plan.outputs]
    assert "archive.py create /workspace /outputs/workspace.tar" in script
    assert "PYTHONPATH=/opt/axrun" in script


def test_claude_model_alias_defaults_are_materialized_in_resolved_episode() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "code-task-v1"
    raw: object = json.loads((fixture / "row.json").read_text())
    assert isinstance(raw, dict)
    episode = SyntheticCodeTaskResolver().resolve(
        cast(dict[str, Any], raw),
        source_dir=fixture,
        episode_id="synthetic-claude-default-models",
        inference_environment_id="env-inference",
        verification_environment_id="env-verification",
        task_image=f"registry.invalid/task@sha256:{'f' * 64}",
        task_platform="linux/amd64",
        harness=HarnessSpec(
            identity="claude-code",
            version="2.1.205",
            config={
                "mount_image": f"registry.invalid/axrun/claude@sha256:{'a' * 64}",
                "model": "opaque-model-id",
            },
        ),
    )

    assert episode.harness.config == {
        "mount_image": f"registry.invalid/axrun/claude@sha256:{'a' * 64}",
        "model": "opaque-model-id",
        "default_opus_model": "opaque-model-id",
        "default_sonnet_model": "opaque-model-id",
        "default_haiku_model": "opaque-model-id",
        "subagent_model": "opaque-model-id",
        "max_turns": 40,
        "working_directory": "/workspace",
        "disallowed_tools": ["WebFetch", "WebSearch"],
    }
    plan = ClaudeCodeHarness().plan(episode, GitPatchCandidateAdapter().capture_plan(episode))
    assert {
        plan.env["ANTHROPIC_MODEL"],
        plan.env["ANTHROPIC_DEFAULT_OPUS_MODEL"],
        plan.env["ANTHROPIC_DEFAULT_SONNET_MODEL"],
        plan.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"],
        plan.env["CLAUDE_CODE_SUBAGENT_MODEL"],
    } == {"opaque-model-id"}


def test_claude_disallowed_tools_are_explicit_deterministic_and_may_be_empty() -> None:
    episode = _episode()
    config = dict(episode.harness.config, disallowed_tools=["WebSearch", "WebFetch"])
    resolved = replace(
        episode,
        harness=HarnessSpec("claude-code", "2.1.205", config=config),
    )
    capture = GitPatchCandidateAdapter().capture_plan(resolved)
    assert (
        "--disallowedTools WebFetch WebSearch"
        in ClaudeCodeHarness().plan(resolved, capture).argv[-1]
    )

    enabled = replace(
        episode,
        harness=HarnessSpec(
            "claude-code", "2.1.205", config=dict(episode.harness.config, disallowed_tools=[])
        ),
    )
    capture = GitPatchCandidateAdapter().capture_plan(enabled)
    assert "--disallowedTools" not in ClaudeCodeHarness().plan(enabled, capture).argv[-1]


@pytest.mark.parametrize("value", [["WebSearch", "WebSearch"], ["bad tool"], "WebSearch"])
def test_claude_disallowed_tools_fail_closed(value: object) -> None:
    episode = _episode()
    config = dict(episode.harness.config, disallowed_tools=value)
    invalid = replace(episode, harness=HarnessSpec("claude-code", "2.1.205", config=config))
    with pytest.raises(ContractError, match="disallowed_tools"):
        ClaudeCodeHarness().plan(invalid, GitPatchCandidateAdapter().capture_plan(invalid))


def test_claude_working_directory_is_explicit_and_must_be_absolute() -> None:
    episode = _episode()
    config = dict(episode.harness.config, working_directory="/testbed")
    benchmark_episode = replace(
        episode,
        harness=HarnessSpec("claude-code", "2.1.205", config=config),
        inference_environment=replace(episode.inference_environment, working_directory="/testbed"),
    )
    assert (
        ClaudeCodeHarness()
        .plan(benchmark_episode, GitPatchCandidateAdapter().capture_plan(benchmark_episode))
        .cwd
        == "/testbed"
    )
