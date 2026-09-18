from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from axrun.datasets import SyntheticCodeTaskResolver
from axrun.harnesses import ClaudeCodeHarness
from axrun.models import Artifact, ExecutionRef, HarnessSpec, ResolvedEpisode, StageResult


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
    plan = ClaudeCodeHarness().plan(episode)
    assert plan.image_mounts[0].target == "/__claude_code"
    assert plan.image_mounts[0].image.endswith(f"@sha256:{'a' * 64}")
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
    assert [item.path for item in plan.outputs] == [
        "/outputs/candidate.patch",
        "/outputs/trajectory.jsonl",
        "/outputs/harness.log",
        "/outputs/usage.json",
    ]
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
    bundle = ClaudeCodeHarness().build_candidate(
        episode,
        StageResult(
            ExecutionRef("env-inference", "run-claude", "alloc-claude"), 0, "", tuple(artifacts)
        ),
        destination=tmp_path / "candidates",
    )
    assert bundle.harness == "claude-code" and len(bundle.files) == 4


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
    }
    plan = ClaudeCodeHarness().plan(episode)
    assert {
        plan.env["ANTHROPIC_MODEL"],
        plan.env["ANTHROPIC_DEFAULT_OPUS_MODEL"],
        plan.env["ANTHROPIC_DEFAULT_SONNET_MODEL"],
        plan.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"],
        plan.env["CLAUDE_CODE_SUBAGENT_MODEL"],
    } == {"opaque-model-id"}


def test_claude_output_normalizer_redacts_auth_material_and_extracts_usage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "raw.jsonl"
    source.write_text(
        json.dumps(
            {
                "type": "result",
                "authorization": "Bearer secret",
                "text": "contains local-placeholder",
                "usage": {"input_tokens": 12, "output_tokens": 4},
            }
        )
        + "\n"
    )
    trajectory = tmp_path / "trajectory.jsonl"
    usage = tmp_path / "usage.json"
    script = (
        Path(__file__).parents[1] / "src" / "axrun" / "fixtures" / "claude" / "normalize_output.py"
    )
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--input",
            str(source),
            "--trajectory",
            str(trajectory),
            "--usage",
            str(usage),
            "--redact-value",
            "local-placeholder",
        ],
        check=True,
    )
    output = trajectory.read_text()
    assert "Bearer secret" not in output and "local-placeholder" not in output
    assert json.loads(output)["usage"] == {"input_tokens": 12, "output_tokens": 4}
    assert json.loads(usage.read_text()) == {
        "schema_version": 1,
        "observations": 1,
        "input_tokens": 12,
        "output_tokens": 4,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
