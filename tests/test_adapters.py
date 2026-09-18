from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

import axrun.adapters._candidate as candidate_module
from axrun.adapters import CommandVerifierAdapter, MiniSweAgentAdapter
from axrun.adapters._candidate import load_candidate, persist_candidate
from axrun.errors import ContractError
from axrun.models import Artifact, ExecutionRef, ResolvedEpisode, StageResult


def episode(tmp_path: Path) -> ResolvedEpisode:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("fix it", encoding="utf-8")
    return ResolvedEpisode(1, "ep", "task", "sha256:task", "a" * 40, str(prompt), "env-i", "env-v")


def test_mini_swe_plan_uses_official_cli_and_declared_outputs(tmp_path: Path) -> None:
    plan = MiniSweAgentAdapter().plan(episode(tmp_path))
    assert plan.image_mounts == () and plan.secret_env == ()
    assert plan.labels["axrun.agent"] == "mini-swe-agent"
    assert "mini -y -t" in plan.argv[-1]
    assert "GIT_INDEX_FILE" in plan.argv[-1]
    assert {item.path for item in plan.outputs} == {
        "/outputs/candidate.patch",
        "/outputs/trajectory.json",
        "/outputs/mini-swe-agent.log",
    }


def test_candidate_is_self_contained_and_detects_tampering(tmp_path: Path) -> None:
    source = tmp_path / "patch"
    source.write_bytes(b"patch")
    artifact = Artifact(
        "/outputs/candidate.patch",
        str(source),
        5,
        hashlib.sha256(b"patch").hexdigest(),
        "text/x-diff",
    )
    stage = StageResult(ExecutionRef("env-i", "run-i", "alloc-i"), 0, "", (artifact,))
    destination = tmp_path / "candidate"
    bundle = persist_candidate(
        episode(tmp_path),
        stage,
        destination=destination,
        required_paths=(artifact.name,),
        harness="mini-swe-agent",
        harness_version="2.4.6",
    )
    assert load_candidate(Path(bundle.root) / "candidate-manifest.json").digest == bundle.digest
    exported = tmp_path / "exported"
    shutil.copytree(bundle.root, exported)
    assert load_candidate(exported / "candidate-manifest.json").digest == bundle.digest
    (Path(bundle.root) / bundle.files[0].bundle_path).write_bytes(b"wrong")
    with pytest.raises(ContractError, match="integrity"):
        load_candidate(Path(bundle.root) / "candidate-manifest.json")


def test_verifier_receives_only_candidate_and_digest(tmp_path: Path) -> None:
    source = tmp_path / "patch"
    source.write_bytes(b"patch")
    artifact = Artifact(
        "/outputs/candidate.patch",
        str(source),
        5,
        hashlib.sha256(b"patch").hexdigest(),
        "text/x-diff",
    )
    bundle = persist_candidate(
        episode(tmp_path),
        StageResult(ExecutionRef("env-i", "run-i"), 0, "", (artifact,)),
        destination=tmp_path / "candidate",
        required_paths=(artifact.name,),
        harness="mini-swe-agent",
        harness_version="2.4.6",
    )
    plan = CommandVerifierAdapter().plan(episode(tmp_path), bundle)
    assert plan.environment_id == "env-v" and plan.network_policy == "deny_all"
    assert plan.env == {"AXRUN_CANDIDATE_DIGEST": bundle.digest}
    assert plan.secret_env == () and plan.image_mounts == ()


def test_candidate_crash_before_atomic_publish_leaves_no_final_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "patch"
    source.write_bytes(b"patch")
    artifact = Artifact(
        "/outputs/candidate.patch",
        str(source),
        5,
        hashlib.sha256(b"patch").hexdigest(),
        "text/x-diff",
    )
    destination = tmp_path / "candidate"
    monkeypatch.setattr(
        candidate_module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("crash"))
    )
    with pytest.raises(OSError, match="crash"):
        persist_candidate(
            episode(tmp_path),
            StageResult(ExecutionRef("env-i", "run-i"), 0, "", (artifact,)),
            destination=destination,
            required_paths=(artifact.name,),
            harness="mini-swe-agent",
            harness_version="2.4.6",
        )
    assert not list(destination.glob("sha256/*/candidate-manifest.json"))
