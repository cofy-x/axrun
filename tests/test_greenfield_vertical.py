from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from axrun.adapters import GreenfieldVerifierAdapter, StaticCandidateHarness
from axrun.adapters._candidate import load_candidate
from axrun.candidates import WorkspaceArchiveCandidateAdapter
from axrun.candidates.archive import create_workspace_archive, extract_workspace_archive
from axrun.datasets import SyntheticGreenfieldResolver
from axrun.errors import InfrastructureError
from axrun.models import Artifact, ExecutionRef, HarnessSpec, StagePlan, StageResult
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore


class GreenfieldBackend:
    def __init__(self, *, fail_finalization: bool = False) -> None:
        self.executions: list[ExecutionRef] = []
        self.plans: list[StagePlan] = []
        self.fail_finalization = fail_finalization

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
        if plan.labels["axrun.stage"] == "inference":
            return self._inference(plan, artifact_dir, execution)
        return self._verification(plan, artifact_dir, execution)

    def recover(
        self, execution: ExecutionRef, plan: StagePlan, *, artifact_dir: Path
    ) -> StageResult:
        if plan.labels["axrun.stage"] == "inference":
            return self._inference(plan, artifact_dir, execution)
        return self._verification(plan, artifact_dir, execution)

    def cancel(self, execution: ExecutionRef) -> None:
        return None

    def wait(self, execution: ExecutionRef, *, timeout: float | None = None) -> None:
        return None

    def _inference(
        self, plan: StagePlan, artifact_dir: Path, execution: ExecutionRef
    ) -> StageResult:
        if self.fail_finalization:
            return StageResult(execution, 125, "CANDIDATE_FINALIZATION_FAILED", ())
        workspace = artifact_dir / "inference-workspace"
        workspace.mkdir(parents=True)
        prefix = "/run/axrun/static-source/"
        for item in plan.inputs:
            if item.target.startswith(prefix):
                target = workspace / item.target.removeprefix(prefix)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item.source, target)
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
        candidate = next(item for item in plan.inputs if item.target == "/inputs/workspace.tar")
        verifier = next(
            item for item in plan.inputs if item.target == "/opt/axrun-greenfield/run_verifier.py"
        )
        extract_workspace_archive(Path(candidate.source), workspace)
        result_path = artifact_dir / "verification.json"
        log_path = artifact_dir / "verifier.log"
        candidate_digest = plan.argv[-1].split("--candidate-digest ", 1)[1].split()[0]
        completed = subprocess.run(
            [
                sys.executable,
                verifier.source,
                "--workspace",
                str(workspace),
                "--candidate-digest",
                candidate_digest,
                "--result",
                str(result_path),
                "--log",
                str(log_path),
            ],
            check=False,
            timeout=30,
        )
        artifacts = ()
        if completed.returncode == 0:
            artifacts = (
                _artifact("/outputs/verification.json", result_path, "application/json"),
                _artifact("/outputs/verifier.log", log_path, "text/plain"),
            )
        return StageResult(execution, completed.returncode, "", artifacts)


def _artifact(name: str, path: Path, media_type: str) -> Artifact:
    payload = path.read_bytes()
    return Artifact(
        name,
        str(path),
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        media_type,
    )


def _episode(variant: str, episode_id: str):
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "greenfield-task-v1"
    raw: object = json.loads((fixture / "row.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return SyntheticGreenfieldResolver().resolve(
        cast(dict[str, Any], raw),
        source_dir=fixture,
        episode_id=episode_id,
        inference_environment_id="greenfield-inference",
        verification_environment_id="greenfield-verification",
        inference_image=f"registry.invalid/inference@sha256:{'a' * 64}",
        verification_image=f"registry.invalid/verification@sha256:{'b' * 64}",
        task_platform="linux/amd64",
        harness=HarnessSpec("static-candidate", "1", config={"candidate_variant": variant}),
    )


@pytest.mark.parametrize(
    ("variant", "verdict"),
    [("gold", "passed"), ("empty", "failed"), ("known-bad", "failed")],
)
def test_greenfield_archive_completes_fresh_two_stage_vertical(
    tmp_path: Path, variant: str, verdict: str
) -> None:
    episode = _episode(variant, f"greenfield-{variant}")
    backend = GreenfieldBackend()
    store = EpisodeStore(tmp_path / "state")
    result = EpisodeRunner(backend=backend, store=store).run(
        episode,
        inference=StaticCandidateHarness(),
        candidate=WorkspaceArchiveCandidateAdapter(),
        verifier=GreenfieldVerifierAdapter(),
    )
    record = store.load(episode.episode_id)
    assert record is not None and record.inference is not None and record.verification is not None
    assert result.verdict == verdict
    assert record.inference.run_id != record.verification.run_id
    assert record.inference.allocation_id != record.verification.allocation_id
    assert record.inference.environment_id != record.verification.environment_id
    bundle = load_candidate(Path(record.candidate_manifest))
    assert bundle.files[0].role == "workspace"
    assert result.candidate_digest == bundle.digest
    verification = backend.plans[1]
    assert verification.secret_env == () and verification.image_mounts == ()
    assert all("inference-workspace" not in item.source for item in verification.inputs)


def test_candidate_finalization_failure_does_not_start_verifier(tmp_path: Path) -> None:
    episode = _episode("gold", "greenfield-finalization-failure")
    backend = GreenfieldBackend(fail_finalization=True)
    with pytest.raises(InfrastructureError, match="inference Run failed"):
        EpisodeRunner(backend=backend, store=EpisodeStore(tmp_path / "state")).run(
            episode,
            inference=StaticCandidateHarness(),
            candidate=WorkspaceArchiveCandidateAdapter(),
            verifier=GreenfieldVerifierAdapter(),
        )
    assert len(backend.executions) == 1


def test_static_workspace_source_inputs_are_content_pinned() -> None:
    episode = _episode("gold", "greenfield-source-pins")
    capture = WorkspaceArchiveCandidateAdapter().capture_plan(episode)
    sources = [item for item in capture.inputs if "/static-source/" in item.target]
    assert sources and all(len(item.sha256) == 64 for item in sources)
