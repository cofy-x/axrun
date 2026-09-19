from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from axrun.adapters import StaticCandidateHarness, SyntheticVerifierAdapter
from axrun.adapters._candidate import load_candidate
from axrun.candidates import GitPatchCandidateAdapter
from axrun.datasets import SyntheticCodeTaskResolver
from axrun.errors import ContractError
from axrun.models import Artifact, ExecutionRef, HarnessSpec, StagePlan, StageResult
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore


class SyntheticVerticalBackend:
    """Test transport that executes the real synthetic verifier in fresh directories."""

    def __init__(self) -> None:
        self.executions: list[ExecutionRef] = []
        self.plans: list[StagePlan] = []

    def execute(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
        lifecycle=None,
    ) -> StageResult:
        index = len(self.executions) + 1
        execution = ExecutionRef(plan.environment_id, f"run-{index}", f"allocation-{index}")
        self.executions.append(execution)
        self.plans.append(plan)
        on_bound(execution)
        if lifecycle is not None:
            lifecycle.start(execution, object())
        if plan.labels.get("axrun.stage") == "inference":
            result = self._inference(plan, artifact_dir, execution)
        else:
            result = self._verification(plan, artifact_dir, execution)
        if lifecycle is not None:
            lifecycle.close()
        return result

    def recover(
        self, execution: ExecutionRef, plan: StagePlan, *, artifact_dir: Path
    ) -> StageResult | None:
        if plan.labels.get("axrun.stage") == "inference":
            return self._inference(plan, artifact_dir, execution)
        return self._verification(plan, artifact_dir, execution)

    def cancel(self, execution: ExecutionRef) -> None:
        return None

    def wait(self, execution: ExecutionRef, *, timeout: float | None = None) -> None:
        return None

    @staticmethod
    def _inference(plan: StagePlan, artifact_dir: Path, execution: ExecutionRef) -> StageResult:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        payload = Path(plan.inputs[0].source).read_bytes()
        output = artifact_dir / "candidate.patch"
        output.write_bytes(payload)
        artifact = Artifact(
            plan.outputs[0].path,
            str(output),
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            plan.outputs[0].media_type,
        )
        return StageResult(execution, 0, "", (artifact,))

    @staticmethod
    def _verification(plan: StagePlan, artifact_dir: Path, execution: ExecutionRef) -> StageResult:
        assert plan.network_policy == "deny_all"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        workspace = artifact_dir / "fresh-workspace"
        fixture_repository = (
            Path(__file__).parents[1] / "fixtures" / "synthetic" / "code-task-v1" / "repository"
        )
        shutil.copytree(fixture_repository, workspace)
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        subprocess.run(["git", "add", "-A", "--", "."], cwd=workspace, check=True)
        commit_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Axrun Synthetic",
            "GIT_AUTHOR_EMAIL": "synthetic@axrun.invalid",
            "GIT_COMMITTER_NAME": "Axrun Synthetic",
            "GIT_COMMITTER_EMAIL": "synthetic@axrun.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        }
        subprocess.run(
            ["git", "commit", "-q", "-m", "synthetic base"],
            cwd=workspace,
            env=commit_env,
            check=True,
        )
        candidate: Path | None = None
        runner: Path | None = None
        for item in plan.inputs:
            if item.target == "/inputs/candidate.patch":
                candidate = Path(item.source)
            elif item.target == "/opt/axrun-synthetic/run_verifier.py":
                runner = Path(item.source)
        assert candidate is not None and runner is not None
        argv = list(plan.argv)
        base_commit = argv[argv.index("--base-commit") + 1]
        candidate_digest = argv[argv.index("--candidate-digest") + 1]
        result_path = artifact_dir / "verification.json"
        log_path = artifact_dir / "verifier.log"
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
                candidate_digest,
                "--result",
                str(result_path),
                "--log",
                str(log_path),
            ],
            check=False,
            timeout=90,
        )
        artifacts = ()
        if completed.returncode == 0:
            artifacts = tuple(
                _artifact(spec.path, path, spec.media_type)
                for spec, path in zip(plan.outputs, (result_path, log_path), strict=True)
            )
        return StageResult(
            execution,
            completed.returncode,
            "" if completed.returncode == 0 else "SYNTHETIC_VERIFIER_INFRASTRUCTURE",
            artifacts,
        )


def _artifact(name: str, path: Path, media_type: str) -> Artifact:
    payload = path.read_bytes()
    return Artifact(
        name,
        str(path),
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        media_type,
    )


