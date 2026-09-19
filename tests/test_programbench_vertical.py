from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from axrun.adapters._candidate import load_candidate
from axrun.candidates.archive import create_workspace_archive, extract_workspace_archive
from axrun.catalog import resolve_adapters, resolve_qualification_requirements
from axrun.datasets import ProgramBenchCompatibilityResolver
from axrun.errors import ContractError
from axrun.models import Artifact, CandidateSpec, ExecutionRef, HarnessSpec, StagePlan, StageResult
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore
from axrun.tasks import ProgramBenchTaskAdapter


class ProgramBenchBackend:
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
        execution = ExecutionRef(
            plan.environment_id,
            f"run-{len(self.executions) + 1}",
            f"allocation-{len(self.executions) + 1}",
        )
        self.executions.append(execution)
        self.plans.append(plan)
        on_bound(execution)
        if plan.labels["axrun.stage"] == "inference":
            return self._inference(plan, artifact_dir, execution)
        return self._verification(plan, artifact_dir, execution)

    def recover(
        self, execution: ExecutionRef, plan: StagePlan, *, artifact_dir: Path
    ) -> StageResult:
        raise AssertionError("test episodes complete synchronously")

    def cancel(self, execution: ExecutionRef) -> None:
        return None

    def wait(self, execution: ExecutionRef, *, timeout: float | None = None) -> None:
        return None

    @staticmethod
    def _inference(plan: StagePlan, artifact_dir: Path, execution: ExecutionRef) -> StageResult:
        workspace = artifact_dir / "inference-workspace"
        workspace.mkdir(parents=True)
        reference = workspace / "executable"
        reference.write_text(
            "reference binary must not cross the candidate boundary", encoding="utf-8"
        )
        reference.chmod(0o111)
        prefix = "/run/axrun/static-source/"
        for item in plan.inputs:
            if item.target.startswith(prefix):
                target = workspace / item.target.removeprefix(prefix)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item.source, target)
                target.chmod(Path(item.source).stat().st_mode & 0o777)
        reference.unlink(missing_ok=True)
        output = artifact_dir / "workspace.tar"
        create_workspace_archive(workspace, output)
        return StageResult(
            execution,
            0,
            "",
            (_artifact("/outputs/workspace.tar", output, "application/x-tar"),),
        )

    @staticmethod
    def _verification(plan: StagePlan, artifact_dir: Path, execution: ExecutionRef) -> StageResult:
        assert plan.network_policy == "deny_all"
        workspace = artifact_dir / "verification-workspace"
        archive = next(item for item in plan.inputs if item.target == "/inputs/workspace.tar")
        verifier = next(
            item for item in plan.inputs if item.target == "/opt/axrun-programbench/run_verifier.py"
        )
        extract_workspace_archive(Path(archive.source), workspace)
        result = artifact_dir / "verification.json"
        log = artifact_dir / "verifier.log"
        digest = plan.argv[-1].split("--candidate-digest ", 1)[1].split()[0]
        completed = subprocess.run(
            [
                sys.executable,
                verifier.source,
                "--workspace",
                str(workspace),
                "--candidate-digest",
                digest,
                "--result",
                str(result),
                "--log",
                str(log),
            ],
            check=False,
            timeout=30,
        )
        artifacts = ()
        if completed.returncode == 0:
            artifacts = (
                _artifact("/outputs/verification.json", result, "application/json"),
                _artifact("/outputs/verifier.log", log, "text/plain"),
            )
        return StageResult(execution, completed.returncode, "", artifacts)


def _artifact(name: str, path: Path, media_type: str) -> Artifact:
    payload = path.read_bytes()
    return Artifact(name, str(path), len(payload), hashlib.sha256(payload).hexdigest(), media_type)


