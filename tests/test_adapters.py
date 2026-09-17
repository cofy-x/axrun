from __future__ import annotations

from axrun.adapters import ClaudeCodeMountAdapter, MiniSweAgentAdapter
from axrun.models import ResolvedEpisode


def episode(tmp_path) -> ResolvedEpisode:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("fix it", encoding="utf-8")
    return ResolvedEpisode(1, "ep", "task", "sha256:task", "a" * 40, str(prompt), "env-i", "env-v")


def test_claude_plan_keeps_secret_out_of_command(tmp_path) -> None:
    adapter = ClaudeCodeMountAdapter("registry/claude@sha256:abc", "secret-model")
    plan = adapter.plan(episode(tmp_path))

    assert plan.image_mounts[0].target == "/__claude_code"
    assert plan.image_mounts[0].readonly is True
    assert plan.secret_env[0].secret_id == "secret-model"
    assert "secret-model" not in " ".join(plan.argv)
    assert any(output.path == "/outputs/candidate.patch" for output in plan.outputs)
    command = plan.argv[-1]
    assert "GIT_INDEX_FILE" in command
    assert "git -c core.fileMode=false add -A" in command
    assert "> /outputs/trajectory.jsonl 2> /outputs/claude-code.log" in command


def test_mini_swe_plan_has_no_runtime_mount(tmp_path) -> None:
    plan = MiniSweAgentAdapter("secret-model").plan(episode(tmp_path))

    assert plan.image_mounts == ()
    assert plan.labels["axrun.agent"] == "mini-swe-agent"
