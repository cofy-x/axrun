from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from axrun.catalog import resolve_adapters
from axrun.datasets import ProgramBenchOfficialSingleResolver
from axrun.errors import InfrastructureError
from axrun.models import (
    Artifact,
    ExecutionRef,
    HarnessSpec,
    StagePlan,
    StageResult,
    VerifierSpec,
)
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore


def _fixture() -> Path:
    return Path(__file__).parents[1] / "fixtures" / "programbench" / "tty-clock-1.2.4-official"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(name: str, path: Path) -> Artifact:
    return Artifact(name, str(path), path.stat().st_size, _sha256(path), "application/json")


def _episode(tmp_path: Path, variant: str):
    row = cast(dict[str, Any], json.loads((_fixture() / "row.json").read_text()))
    assets = tmp_path / "assets"
    lock = cast(dict[str, Any], json.loads((_fixture() / "asset-lock.json").read_text()))
    for branch, value in lock["test_blobs"]["branches"].items():
        path = assets / value["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"asset:{branch}".encode())
        value["size_bytes"] = path.stat().st_size
        value["sha256"] = _sha256(path)
    lock_path = tmp_path / "asset-lock.json"
    lock_path.write_text(json.dumps(lock))
    episode = ProgramBenchOfficialSingleResolver().resolve(
        row,
        source_dir=_fixture(),
        episode_id=f"programbench-official-{variant}",
        inference_environment_id="official-inference",
        verification_environment_id="official-verification",
        harness=HarnessSpec("static-candidate", "1"),
        test_assets_dir=assets,
    )
    config = {**episode.verifier.config, "asset_lock_file": str(lock_path)}
    return replace(
        episode, verifier=VerifierSpec("programbench-official-single", "1", config=config)
    )


class OfficialBackend:
    def __init__(self, *, variant: str, interrupt_branch_once: bool = False) -> None:
        self.variant = variant
        self.interrupt_branch_once = interrupt_branch_once
        self.interrupted = False
        self.created: list[ExecutionRef] = []
        self.deleted_environments: list[str] = []
        self.plans: dict[str, StagePlan] = {}
        raw = json.loads((_fixture() / "tests.json").read_text())
        self.tests = {
            branch: list(value["tests"])
            for branch, value in raw["branches"].items()
            if not value["ignored"]
        }

    def _new(self, plan: StagePlan, on_bound: Callable[[ExecutionRef], None]) -> ExecutionRef:
        execution = ExecutionRef(
            plan.environment_id,
            f"run-{len(self.created) + 1}",
            f"allocation-{len(self.created) + 1}",
        )
        self.created.append(execution)
        self.plans[execution.run_id] = plan
        on_bound(execution)
        return execution

    def execute(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
        lifecycle=None,
    ) -> StageResult:
        execution = self._new(plan, on_bound)
        if plan.labels["axrun.stage"] == "inference":
            artifact_dir.mkdir(parents=True, exist_ok=True)
            archive = artifact_dir / "workspace.tar"
            archive.write_bytes(b"canonical candidate archive")
            return StageResult(
                execution,
                0,
                "",
                (
                    Artifact(
                        "/outputs/workspace.tar",
                        str(archive),
                        archive.stat().st_size,
                        _sha256(archive),
                        "application/x-tar",
                    ),
                ),
            )
        if self.interrupt_branch_once and not self.interrupted:
            self.interrupted = True
            raise InfrastructureError("simulated caller interruption")
        return self._branch_result(plan, artifact_dir, execution)

    def execute_rootfs(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
    ) -> tuple[StageResult, str]:
        execution = self._new(plan, on_bound)
        if self.variant == "empty":
            return StageResult(execution, 22, "", ()), ""
        artifact_dir.mkdir(parents=True, exist_ok=True)
        result = artifact_dir / "compile.json"
        result.write_text(
            json.dumps(
                {
                    "status": "succeeded",
                    "diagnostic_code": "",
                    "executable_sha256": "e" * 64,
                    "executable_mode": 0o755,
                }
            )
        )
        return (
            StageResult(
                execution, 0, "", (_artifact("/outputs/programbench-compile.json", result),)
            ),
            f"derived-{self.variant}",
        )

    def recover(
        self, execution: ExecutionRef, plan: StagePlan, *, artifact_dir: Path
    ) -> StageResult | None:
        return self._branch_result(plan, artifact_dir, execution)

    def recover_rootfs(
        self, execution: ExecutionRef, plan: StagePlan, *, artifact_dir: Path
    ) -> tuple[StageResult, str] | None:
        raise AssertionError("compile recovery is not used by this test")

    def wait(self, execution: ExecutionRef, *, timeout: float | None = None) -> None:
        return None

    def cancel(self, execution: ExecutionRef) -> None:
        return None

    def delete_environment(self, environment_id: str) -> None:
        if environment_id not in self.deleted_environments:
            self.deleted_environments.append(environment_id)

    def _branch_result(
        self, plan: StagePlan, artifact_dir: Path, execution: ExecutionRef
    ) -> StageResult:
        if self.variant == "infrastructure-failure":
            return StageResult(execution, 1, "RUNTIME_ERROR", ())
        branch = plan.labels["axrun.programbench.branch"]
        tests = [{"name": name, "status": "passed"} for name in self.tests[branch]]
        if self.variant == "partial" and branch == sorted(self.tests)[0]:
            tests[0]["status"] = "failure"
        if self.variant == "duplicate" and branch == sorted(self.tests)[0]:
            tests = [dict(tests[0], status="failure"), *tests]
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / "branch.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "branch": branch,
                    "status": "completed",
                    "reason_code": "",
                    "tests": tests,
                }
            )
        )
        return StageResult(
            execution,
            0,
            "",
            (_artifact("/outputs/programbench-branch.json", path),),
        )