def _row(fixture: Path) -> dict[str, Any]:
    value: object = json.loads((fixture / "row.json").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _static_harness(candidate_file: str) -> HarnessSpec:
    return HarnessSpec(
        identity="static-candidate", version="1", config={"candidate_file": candidate_file}
    )


@pytest.mark.parametrize(
    ("candidate_file", "expected_verdict", "expected_score"),
    [
        ("gold.patch", "passed", 1.0),
        ("empty.patch", "failed", 0.0),
        ("known-bad.patch", "failed", 0.0),
    ],
)
def test_synthetic_gold_and_bad_patch_complete_fresh_two_stage_vertical(
    tmp_path: Path,
    candidate_file: str,
    expected_verdict: str,
    expected_score: float,
) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "code-task-v1"
    resolver = SyntheticCodeTaskResolver()
    episode = resolver.resolve(
        _row(fixture),
        source_dir=fixture,
        episode_id=f"synthetic-{candidate_file.removesuffix('.patch')}",
        inference_environment_id="synthetic-inference",
        verification_environment_id="synthetic-verification",
        task_image=f"registry.invalid/task@sha256:{'f' * 64}",
        task_platform="linux/amd64",
        harness=_static_harness(candidate_file),
    )
    backend = SyntheticVerticalBackend()
    store = EpisodeStore(tmp_path / "state")
    runner = EpisodeRunner(backend=backend, store=store)
    result = runner.run(
        episode,
        inference=StaticCandidateHarness(),
        candidate=GitPatchCandidateAdapter(),
        verifier=SyntheticVerifierAdapter(),
    )
    record = runner.inspect(episode.episode_id)
    assert result.verdict == expected_verdict and result.score == expected_score
    assert record.inference is not None and record.verification is not None
    assert record.inference.run_id != record.verification.run_id
    assert record.inference.allocation_id != record.verification.allocation_id
    bundle = load_candidate(Path(record.candidate_manifest))
    assert bundle.seed_digest == episode.seed_digest
    verification_plan = backend.plans[1]
    assert verification_plan.secret_env == () and verification_plan.image_mounts == ()
    assert all("/inference/" not in item.source for item in verification_plan.inputs)
    assert all(not item.target.startswith("/workspace/") for item in verification_plan.inputs)


def test_synthetic_resolver_parses_one_explicit_schema_and_stabilizes_seed_digest(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "code-task-v1"
    resolver = SyntheticCodeTaskResolver()
    row = _row(fixture)
    first = resolver.resolve(
        row,
        source_dir=fixture,
        episode_id="gold",
        inference_environment_id="env-i",
        verification_environment_id="env-v",
        task_image=f"registry.invalid/task@sha256:{'f' * 64}",
        task_platform="linux/amd64",
        harness=_static_harness("gold.patch"),
    )
    second = resolver.resolve(
        row,
        source_dir=fixture,
        episode_id="bad",
        inference_environment_id="other-i",
        verification_environment_id="other-v",
        task_image=f"registry.invalid/task@sha256:{'f' * 64}",
        task_platform="linux/amd64",
        harness=_static_harness("known-bad.patch"),
    )
    assert first.seed_digest == second.seed_digest
    assert first.harness.config == second.harness.config == {}
    assert first.candidate.config != second.candidate.config
    invalid = dict(row, benchmark="guessed-from-shape")
    with pytest.raises(ContractError, match="unknown"):
        resolver.resolve(
            invalid,
            source_dir=fixture,
            episode_id="invalid",
            inference_environment_id="env-i",
            verification_environment_id="env-v",
            task_image=f"registry.invalid/task@sha256:{'f' * 64}",
            task_platform="linux/amd64",
            harness=_static_harness("gold.patch"),
        )
    tampered = json.loads(json.dumps(row))
    task_image = cast(dict[str, Any], tampered["task_image"])
    cast(dict[str, Any], cast(list[object], task_image["sources"])[0])["sha256"] = "0" * 64
    with pytest.raises(ContractError, match="digest mismatch"):
        resolver.resolve(
            cast(dict[str, Any], tampered),
            source_dir=fixture,
            episode_id="tampered",
            inference_environment_id="env-i",
            verification_environment_id="env-v",
            task_image=f"registry.invalid/task@sha256:{'f' * 64}",
            task_platform="linux/amd64",
            harness=_static_harness("gold.patch"),
        )
