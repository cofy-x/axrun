from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from axrun.adapters._candidate import persist_candidate
from axrun.errors import ContractError
from axrun.models import (
    Artifact,
    EpisodePhase,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageResult,
    VerificationResult,
    VerifierSpec,
    canonical_digest,
)
from axrun.qualification import QualificationResult
from axrun.report import REPORT_FORMAT, report_markdown, verify_record
from axrun.store import EpisodeStore


def _episode(tmp_path: Path) -> ResolvedEpisode:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("task", encoding="utf-8")
    return ResolvedEpisode(
        1,
        "episode",
        "task",
        "a" * 64,
        "b" * 40,
        str(prompt),
        "env-inference",
        "env-verification",
        HarnessSpec("static-patch", "1"),
        VerifierSpec("command-verifier", "1"),
    )


def _completed_store(tmp_path: Path) -> tuple[EpisodeStore, Path]:
    store = EpisodeStore(tmp_path / "state")
    episode = _episode(tmp_path)
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
        required_paths=("/outputs/candidate.patch",),
        harness="static-patch",
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
    qualification = QualificationResult(
        1,
        episode.episode_id,
        episode.digest,
        f"registry.example/task@sha256:{'e' * 64}",
        "run-qualification",
        "alloc-qualification",
        "f" * 64,
        {
            "schema_version": 1,
            "base_commit": episode.base_commit,
            "git": "git version 2.51.0",
            "machine": "aarch64",
            "python": "3.12.11",
            "working_directory": "/workspace",
            "claude": None,
        },
    )
    qualification_path = tmp_path / "qualification.json"
    qualification_path.write_text(
        json.dumps(qualification.as_dict(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    record.phase = EpisodePhase.COMPLETED
    record.qualification = ExecutionRef("env-inference", "run-qualification", "alloc-qualification")
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


def test_verify_record_rechecks_full_completed_digest_chain(tmp_path: Path) -> None:
    store, _ = _completed_store(tmp_path)
    report = verify_record(store, "episode")

    assert report["format"] == REPORT_FORMAT
    assert report["integrity_verified"] is True
    assert report["verdict"] == "passed" and report["score"] == 1.0
    assert report["inference_termination_reason"] == "completed"
    assert report["qualification"]["run_id"] == "run-qualification"
    assert report["inference"]["run_id"] == "run-inference"
    assert report["verification"]["run_id"] == "run-verification"
    assert "CandidateBundle" in report_markdown(report)


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
