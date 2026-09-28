"""Registered Flask task and mandatory admission cannot be bypassed by callers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from flask_admission_fixtures import RUNTIME_IMAGE, import_receipt, pin_synthetic_row, write_receipt

from axrun.adapters import swebench_flask_official as verifier_lock
from axrun.catalog import resolve_adapters, resolve_required_admission, resolve_task
from axrun.datasets import swebench_flask_official as lock
from axrun.errors import ContractError
from axrun.models import (
    Artifact,
    EpisodePhase,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageResult,
    TaskSpec,
    canonical_digest,
    canonical_json,
)
from axrun.qualification import load_qualification_result, qualify_episode, require_admission
from axrun.report import verify_record
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore
from axrun.tasks import GitWorktreeTaskAdapter
from axrun.tasks.swebench_flask_official import SweBenchFlaskOfficialTaskAdapter


@pytest.fixture
def episode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ResolvedEpisode:
    row: dict[str, Any] = {
        "FAIL_TO_PASS": ["synthetic_failing_test"],
        "PASS_TO_PASS": [f"synthetic_passing_test_{index}" for index in range(59)],
        "base_commit": "7ee9ceb71e868944a46e1ff00b506772a53a4f1d",
        "created_at": "2024-01-01T00:00:00Z",
        "difficulty": "synthetic",
        "environment_setup_commit": "a" * 40,
        "eval_script": "#!/bin/bash\necho synthetic-offline-test\n",
        "eval_type": "pass_and_fail",
        "hints_text": "synthetic-hidden-hint",
        "image": "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest",
        "instance_id": "pallets__flask-5014",
        "log_parser": "parse_log_flask",
        "patch": "synthetic-private-gold",
        "problem_statement": "Fix the synthetic problem.",
        "repo": "pallets/flask",
        "test_patch": "synthetic-private-test",
        "version": "2.3",
    }
    pin_synthetic_row(row, monkeypatch)
    monkeypatch.setattr(verifier_lock, "_EVAL_SCRIPT_SHA256", lock._EVAL_SCRIPT_SHA256)
    wheels = (
        ("setuptools-70.0.0-py3-none-any.whl", b"synthetic-setuptools"),
        ("wheel-0.45.1-py3-none-any.whl", b"synthetic-wheel"),
    )
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    checks = []
    for name, payload in wheels:
        (wheelhouse / name).write_bytes(payload)
        checks.append((name, len(payload), hashlib.sha256(payload).hexdigest()))
    monkeypatch.setattr(lock, "_LOCKED_WHEELS", tuple(checks))
    monkeypatch.setattr(
        verifier_lock,
        "_WHEELS",
        {"setuptools_wheel_file": checks[0], "wheel_wheel_file": checks[1]},
    )
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"synthetic candidate\n")
    return lock.SweBenchFlaskOfficialResolver().resolve(
        row,
        asset_dir=tmp_path / "assets",
        episode_id="flask-gated-episode",
        inference_environment_id="env-inference",
        verification_environment_id="env-verification",
        task_image=RUNTIME_IMAGE,
        image_import_receipt=import_receipt(),
        admission_receipt_file=write_receipt(tmp_path / "admission.json"),
        wheelhouse_dir=wheelhouse,
        harness=HarnessSpec("static-candidate", "1"),
        static_candidate_file=patch,
    )


class _Backend:
    def __init__(self) -> None:
        self.executed = []
        self.recovered = []
        self.waited = []
        self.cancelled = []

    def execute(self, plan, *, artifact_dir, on_bound, lifecycle=None):
        assert lifecycle is None and plan.labels["axrun.stage"] == "qualification"
        assert plan.network_policy == "deny_all"
        for item in plan.inputs:
            payload = Path(item.source).read_bytes()
            assert b"synthetic-private-gold" not in payload
            assert b"synthetic-private-test" not in payload
            assert b"synthetic-hidden-hint" not in payload
        self.executed.append(plan)
        role = plan.labels["axrun.qualification.role"]
        execution = ExecutionRef(plan.environment_id, f"run-q-{role}", f"alloc-q-{role}")
        on_bound(execution)
        payload = {
            "schema_version": 1,
            "role": role,
            "base_commit": lock._IMAGE_HEAD,
            "git": "git version 2.51.0",
            "machine": "x86_64",
            "python": "3.12.11",
            "working_directory": "/testbed",
            "workspace_empty": None,
            "workspace_files": None,
            "archive_module": False,
            "verifier_file": role == "verification",
            "claude": None,
        }
        data = canonical_json(payload)
        path = artifact_dir / "qualification.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StageResult(
            execution,
            0,
            "",
            (
                Artifact(
                    "/outputs/qualification.json",
                    str(path),
                    len(data),
                    hashlib.sha256(data).hexdigest(),
                    "application/json",
                ),
            ),
        )

    def recover(self, execution, plan, *, artifact_dir):
        self.recovered.append(execution)
        raise AssertionError("invalid admission cannot query or recover a Run")

    def wait(self, execution, *, timeout=None):
        self.waited.append(execution)
        raise AssertionError("invalid admission cannot wait on a Run")

    def cancel(self, execution):
        self.cancelled.append(execution)


def _client():
    return SimpleNamespace(
        get_environment=lambda _id: SimpleNamespace(
            spec=SimpleNamespace(image=SimpleNamespace(ref=RUNTIME_IMAGE))
        )
    )


def _receipt_path(episode: ResolvedEpisode) -> Path:
    return Path(episode.task.config["admission_receipt_file"])


def test_catalog_uses_closed_task_and_verified_admission(episode: ResolvedEpisode) -> None:
    task = resolve_task(episode)
    assert isinstance(task, SweBenchFlaskOfficialTaskAdapter)
    assert isinstance(resolve_required_admission(episode), SweBenchFlaskOfficialTaskAdapter)
    evidence = task.validate_admission(episode)
    assert evidence["runtime_image"] == RUNTIME_IMAGE
    summary = task.admission_report(episode)
    assert summary["trust_boundary"] == "caller-owned-state"
    assert summary["receipt_sha256"] == episode.task.config["admission_receipt_sha256"]
    assert summary["execution"] == evidence["execution"]
    assert "sealed_audit" not in summary
    for role in ("inference", "verification"):
        requirements = task.qualification_requirements(episode, role)
        assert requirements.mode == "git" and requirements.base_commit == lock._IMAGE_HEAD


@pytest.mark.parametrize("bad", ["missing", "corrupt", "old_task_contract"])
def test_qualification_cannot_override_mandatory_task_admission(
    episode: ResolvedEpisode,
    tmp_path: Path,
    bad: str,
) -> None:
    selection = resolve_adapters(episode)
    bypass = replace(selection, task=GitWorktreeTaskAdapter(name="swebench-flask-official"))
    if bad == "missing":
        _receipt_path(episode).unlink()
    elif bad == "corrupt":
        _receipt_path(episode).write_bytes(b'{"status":"passed"}\n')
    else:
        episode = replace(
            episode,
            task=TaskSpec("swebench-flask-official", "1", {"base_commit": lock._IMAGE_HEAD}),
        )
    backend = _Backend()
    with pytest.raises(ContractError):
        qualify_episode(
            episode,
            client=_client(),
            backend=backend,
            store=EpisodeStore(tmp_path / "state"),
            selection=bypass,
        )
    assert backend.executed == [] and backend.recovered == []


def test_same_length_test_selection_replacement_cannot_shrink_or_change_denominator(
    episode: ResolvedEpisode,
) -> None:
    original = episode.verifier.config
    for key in ("fail_to_pass", "pass_to_pass"):
        changed = list(original[key])
        changed[0] = "replaced-expected-test"
        bad = replace(
            episode, verifier=replace(episode.verifier, config={**original, key: changed})
        )
        with pytest.raises(ContractError, match="selection differs"):
            SweBenchFlaskOfficialTaskAdapter().validate_admission(bad)


@pytest.mark.parametrize(
    "change",
    [
        "instance",
        "task_version",
        "verifier_version",
        "task_identity",
        "seed",
        "platform",
        "workspace",
        "same_environment",
        "candidate",
        "network",
        "metadata",
        "extra_config",
    ],
)
def test_locked_episode_contract_cannot_be_relabeled_or_weakened(
    episode: ResolvedEpisode,
    change: str,
) -> None:
    if change == "instance":
        bad = replace(episode, task_id="another__flask-5014")
    elif change == "task_version":
        bad = replace(episode, task=replace(episode.task, version="2"))
    elif change == "verifier_version":
        bad = replace(episode, verifier=replace(episode.verifier, version="2"))
    elif change == "task_identity":
        bad = replace(
            episode, task=TaskSpec("git-worktree", "1", {"base_commit": lock._IMAGE_HEAD})
        )
    elif change == "seed":
        bad = replace(episode, seed_digest="0" * 64)
    elif change == "platform":
        bad = replace(
            episode,
            inference_environment=replace(episode.inference_environment, platform="linux/arm64"),
        )
    elif change == "workspace":
        bad = replace(
            episode,
            verification_environment=replace(
                episode.verification_environment, working_directory="/workspace"
            ),
        )
    elif change == "same_environment":
        bad = replace(episode, verification_environment=episode.inference_environment)
    elif change == "candidate":
        bad = replace(episode, candidate=replace(episode.candidate, identity="workspace-archive"))
    elif change == "network":
        bad = replace(episode, inference_network_policy="unrestricted")
    elif change == "metadata":
        bad = replace(episode, metadata={**episode.metadata, "task_platform": "linux/arm64"})
    else:
        bad = replace(
            episode,
            task=replace(episode.task, config={**episode.task.config, "skip_admission": True}),
        )
    with pytest.raises(ContractError):
        SweBenchFlaskOfficialTaskAdapter().validate_admission(bad)


def test_prompt_file_and_offline_assets_are_rechecked(episode: ResolvedEpisode) -> None:
    prompt = Path(episode.prompt_file)
    before = prompt.read_bytes()
    prompt.write_bytes(before.replace(b"synthetic", b"different"))
    with pytest.raises(ContractError, match="prompt differs"):
        SweBenchFlaskOfficialTaskAdapter().validate_admission(episode)
    prompt.write_bytes(before)
    Path(episode.verifier.config["setuptools_wheel_file"]).write_bytes(b"changed wheel")
    with pytest.raises(ContractError, match=r"size|SHA-256"):
        SweBenchFlaskOfficialTaskAdapter().validate_admission(episode)


def test_claude_cannot_remove_required_web_tool_restrictions(episode: ResolvedEpisode) -> None:
    from axrun.harnesses import resolve_claude_code_spec

    harness = resolve_claude_code_spec(
        HarnessSpec(
            "claude-code",
            "2.1.205",
            config={
                "mount_image": f"example.invalid/claude@sha256:{'a' * 64}",
                "model": "opaque-model",
                "working_directory": "/testbed",
            },
        )
    )
    claude = replace(episode, harness=harness, candidate=replace(episode.candidate, config={}))
    SweBenchFlaskOfficialTaskAdapter().validate_admission(claude)
    changed = replace(harness, config={**harness.config, "disallowed_tools": []})
    with pytest.raises(ContractError, match="offline tool restrictions"):
        SweBenchFlaskOfficialTaskAdapter().validate_admission(replace(claude, harness=changed))


def test_runner_run_wait_recover_and_report_require_existing_qualification(
    episode: ResolvedEpisode,
    tmp_path: Path,
) -> None:
    selection = resolve_adapters(episode)
    backend = _Backend()
    store = EpisodeStore(tmp_path / "state")
    runner = EpisodeRunner(backend=backend, store=store)
    with pytest.raises(ContractError, match="qualification record is incomplete"):
        runner.run(
            episode,
            inference=selection.inference,
            candidate=selection.candidate,
            verifier=selection.verifier,
        )
    record = store.initialize(episode)
    record.phase = EpisodePhase.INFERENCE_RUNNING
    record.inference = ExecutionRef("env-inference", "run-existing", "alloc-existing")
    store.save(record)
    for operation in (runner.recover, runner.wait):
        with pytest.raises(ContractError, match="qualification record is incomplete"):
            operation(
                episode.episode_id,
                inference=selection.inference,
                candidate=selection.candidate,
                verifier=selection.verifier,
            )
    with pytest.raises(ContractError, match="qualification record is incomplete"):
        verify_record(
            store,
            episode.episode_id,
            selection=replace(
                selection, task=GitWorktreeTaskAdapter(name="swebench-flask-official")
            ),
        )
    assert backend.executed == backend.recovered == backend.waited == []


def test_qualified_record_loads_rechecks_and_cannot_be_restored_without_admission(
    episode: ResolvedEpisode,
    tmp_path: Path,
) -> None:
    store = EpisodeStore(tmp_path / "state")
    backend = _Backend()
    result = qualify_episode(episode, client=_client(), backend=backend, store=store)
    assert load_qualification_result(store, episode) == result
    require_admission(store, episode)
    selection = resolve_adapters(episode)
    record = store.load(episode.episode_id)
    assert record is not None
    record.phase = EpisodePhase.COMPLETED
    store.save(record)
    _receipt_path(episode).unlink()
    selection = replace(selection, task=GitWorktreeTaskAdapter(name="swebench-flask-official"))
    with pytest.raises(ContractError):
        verify_record(store, episode.episode_id, selection=selection)
    with pytest.raises(ContractError):
        EpisodeRunner(backend=backend, store=store).recover(
            episode.episode_id,
            inference=selection.inference,
            candidate=selection.candidate,
            verifier=selection.verifier,
        )
    assert len(backend.executed) == 2 and backend.recovered == []


@pytest.mark.parametrize("field", ["environment_image", "platform", "working_directory", "machine"])
def test_qualification_target_and_machine_are_bound_even_after_digest_recalculation(
    episode: ResolvedEpisode,
    tmp_path: Path,
    field: str,
) -> None:
    store = EpisodeStore(tmp_path / "state")
    backend = _Backend()
    qualify_episode(episode, client=_client(), backend=backend, store=store)
    record = store.load(episode.episode_id)
    assert record is not None
    path = Path(record.qualification_result)
    value = json.loads(path.read_bytes())
    if field == "machine":
        value["targets"][0]["checks"]["machine"] = "aarch64"
    else:
        value["targets"][0][field] = (
            f"example.invalid/task@sha256:{'1' * 64}"
            if field == "environment_image"
            else "linux/arm64"
            if field == "platform"
            else "/workspace"
        )
    path.write_bytes(canonical_json(value))
    record.qualification_result_digest = canonical_digest(value)
    store.save(record)
    with pytest.raises(ContractError):
        require_admission(store, episode)
    assert len(backend.executed) == 2 and backend.recovered == []


def test_reserved_flask_instance_cannot_restore_generic_task_to_skip_gate(
    episode: ResolvedEpisode,
    tmp_path: Path,
) -> None:
    selection = resolve_adapters(episode)
    generic = replace(
        episode, task=TaskSpec("git-worktree", "1", {"base_commit": lock._IMAGE_HEAD})
    )
    assert isinstance(resolve_task(generic), GitWorktreeTaskAdapter)
    assert isinstance(resolve_required_admission(generic), SweBenchFlaskOfficialTaskAdapter)
    backend = _Backend()
    store = EpisodeStore(tmp_path / "state")
    with pytest.raises(ContractError, match="locked admitted episode"):
        qualify_episode(generic, client=_client(), backend=backend, store=store)
    store.initialize(generic)
    with pytest.raises(ContractError, match="locked admitted episode"):
        EpisodeRunner(backend=backend, store=store).run(
            generic,
            inference=selection.inference,
            candidate=selection.candidate,
            verifier=selection.verifier,
        )
    with pytest.raises(ContractError, match="locked admitted episode"):
        verify_record(store, generic.episode_id)
    assert backend.executed == backend.recovered == backend.waited == []


def test_mutable_tag_or_digest_tag_alias_cannot_replace_admitted_runtime(
    episode: ResolvedEpisode,
) -> None:
    with pytest.raises(ContractError, match="OCI sha256"):
        replace(episode.inference_environment, image="docker.io/swebench/flask:latest")
    tagged_digest = RUNTIME_IMAGE.replace("@", ":latest@")
    changed = replace(
        episode,
        inference_environment=replace(episode.inference_environment, image=tagged_digest),
        verification_environment=replace(episode.verification_environment, image=tagged_digest),
    )
    with pytest.raises(ContractError):
        SweBenchFlaskOfficialTaskAdapter().validate_admission(changed)