def _episode(variant: str, episode_id: str):
    fixture = Path(__file__).parents[1] / "fixtures" / "programbench" / "calculator-v1"
    raw: object = json.loads((fixture / "row.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return ProgramBenchCompatibilityResolver().resolve(
        cast(dict[str, Any], raw),
        source_dir=fixture,
        episode_id=episode_id,
        inference_environment_id="programbench-inference",
        verification_environment_id="programbench-verification",
        inference_image=f"registry.invalid/inference@sha256:{'a' * 64}",
        verification_image=f"registry.invalid/verification@sha256:{'b' * 64}",
        task_platform="linux/amd64",
        harness=HarnessSpec("static-candidate", "1", config={"candidate_variant": variant}),
    )


@pytest.mark.parametrize(
    ("variant", "verdict", "score"),
    (("gold", "passed", 1.0), ("empty", "failed", 0.0), ("known-bad", "failed", 1 / 3)),
)
def test_programbench_compatibility_vertical(
    tmp_path: Path, variant: str, verdict: str, score: float
) -> None:
    episode = _episode(variant, f"programbench-{variant}")
    selection = resolve_adapters(episode)
    assert isinstance(selection.task, ProgramBenchTaskAdapter)
    backend = ProgramBenchBackend()
    store = EpisodeStore(tmp_path / "state")
    result = EpisodeRunner(backend=backend, store=store).run(
        episode,
        inference=selection.inference,
        candidate=selection.candidate,
        verifier=selection.verifier,
    )
    assert result.verdict == verdict
    assert result.score == pytest.approx(score)
    record = store.load(episode.episode_id)
    assert record is not None and record.inference is not None and record.verification is not None
    assert record.inference.run_id != record.verification.run_id
    assert record.inference.environment_id != record.verification.environment_id
    bundle = load_candidate(Path(record.candidate_manifest))
    extracted = tmp_path / f"extracted-{variant}"
    extract_workspace_archive(Path(bundle.root) / bundle.files[0].bundle_path, extracted)
    assert not (extracted / "executable").exists()
    assert result.candidate_digest == bundle.digest


def test_programbench_qualification_is_stage_specific() -> None:
    episode = _episode("gold", "programbench-qualification")
    inference = resolve_qualification_requirements(episode, "inference")
    verification = resolve_qualification_requirements(episode, "verification")
    assert inference.task_mode == "prepared"
    assert [(item.path, item.mode) for item in inference.workspace_files] == [("executable", 0o111)]
    assert inference.archive_finalizer is True
    assert verification.task_mode == "empty" and verification.workspace_files == ()
    assert verification.verifier_file.endswith("verifier/run_verifier.py")


def test_programbench_resolver_rejects_native_shape_drift() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "programbench" / "calculator-v1"
    raw = json.loads((fixture / "row.json").read_text(encoding="utf-8"))
    raw["instance_id"] = "another__instance.0000000"
    with pytest.raises(ContractError, match="instance_id is unsupported"):
        ProgramBenchCompatibilityResolver().resolve(
            raw,
            source_dir=fixture,
            episode_id="bad",
            inference_environment_id="inference",
            verification_environment_id="verification",
            inference_image=f"registry.invalid/inference@sha256:{'a' * 64}",
            verification_image=f"registry.invalid/verification@sha256:{'b' * 64}",
            task_platform="linux/amd64",
            harness=HarnessSpec("static-candidate", "1", config={"candidate_variant": "gold"}),
        )


def test_programbench_candidate_reference_exclusion_is_required() -> None:
    episode = _episode("gold", "programbench-missing-exclusion")
    broken = replace(
        episode,
        candidate=CandidateSpec(
            "workspace-archive",
            "1",
            {"source_directory": episode.candidate.config["source_directory"]},
        ),
    )
    selection = resolve_adapters(broken)
    capture = selection.candidate.capture_plan(broken)
    with pytest.raises(ContractError, match="exclude the seed executable"):
        selection.verifier.plan(
            broken,
            # The verifier rejects the episode before inspecting bundle fields.
            cast(Any, object()),
        )
    assert "rm -f" not in capture.finalize_script


def test_programbench_fixture_images_are_dual_platform_and_fail_closed() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "programbench" / "calculator-v1"
    for name in ("Dockerfile.inference", "Dockerfile.verification"):
        text = (fixture / name).read_text(encoding="utf-8")
        assert "ARG TARGETARCH" in text
        assert 'case "$TARGETARCH" in amd64|arm64)' in text
        assert "@sha256:" in text
        assert "/workspace" in text
        assert not any(value in text.lower() for value in ("credential", "localhost", "aliyun"))
    inference = (fixture / "Dockerfile.inference").read_text(encoding="utf-8")
    assert "chmod 0111 /workspace/executable" in inference
