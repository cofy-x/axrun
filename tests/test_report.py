from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from axrun.adapters import CommandVerifierAdapter, StaticCandidateHarness
from axrun.adapters._candidate import persist_candidate
from axrun.candidates import GitPatchCandidateAdapter
from axrun.catalog import AdapterSelection
from axrun.errors import ContractError
from axrun.models import (
    Artifact,
    CandidateSpec,
    EnvironmentBinding,
    EpisodePhase,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageResult,
    TaskSpec,
    VerificationResult,
    VerifierSpec,
    canonical_digest,
)
from axrun.qualification import QualificationResult, QualificationTargetResult
from axrun.report import REPORT_FORMAT, report_markdown, verify_record
from axrun.store import EpisodeStore
from axrun.tasks import GitWorktreeTaskAdapter
from axrun.trajectories.bundle import persist_trajectory_bundle
from axrun.trajectories.schema import TrajectoryEvent


def _episode(tmp_path: Path) -> ResolvedEpisode:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("task", encoding="utf-8")
    image = f"registry.invalid/task@sha256:{'f' * 64}"
    return ResolvedEpisode(
        1,
        "episode",
        "task",
        "a" * 64,
        str(prompt),
        TaskSpec("git-worktree", "1", {"base_commit": "b" * 40}),
        EnvironmentBinding("env-inference", image, "linux/amd64", "/workspace"),
        EnvironmentBinding("env-verification", image, "linux/amd64", "/workspace"),
        HarnessSpec("static-candidate", "1"),
        CandidateSpec("git-patch", "1"),
        VerifierSpec("command-verifier", "1"),
    )


def _completed_store(
    tmp_path: Path, *, task_identity: str = "git-worktree"
) -> tuple[EpisodeStore, Path]:
    store = EpisodeStore(tmp_path / "state")
    episode = replace(
        _episode(tmp_path),
        task=TaskSpec(task_identity, "1", {"base_commit": "b" * 40}),
    )
    record = store.initialize(episode)
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"patch")
    patch_digest = hashlib.sha256(b"patch").hexdigest()
    candidate = persist_candidate(
        episode,
        StageResult(
            ExecutionRef("env-inference", "run-inference", "alloc-inference"),
            0,
            "",
            (Artifact("/outputs/candidate.patch", str(patch), 5, patch_digest, "text/x-diff"),),
        ),
        destination=store.root / "candidates",
        required_outputs=(("patch", "/outputs/candidate.patch"),),
        harness="static-candidate",
        harness_version="1",
    )
    now = datetime.now(UTC).isoformat()
    result = VerificationResult(
        1,
        candidate.digest,
        "command-verifier",
        "1",
        "passed",
        "",
        0,
        "c" * 64,
        now,
        now,
        1.0,
    )
    result_path, result_digest = store.save_result(result)
    checks = {
        "schema_version": 1,
        "role": "inference",
        "base_commit": episode.task.config["base_commit"],
        "git": "git version 2.51.0",
        "machine": "x86_64",
        "python": "3.12.11",
        "working_directory": "/workspace",
        "workspace_empty": None,
        "workspace_files": None,
        "archive_module": False,
        "verifier_file": False,
        "claude": None,
    }
    targets = tuple(
        QualificationTargetResult(
            role,
            environment_id,
            episode.inference_environment.image,
            "linux/amd64",
            "/workspace",
            f"run-{role}-qualification",
            f"alloc-{role}-qualification",
            "f" * 64,
            dict(checks, role=role),
        )
        for role, environment_id in (
            ("inference", "env-inference"),
            ("verification", "env-verification"),
        )
    )
    qualification = QualificationResult(1, episode.episode_id, episode.digest, targets)
    qualification_path = tmp_path / "qualification.json"
    qualification_path.write_text(
        json.dumps(qualification.as_dict(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    record.phase = EpisodePhase.COMPLETED
    record.qualifications = tuple(
        ExecutionRef(target.environment_id, target.run_id, target.allocation_id)
        for target in targets
    )
    record.qualification_result = str(qualification_path)
    record.qualification_result_digest = canonical_digest(qualification.as_dict())
    record.inference = ExecutionRef("env-inference", "run-inference", "alloc-inference")
    record.inference_termination_reason = "completed"
    record.candidate_manifest = str(Path(candidate.root) / "candidate-manifest.json")
    record.candidate_digest = candidate.digest
    record.verification = ExecutionRef("env-verification", "run-verification", "alloc-verification")
    record.verification_result = str(result_path)
    record.verification_result_digest = result_digest
    record.completed_at = now
    store.save(record)
    return store, Path(candidate.root) / candidate.files[0].bundle_path


def _attach_trajectory(
    store: EpisodeStore, tmp_path: Path, *, harness: str, harness_version: str
) -> None:
    record = store.load("episode")
    assert record is not None and record.inference is not None
    episode = store.load_spec("episode")
    event = TrajectoryEvent(
        1,
        0,
        "event-00000000",
        None,
        "session_start",
        "runtime",
        None,
        None,
        None,
        {
            "harness": harness,
            "harness_version": harness_version,
            "runtime_version": "1",
            "tools": [],
        },
    )
    trajectory_path = tmp_path / "trajectory.jsonl"
    trajectory_path.write_text(json.dumps(event.as_dict()) + "\n", encoding="utf-8")
    usage_path = tmp_path / "usage.json"
    usage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "observations": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            }
        ),
        encoding="utf-8",
    )
    artifacts = tuple(
        Artifact(
            f"/outputs/{path.name}",
            str(path),
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            media_type,
        )
        for path, media_type in (
            (trajectory_path, "application/x-ndjson"),
            (usage_path, "application/json"),
        )
    )
    bundle = persist_trajectory_bundle(
        episode,
        StageResult(record.inference, 0, "", artifacts),
        destination=store.root / "trajectories",
        trajectory_path="/outputs/trajectory.jsonl",
        usage_path="/outputs/usage.json",
        harness=harness,
        harness_version=harness_version,
    )
    record.trajectory_manifest = str(Path(bundle.root) / "trajectory-manifest.json")
    record.trajectory_digest = bundle.digest
    store.save(record)


