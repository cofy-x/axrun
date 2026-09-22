from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from axrun.catalog import resolve_adapters
from axrun.datasets import ProgramBenchOfficialSingleResolver
from axrun.errors import ContractError
from axrun.models import HarnessSpec, canonical_digest


def _fixture() -> Path:
    return Path(__file__).parents[1] / "fixtures" / "programbench" / "tty-clock-1.2.4-official"


def _row() -> dict[str, Any]:
    raw: object = json.loads((_fixture() / "row.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return cast(dict[str, Any], raw)


def _episode():
    return ProgramBenchOfficialSingleResolver().resolve(
        _row(),
        source_dir=_fixture(),
        episode_id="programbench-tty-clock-stage-zero",
        inference_environment_id="programbench-tty-clock-inference",
        verification_environment_id="programbench-tty-clock-verification",
        verification_image="registry.invalid/evaluator@sha256:" + "a" * 64,
        harness=HarnessSpec("static-candidate", "1"),
    )


def test_official_resolver_locks_complete_identity_and_denominator() -> None:
    row = _row()
    episode = _episode()
    assert episode.seed_digest == canonical_digest(row)
    assert episode.task_id == "xorg62__tty-clock.f2f847c"
    assert episode.task.config == {
        "instance_id": "xorg62__tty-clock.f2f847c",
        "repository": "xorg62/tty-clock",
        "commit": "f2f847cf2cc2949c8a8b7779a778f366d3743474",
        "language": "c",
        "difficulty": "easy",
        "programbench_version": "1.2.4",
        "programbench_git_sha": "963063c9271cc40fa179977356782ea4582e0b0c",
        "official_image_digest": (
            "sha256:7c070e64a44e0b7dc2a032acf02159da43a0a4993a154b5fd98c4ab997726272"
        ),
        "test_blob_revision": "de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5",
        "active_branch_count": 6,
        "active_test_count": 281,
        "ignored_test_count": 38,
    }
    expected_image = (
        "docker.io/programbench/xorg62_1776_tty-clock.f2f847c@"
        "sha256:7c070e64a44e0b7dc2a032acf02159da43a0a4993a154b5fd98c4ab997726272"
    )
    assert episode.inference_environment.image == expected_image
    assert episode.verification_environment.image == "registry.invalid/evaluator@sha256:" + "a" * 64
    assert episode.inference_environment.platform == "linux/amd64"
    assert episode.verification_environment.platform == "linux/amd64"
    assert episode.inference_environment.environment_id != (
        episode.verification_environment.environment_id
    )
    assert episode.candidate.config == {"exclude_paths": ["executable"]}
    assert episode.verifier.config["required_public_capability"] == (
        "post-compile-allocation-snapshot-v1"
    )
    dependency_lock = Path(episode.verifier.config["dependency_lock_file"])
    assert dependency_lock.name == "requirements.lock"
    assert episode.verifier.config["dependency_lock_sha256"] == (
        "2a33f102d01693cbdb04d1301d07489331c6be0f4bd1f1a77e40c8ec1b158baf"
    )
    assert episode.verifier.config["pytest_xdist_workers"] == 10
    assert episode.verification_resources.limit_cpu == "10"
    serialized = json.dumps(episode.task.config, sort_keys=True)
    assert "branches" not in serialized
    assert "ignored_tests" not in serialized


def test_official_resolver_rejects_shape_asset_and_identity_drift(tmp_path: Path) -> None:
    row = _row()
    row["unknown"] = True
    with pytest.raises(ContractError, match="invalid shape"):
        ProgramBenchOfficialSingleResolver().resolve(
            row,
            source_dir=_fixture(),
            episode_id="shape-drift",
            inference_environment_id="inference",
            verification_environment_id="verification",
            verification_image="registry.invalid/evaluator@sha256:" + "a" * 64,
            harness=HarnessSpec("static-candidate", "1"),
        )

    row = _row()
    row["image"]["platform_digest"] = f"sha256:{'0' * 64}"
    with pytest.raises(ContractError, match="image lock"):
        ProgramBenchOfficialSingleResolver().resolve(
            row,
            source_dir=_fixture(),
            episode_id="image-drift",
            inference_environment_id="inference",
            verification_environment_id="verification",
            verification_image="registry.invalid/evaluator@sha256:" + "a" * 64,
            harness=HarnessSpec("static-candidate", "1"),
        )

    source = tmp_path / "fixture"
    source.mkdir()
    for item in _fixture().iterdir():
        if item.is_file():
            (source / item.name).write_bytes(item.read_bytes())
    tests = json.loads((source / "tests.json").read_text(encoding="utf-8"))
    tests["branches"]["89bbe1810fa3"]["tests"].pop()
    (source / "tests.json").write_text(json.dumps(tests), encoding="utf-8")
    with pytest.raises(ContractError, match="digest mismatch"):
        ProgramBenchOfficialSingleResolver().resolve(
            _row(),
            source_dir=source,
            episode_id="tests-drift",
            inference_environment_id="inference",
            verification_environment_id="verification",
            verification_image="registry.invalid/evaluator@sha256:" + "a" * 64,
            harness=HarnessSpec("static-candidate", "1"),
        )


def test_official_episode_selects_the_closed_single_instance_adapters() -> None:
    selection = resolve_adapters(_episode())
    assert selection.task.name == "programbench-official-single"
    assert selection.verifier.name == "programbench-official-single"
    assert getattr(selection.verifier, "multi_run", False) is True


def test_sdk_reproducer_proves_released_surface_supports_derived_environment() -> None:
    script = (
        Path(__file__).parents[1]
        / "tools"
        / "reproducers"
        / "programbench_post_compile_snapshot.py"
    )
    completed = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    report = json.loads(completed.stdout)
    assert report["schema_version"] == 2
    assert report["axern_sdk_version"] == "0.11.2"
    assert report["supported"] is True
    assert report["capability"] == "post-compile-allocation-snapshot-v1"
    assert report["missing_capability"] == ""
    assert report["create_run_rootfs_snapshot"] == {"default": False, "present": True}
    assert report["wait_rootfs_snapshot"] == {
        "parameters": ["self", "run_id", "timeout"],
        "present": True,
    }
    assert "create_run" in report["public_axern_client_methods"]
    assert "wait_rootfs_snapshot" in report["public_axern_client_methods"]


def test_reproducer_imports_only_public_sdk_symbols() -> None:
    script = (
        Path(__file__).parents[1]
        / "tools"
        / "reproducers"
        / "programbench_post_compile_snapshot.py"
    )
    source = script.read_text(encoding="utf-8")
    assert "from axern_sdk import AxernClient" in source
    assert "_pb2" not in source
    assert "axern." not in source
