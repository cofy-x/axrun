from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from axrun.adapters import SweBenchVerifiedVerifierAdapter
from axrun.adapters._candidate import persist_candidate
from axrun.datasets import SweBenchVerifiedResolver
from axrun.errors import ContractError
from axrun.models import Artifact, ExecutionRef, HarnessSpec, StageResult

_IMAGE_REPOSITORY = "docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419"
_TASK_IMAGE = f"{_IMAGE_REPOSITORY}@sha256:{'d' * 64}"
_ARM64_TASK_IMAGE = (
    f"index.docker.io/library/axrun-swebench-verified-django-12419@sha256:{'e' * 64}"
)


def _row(eval_script: str) -> dict[str, Any]:
    return {
        "FAIL_TO_PASS": ["test_case (module.Class)"],
        "PASS_TO_PASS": [],
        "base_commit": "7fa1a93c6c8109010a6ff3f604fda83b604e0e97",
        "created_at": "2020-01-01T00:00:00Z",
        "difficulty": "<15 min fix",
        "environment_setup_commit": "c" * 40,
        "eval_script": eval_script,
        "eval_type": "pass_and_fail",
        "hints_text": "",
        "image": "swebench/sweb.eval.x86_64.django_1776_django-12419:latest",
        "instance_id": "django__django-12419",
        "log_parser": "parse_log_django",
        "patch": "GOLD-PATCH-MUST-NOT-BECOME-AN-ASSET",
        "problem_statement": "Fix the setting safely.",
        "repo": "django/django",
        "test_patch": "TEST-PATCH-MUST-NOT-BECOME-AN-ASSET",
        "version": "3.1",
    }


def _harness() -> HarnessSpec:
    return HarnessSpec(
        "claude-code",
        "2.1.205",
        config={
            "mount_image": f"registry.invalid/claude@sha256:{'a' * 64}",
            "model": "opaque-model",
            "working_directory": "/testbed",
        },
    )


def _resolve(tmp_path: Path, row: dict[str, Any] | None = None):
    return SweBenchVerifiedResolver().resolve(
        row or _row("#!/bin/bash\necho offline\n"),
        asset_dir=tmp_path / "assets",
        episode_id="swebench-one",
        inference_environment_id="env-i",
        verification_environment_id="env-v",
        task_image=_TASK_IMAGE,
        harness=_harness(),
    )


def test_resolver_parses_exact_schema_once_and_materializes_stable_assets(
    tmp_path: Path,
) -> None:
    row = _row("#!/bin/bash\necho offline\n")
    first = _resolve(tmp_path, row)
    second = SweBenchVerifiedResolver().resolve(
        dict(row),
        asset_dir=tmp_path / "assets",
        episode_id="other-episode",
        inference_environment_id="other-i",
        verification_environment_id="other-v",
        task_image=_TASK_IMAGE,
        harness=_harness(),
    )
    assert first.seed_digest == second.seed_digest
    assert first.harness.config["working_directory"] == "/testbed"
    assert first.metadata["task_image"].endswith(f"@sha256:{'d' * 64}")
    assert first.metadata["task_platform"] == "linux/amd64"
    assert Path(first.prompt_file).read_text() == row["problem_statement"]
    assert Path(first.verifier.config["eval_script_file"]).read_text() == row["eval_script"]
    serialized = json.dumps(asdict(first), sort_keys=True)
    assert row["patch"] not in serialized and row["test_patch"] not in serialized

    with pytest.raises(ContractError, match="unknown"):
        _resolve(tmp_path / "unknown", dict(row, guessed_field=True))
    incomplete = dict(row)
    del incomplete["created_at"]
    with pytest.raises(ContractError, match="missing"):
        _resolve(tmp_path / "missing", incomplete)
    with pytest.raises(ContractError, match="OCI sha256"):
        SweBenchVerifiedResolver().resolve(
            row,
            asset_dir=tmp_path / "mutable",
            episode_id="mutable",
            inference_environment_id="env-i",
            verification_environment_id="env-v",
            task_image=row["image"],
            harness=_harness(),
        )
    with pytest.raises(ContractError, match="requires instance_id"):
        _resolve(tmp_path / "other", dict(row, instance_id="django__django-other"))