@pytest.mark.parametrize(
    ("variant", "verdict", "score", "run_count"),
    (
        ("gold", "passed", 1.0, 8),
        ("duplicate", "passed", 1.0, 8),
        ("empty", "failed", 0.0, 2),
        ("partial", "failed", 280 / 281, 8),
    ),
)
def test_official_multirun_verifier_isolates_compile_and_branches(
    tmp_path: Path,
    variant: str,
    verdict: str,
    score: float,
    run_count: int,
) -> None:
    episode = _episode(tmp_path, variant)
    selection = resolve_adapters(episode)
    backend = OfficialBackend(variant=variant)
    store = EpisodeStore(tmp_path / "state")
    result = EpisodeRunner(backend=backend, store=store).run(
        episode,
        inference=selection.inference,
        candidate=selection.candidate,
        verifier=selection.verifier,
    )
    assert result.verdict == verdict
    assert result.score == pytest.approx(score)
    assert result.details["active_test_count"] == 281
    assert result.details["not_run"] == (281 if variant == "empty" else 0)
    assert len(backend.created) == run_count
    if variant != "empty":
        branch_plans = [
            plan
            for plan in backend.plans.values()
            if plan.labels.get("axrun.stage") == "verification-branch"
        ]
        assert len(branch_plans) == 6
        assert all(plan.environment_id == f"derived-{variant}" for plan in branch_plans)
        assert all(plan.env == {"PYTEST_XDIST_AUTO_NUM_WORKERS": "10"} for plan in branch_plans)
        assert all(plan.resources.limit_cpu == "10" for plan in branch_plans)
        assert len({ref.run_id for ref in backend.created}) == run_count
        assert all(plan.network_policy == "deny_all" for plan in branch_plans)
        assert backend.deleted_environments == [f"derived-{variant}"]
        compile_plan = next(
            plan
            for plan in backend.plans.values()
            if plan.labels.get("axrun.stage") == "verification-compile"
        )
        assert compile_plan.env == {"PYTHONPATH": "/opt/axrun"}
        assert compile_plan.network_policy == "deny_all"
        rerun_input = next(
            item
            for item in compile_plan.inputs
            if item.target == "/inputs/pytest_rerunfailures-16.7-py3-none-any.whl"
        )
        assert rerun_input.sha256 == (
            "edf1886209c2b7dafe35b5bf1708d6ec40ccf6c6b357f0f02807efcec0204c99"
        )
        assert compile_plan.argv[compile_plan.argv.index("--rerun-wheel") + 1] == (
            "/inputs/pytest_rerunfailures-16.7-py3-none-any.whl"
        )
        remove_index = compile_plan.argv.index("--remove-sha256")
        assert compile_plan.argv[remove_index + 1] == (
            "cd400708bcd6a5b9dd28bd450a211ec4625cde31470057e9d62f66072e297db0"
        )


def test_official_multirun_resume_reuses_the_bound_branch_run(tmp_path: Path) -> None:
    episode = _episode(tmp_path, "gold")
    selection = resolve_adapters(episode)
    backend = OfficialBackend(variant="gold", interrupt_branch_once=True)
    store = EpisodeStore(tmp_path / "state")
    runner = EpisodeRunner(backend=backend, store=store)
    with pytest.raises(InfrastructureError, match="simulated caller interruption"):
        runner.run(
            episode,
            inference=selection.inference,
            candidate=selection.candidate,
            verifier=selection.verifier,
        )
    created_before = len(backend.created)
    result = runner.recover(
        episode.episode_id,
        inference=selection.inference,
        candidate=selection.candidate,
        verifier=selection.verifier,
    )
    assert result.verdict == "passed"
    assert len(backend.created) == created_before + 5
    record = json.loads(
        (
            store.root / "verifications" / f"{episode.episode_id}-programbench" / "execution.json"
        ).read_text()
    )
    assert record["state"] == "completed"
    assert record["aggregation_state"] == "completed"
    assert record["cleanup_state"] == "completed"
    assert backend.deleted_environments == ["derived-gold"]


def test_official_terminal_branch_infrastructure_failure_cleans_derived_environment(
    tmp_path: Path,
) -> None:
    episode = _episode(tmp_path, "infrastructure-failure")
    selection = resolve_adapters(episode)
    backend = OfficialBackend(variant="infrastructure-failure")
    store = EpisodeStore(tmp_path / "state")
    with pytest.raises(InfrastructureError, match="RUNTIME_ERROR"):
        EpisodeRunner(backend=backend, store=store).run(
            episode,
            inference=selection.inference,
            candidate=selection.candidate,
            verifier=selection.verifier,
        )
    assert backend.deleted_environments == ["derived-infrastructure-failure"]
    record = json.loads(
        (
            store.root / "verifications" / f"{episode.episode_id}-programbench" / "execution.json"
        ).read_text()
    )
    assert record["state"] == "infrastructure_failed"
    assert record["cleanup_state"] == "completed"