def test_verify_record_rechecks_full_completed_digest_chain(tmp_path: Path) -> None:
    store, _ = _completed_store(tmp_path)
    report = verify_record(store, "episode")

    assert report["format"] == REPORT_FORMAT
    assert report["integrity_verified"] is True
    assert report["verdict"] == "passed" and report["score"] == 1.0
    assert report["inference_termination_reason"] == "completed"
    assert report["qualifications"][0]["run_id"] == "run-inference-qualification"
    assert report["inference"]["run_id"] == "run-inference"
    assert report["verification"]["run_id"] == "run-verification"
    assert "CandidateBundle" in report_markdown(report)


def test_verify_record_accepts_matching_trajectory_harness(tmp_path: Path) -> None:
    store, _ = _completed_store(tmp_path)
    _attach_trajectory(store, tmp_path, harness="static-candidate", harness_version="1")

    assert verify_record(store, "episode")["integrity_verified"] is True


@pytest.mark.parametrize(
    ("harness", "harness_version"),
    [("other-harness", "1"), ("static-candidate", "2")],
)
def test_verify_record_rejects_integrity_valid_trajectory_harness_mismatch(
    tmp_path: Path, harness: str, harness_version: str
) -> None:
    store, _ = _completed_store(tmp_path)
    _attach_trajectory(store, tmp_path, harness=harness, harness_version=harness_version)

    with pytest.raises(ContractError, match="TrajectoryBundle provenance mismatch"):
        verify_record(store, "episode")


def test_verify_record_accepts_explicit_stage_zero_selection(tmp_path: Path) -> None:
    store, _ = _completed_store(tmp_path, task_identity="unregistered-stage-zero")
    with pytest.raises(ContractError, match="unsupported task adapter"):
        verify_record(store, "episode")
    harness = StaticCandidateHarness()
    selection = AdapterSelection(
        task=GitWorktreeTaskAdapter(name="unregistered-stage-zero"),
        inference=harness,
        candidate=GitPatchCandidateAdapter(),
        verifier=CommandVerifierAdapter(),
        trajectory=None,
        runtime=harness.runtime_requirements,
    )
    report = verify_record(store, "episode", selection=selection)
    assert report["integrity_verified"] is True
    assert report["task"] == {"identity": "unregistered-stage-zero", "version": "1"}


@pytest.mark.parametrize(
    ("field", "value"),
    [("verifier", "other-verifier"), ("verifier_version", "2")],
)
def test_verify_record_rejects_result_verifier_identity_mismatch(
    tmp_path: Path, field: str, value: str
) -> None:
    store, _ = _completed_store(tmp_path)
    record = store.load("episode")
    assert record is not None
    result = store.load_result(record.verification_result, record.verification_result_digest)
    path, digest = store.save_result(replace(result, **{field: value}))
    record.verification_result = str(path)
    record.verification_result_digest = digest
    store.save(record)
    with pytest.raises(ContractError, match="verifier identity mismatch"):
        verify_record(store, "episode")


def test_verify_record_fails_closed_on_bundle_tampering(tmp_path: Path) -> None:
    store, patch = _completed_store(tmp_path)
    patch.write_bytes(b"tampered")

    with pytest.raises(ContractError, match="integrity"):
        verify_record(store, "episode")


def test_completed_record_requires_accepted_outputs(tmp_path: Path) -> None:
    store = EpisodeStore(tmp_path / "state")
    record = store.initialize(_episode(tmp_path))
    record.phase = EpisodePhase.COMPLETED
    store.save(record)

    with pytest.raises(ContractError, match="missing accepted outputs"):
        verify_record(store, "episode")