def test_resolver_requires_explicit_platform_specific_task_image(tmp_path: Path) -> None:
    row = _row("#!/bin/bash\necho offline\n")
    episode = SweBenchVerifiedResolver().resolve(
        row,
        asset_dir=tmp_path / "assets",
        episode_id="arm64-local",
        inference_environment_id="env-i",
        verification_environment_id="env-v",
        task_image=_ARM64_TASK_IMAGE,
        task_platform="linux/arm64",
        harness=_harness(),
    )
    assert episode.metadata["task_platform"] == "linux/arm64"
    assert episode.metadata["official_image"] == row["image"]
    with pytest.raises(ContractError, match="linux/amd64 image contract"):
        SweBenchVerifiedResolver().resolve(
            row,
            asset_dir=tmp_path / "wrong-assets",
            episode_id="wrong-platform",
            inference_environment_id="env-i",
            verification_environment_id="env-v",
            task_image=_ARM64_TASK_IMAGE,
            harness=_harness(),
        )


def _candidate(tmp_path: Path, episode, payload: bytes = b""):
    source = tmp_path / "candidate.patch"
    source.write_bytes(payload)
    artifact = Artifact(
        "/outputs/candidate.patch",
        str(source),
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        "text/x-diff",
    )
    return persist_candidate(
        episode,
        StageResult(ExecutionRef("env-i", "run-i", "alloc-i"), 0, "", (artifact,)),
        destination=tmp_path / "bundles",
        required_outputs=(("patch", artifact.name),),
        harness="claude-code",
        harness_version="2.1.205",
    )


def test_verifier_plan_is_fresh_offline_and_receives_only_owned_inputs(tmp_path: Path) -> None:
    episode = _resolve(tmp_path)
    candidate = _candidate(tmp_path, episode)
    plan = SweBenchVerifiedVerifierAdapter().plan(episode, candidate)
    assert plan.cwd == "/testbed" and plan.network_policy == "deny_all"
    assert plan.env == {} and plan.secret_env == () and plan.image_mounts == ()
    assert {item.target for item in plan.inputs} == {
        "/inputs/candidate.patch",
        "/opt/axrun-swebench/run_verifier.py",
        "/opt/axrun-swebench/eval.sh",
    }
    assert candidate.digest in plan.argv

    invalid = replace(
        episode,
        verifier=replace(
            episode.verifier,
            config={**episode.verifier.config, "log_parser": "parse_log_unknown"},
        ),
    )
    with pytest.raises(ContractError, match="parse_log_django"):
        SweBenchVerifiedVerifierAdapter().plan(invalid, candidate)


def _git_workspace(path: Path) -> str:
    path.mkdir()
    (path / "setting.txt").write_text("unsafe\n")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "add", "setting.txt"], cwd=path, check=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Axrun",
        "GIT_AUTHOR_EMAIL": "axrun@example.invalid",
        "GIT_COMMITTER_NAME": "Axrun",
        "GIT_COMMITTER_EMAIL": "axrun@example.invalid",
    }
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=path, env=env, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()


@pytest.mark.parametrize(("fixed", "resolved"), [(True, True), (False, False)])
def test_packaged_verifier_returns_business_verdict_for_patch_and_empty_candidate(
    tmp_path: Path, fixed: bool, resolved: bool
) -> None:
    workspace = tmp_path / "workspace"
    base_commit = _git_workspace(workspace)
    candidate = tmp_path / "candidate.patch"
    if fixed:
        (workspace / "setting.txt").write_text("safe\n")
        candidate.write_bytes(
            subprocess.check_output(["git", "diff", "--binary", base_commit], cwd=workspace)
        )
        subprocess.run(["git", "checkout", "--", "setting.txt"], cwd=workspace, check=True)
    else:
        candidate.write_bytes(b"")
    eval_script = tmp_path / "eval.sh"
    eval_script.write_text(
        "#!/bin/bash\n"
        "echo '>>>>> Start Test Output'\n"
        "if grep -q '^safe$' setting.txt; then\n"
        "  echo 'test_case (module.Class) ... ok'\n"
        "else\n"
        "  echo 'test_case (module.Class) ... FAIL'\n"
        "fi\n"
        "echo '>>>>> End Test Output'\n"
    )
    result = tmp_path / "verification.json"
    log = tmp_path / "verifier.log"
    runner = (
        Path(__file__).parents[1]
        / "src"
        / "axrun"
        / "fixtures"
        / "swebench_verified"
        / "run_verifier.py"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--workspace",
            str(workspace),
            "--base-commit",
            base_commit,
            "--candidate",
            str(candidate),
            "--candidate-digest",
            "e" * 64,
            "--eval-script",
            str(eval_script),
            "--log-parser",
            "parse_log_django",
            "--fail-to-pass",
            '["test_case (module.Class)"]',
            "--pass-to-pass",
            "[]",
            "--result",
            str(result),
            "--log",
            str(log),
        ],
        check=False,
    )
    assert completed.returncode == 0
    payload = json.loads(result.read_text())
    assert payload["resolved"] is resolved
    assert payload["candidate_digest"] == "e" * 64
