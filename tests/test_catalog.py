from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from axrun.adapters import StaticCandidateHarness
from axrun.candidates import GitPatchCandidateAdapter
from axrun.catalog import (
    resolve_adapters,
    resolve_model_protocol,
    resolve_qualification_requirements,
)
from axrun.errors import ContractError
from axrun.harnesses import ClaudeCodeHarness
from axrun.models import (
    CandidateSpec,
    EnvironmentBinding,
    HarnessSpec,
    ResolvedEpisode,
    TaskSpec,
    VerifierSpec,
)


def _episode(tmp_path: Path) -> ResolvedEpisode:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("build it", encoding="utf-8")
    binding = EnvironmentBinding(
        "env", f"example.invalid/task@sha256:{'a' * 64}", "linux/amd64", "/workspace"
    )
    return ResolvedEpisode(
        1,
        "catalog",
        "task",
        "b" * 64,
        str(prompt),
        TaskSpec("git-worktree", "1", {"base_commit": "c" * 40}),
        binding,
        replace(binding, environment_id="env-v"),
        HarnessSpec("static-candidate", "1"),
        CandidateSpec("git-patch", "1"),
        VerifierSpec("command-verifier", "1"),
    )


def test_static_catalog_resolution_is_deterministic_and_model_free(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    first = resolve_adapters(episode)
    second = resolve_adapters(episode)
    assert isinstance(first.inference, StaticCandidateHarness)
    assert isinstance(first.candidate, GitPatchCandidateAdapter)
    assert first.runtime == second.runtime
    assert first.trajectory is None
    assert resolve_model_protocol(first.runtime) is None


def test_claude_requirements_select_protocol_without_candidate_branch(tmp_path: Path) -> None:
    episode = replace(
        _episode(tmp_path),
        harness=HarnessSpec("claude-code", "2.1.205"),
        candidate=CandidateSpec("workspace-archive", "1"),
    )
    selected = resolve_adapters(episode)
    assert isinstance(selected.inference, ClaudeCodeHarness)
    assert selected.runtime.model_protocol == "anthropic-compatible"
    assert selected.runtime.requires_model_tunnel is True
    assert selected.trajectory is not None
    assert resolve_model_protocol(selected.runtime).name == "anthropic"


def test_greenfield_qualification_is_no_git_and_stage_specific(tmp_path: Path) -> None:
    verifier = tmp_path / "verifier.py"
    verifier.write_text("pass\n", encoding="utf-8")
    episode = replace(
        _episode(tmp_path),
        task=TaskSpec("axrun.synthetic.greenfield-task", "1"),
        candidate=CandidateSpec("workspace-archive", "1"),
        verifier=VerifierSpec("synthetic-greenfield", "1", config={"verifier_file": str(verifier)}),
    )
    requirements = resolve_qualification_requirements(episode)
    assert requirements.task_mode == "empty" and requirements.base_commit == ""
    assert requirements.archive_finalizer is True
    assert requirements.verifier_file == str(verifier)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("harness", HarnessSpec("unknown", "1")),
        ("harness", HarnessSpec("claude-code", "wrong")),
        ("candidate", CandidateSpec("unknown", "1")),
        ("candidate", CandidateSpec("git-patch", "wrong")),
        ("verifier", VerifierSpec("unknown", "1")),
        ("verifier", VerifierSpec("command-verifier", "wrong")),
    ],
)
def test_catalog_unknown_identity_or_version_fails_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    with pytest.raises(ContractError, match="unsupported"):
        resolve_adapters(replace(_episode(tmp_path), **{field: value}))
