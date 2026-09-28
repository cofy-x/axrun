"""Closed-contract tests; synthetic row text is not an official benchmark asset."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from flask_admission_fixtures import pin_synthetic_row, write_receipt

from axrun.datasets import swebench_flask_official as flask
from axrun.errors import ContractError
from axrun.models import HarnessSpec, StageNetworkPolicy, canonical_digest

_IMPORTED = f"index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:{'9' * 64}"


def _row() -> dict[str, Any]:
    return {
        "FAIL_TO_PASS": ["synthetic_fail_to_pass"],
        "PASS_TO_PASS": [f"synthetic_pass_to_pass_{index}" for index in range(59)],
        "base_commit": "7ee9ceb71e868944a46e1ff00b506772a53a4f1d",
        "created_at": "2024-01-01T00:00:00Z",
        "difficulty": "synthetic",
        "environment_setup_commit": "a" * 40,
        "eval_script": "#!/bin/bash\necho offline-fixture\n",
        "eval_type": "pass_and_fail",
        "hints_text": "HINT-SENTINEL-NEVER-TO-PROMPT",
        "image": "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest",
        "instance_id": "pallets__flask-5014",
        "log_parser": "parse_log_flask",
        "patch": "GOLD-SENTINEL-NEVER-TO-CONFIG",
        "problem_statement": "Fix only the synthetic prompt text.",
        "repo": "pallets/flask",
        "test_patch": "TEST-PATCH-SENTINEL-NEVER-TO-CONFIG",
        "version": "2.3",
    }


def _receipt() -> dict[str, str]:
    return {
        "source_ref": flask._SOURCE_IMAGE,
        "canonical_ref": flask._CANONICAL_SOURCE_IMAGE,
        "immutable_ref": _IMPORTED,
        "content_digest": f"sha256:{'9' * 64}",
        "platform": "linux/amd64",
    }


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    row = _row()
    pin_synthetic_row(row, monkeypatch)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    fake_wheels = (
        ("setuptools-70.0.0-py3-none-any.whl", b"setuptools"),
        ("wheel-0.45.1-py3-none-any.whl", b"wheel"),
    )
    for name, payload in fake_wheels:
        (wheelhouse / name).write_bytes(payload)
    monkeypatch.setattr(
        flask,
        "_LOCKED_WHEELS",
        tuple(
            (name, len(payload), hashlib.sha256(payload).hexdigest())
            for name, payload in fake_wheels
        ),
    )
    candidate = tmp_path / "synthetic.patch"
    candidate.write_bytes(b"synthetic candidate bytes\n")
    return {
        "row": row,
        "asset_dir": tmp_path / "assets",
        "episode_id": "flask-stage-zero",
        "inference_environment_id": "env-inference",
        "verification_environment_id": "env-verification",
        "task_image": _IMPORTED,
        "image_import_receipt": _receipt(),
        "admission_receipt_file": write_receipt(tmp_path / "admission.json"),
        "wheelhouse_dir": wheelhouse,
        "harness": HarnessSpec("static-candidate", "1"),
        "static_candidate_file": candidate,
    }


def test_official_lock_constants_are_pinned() -> None:
    assert flask._ROW_SHA256 == "36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e"
    assert (
        flask._EVAL_SCRIPT_SHA256
        == "a752d2d3520db71513c263dd476e8da457395a447a346f6b5c18782dc0faf034"
    )
    assert flask._SOURCE_IMAGE.endswith(
        "@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4"
    )
    assert flask._DATASET_COMMIT == "78f471bf655a3137b2e8a75af1501690ec009ec3"


def test_resolver_commits_complete_row_and_leaks_no_reference_content(
    inputs: dict[str, Any],
) -> None:
    row = inputs["row"]
    episode = flask.SweBenchFlaskOfficialResolver().resolve(**inputs)
    same_row_other_episode = flask.SweBenchFlaskOfficialResolver().resolve(
        **{**inputs, "episode_id": "another-episode"}
    )
    assert episode.seed_digest == same_row_other_episode.seed_digest
    assert episode.seed_digest == canonical_digest(
        {
            "dataset_identity": flask._DATASET,
            "dataset_commit": flask._DATASET_COMMIT,
            "row_schema": flask._SCHEMA,
            "row": row,
        }
    )
    assert episode.schema_version == 2
    assert episode.inference_network_policy == StageNetworkPolicy.DENY_ALL
    assert episode.verification_network_policy == StageNetworkPolicy.DENY_ALL
    assert episode.task.identity == "swebench-flask-official"
    assert episode.task.config["base_commit"] == flask._IMAGE_HEAD
    assert set(episode.task.config) == {
        "base_commit",
        "admission_receipt_file",
        "admission_receipt_sha256",
    }
    admission = Path(episode.task.config["admission_receipt_file"])
    assert admission.read_bytes() == inputs["admission_receipt_file"].read_bytes()
    assert (
        hashlib.sha256(admission.read_bytes()).hexdigest()
        == episode.task.config["admission_receipt_sha256"]
    )
    assert episode.metadata["official_row_base_commit"] == row["base_commit"]
    assert episode.metadata["official_image_head"] == flask._IMAGE_HEAD
    assert episode.inference_environment.image == _IMPORTED
    assert episode.verification_environment.image == _IMPORTED
    assert episode.inference_environment.platform == "linux/amd64"
    assert episode.inference_environment.working_directory == "/testbed"
    assert episode.candidate.identity == "git-patch"
    assert episode.harness.identity == "static-candidate"
    assert episode.verifier.identity == "swebench-flask-official"
    assert episode.verifier.config["eval_timeout_seconds"] == 1800
    assert episode.verifier.timeout_seconds == 1860
    assert Path(episode.prompt_file).read_text() == row["problem_statement"]
    assert Path(episode.verifier.config["eval_script_file"]).read_text() == row["eval_script"]
    assert hashlib.sha256(row["problem_statement"].encode()).hexdigest() in episode.prompt_file
    assert (
        hashlib.sha256(row["eval_script"].encode()).hexdigest()
        in episode.verifier.config["eval_script_file"]
    )
    assert (
        Path(episode.candidate.config["source_file"]).read_bytes() == b"synthetic candidate bytes\n"
    )
    serialized = json.dumps(asdict(episode), sort_keys=True)
    for private in (row["patch"], row["test_patch"], row["hints_text"]):
        assert private not in serialized
        assert private not in Path(episode.prompt_file).read_text()
    inputs["static_candidate_file"].write_bytes(b"later mutation")
    assert (
        Path(episode.candidate.config["source_file"]).read_bytes() == b"synthetic candidate bytes\n"
    )


def test_claude_harness_is_closed_and_model_aliases_materialize(
    inputs: dict[str, Any],
) -> None:
    harness = HarnessSpec(
        "claude-code",
        "2.1.205",
        config={
            "mount_image": f"index.docker.io/axrun/claude-rootfs@sha256:{'a' * 64}",
            "model": "opaque-model",
            "working_directory": "/testbed",
        },
    )
    episode = flask.SweBenchFlaskOfficialResolver().resolve(
        **{**inputs, "harness": harness, "static_candidate_file": None}
    )
    assert episode.candidate.config == {}
    assert episode.harness.config["default_opus_model"] == "opaque-model"
    assert episode.harness.config["default_sonnet_model"] == "opaque-model"
    assert episode.harness.config["default_haiku_model"] == "opaque-model"
    assert episode.harness.config["subagent_model"] == "opaque-model"
    assert episode.harness.config["disallowed_tools"] == ["WebFetch", "WebSearch"]
    with pytest.raises(ContractError, match="static candidate"):
        flask.SweBenchFlaskOfficialResolver().resolve(**{**inputs, "harness": harness})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("instance_id", "other__flask-5014", "instance_id"),
        ("image", "swebench/flask:latest", "image"),
        ("base_commit", "0" * 40, "base_commit"),
        ("log_parser", "parse_log_django", "log_parser"),
        ("eval_script", "changed script", "eval script"),
        ("PASS_TO_PASS", ["one"], "59 tests"),
    ],
)
def test_row_drift_fails_closed(
    inputs: dict[str, Any], field: str, value: object, message: str
) -> None:
    row = dict(inputs["row"])
    row[field] = value
    with pytest.raises(ContractError, match=message):
        flask.SweBenchFlaskOfficialResolver().resolve(**{**inputs, "row": row})


def test_full_row_digest_and_unknown_fields_fail_closed(inputs: dict[str, Any]) -> None:
    row = dict(inputs["row"], created_at="different time")
    with pytest.raises(ContractError, match="row digest"):
        flask.SweBenchFlaskOfficialResolver().resolve(**{**inputs, "row": row})
    with pytest.raises(ContractError, match="invalid shape"):
        flask.SweBenchFlaskOfficialResolver().resolve(
            **{**inputs, "row": dict(inputs["row"], unknown="x")}
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_ref", "docker.io/swebench/flask:latest", "source/platform"),
        ("canonical_ref", "index.docker.io/other@sha256:" + "a" * 64, "source/platform"),
        ("platform", "linux/arm64", "source/platform"),
        ("content_digest", "sha256:" + "a" * 64, "content digest"),
        ("immutable_ref", "index.docker.io/other@sha256:" + "a" * 64, "import receipt"),
    ],
)
def test_public_import_receipt_drift_fails_closed(
    inputs: dict[str, Any], field: str, value: str, message: str
) -> None:
    receipt = dict(inputs["image_import_receipt"], **{field: value})
    with pytest.raises(ContractError, match=message):
        flask.SweBenchFlaskOfficialResolver().resolve(**{**inputs, "image_import_receipt": receipt})


def test_mutable_image_and_receipt_extension_fail_closed(inputs: dict[str, Any]) -> None:
    with pytest.raises(ContractError, match="immutable OCI digest"):
        flask.SweBenchFlaskOfficialResolver().resolve(
            **{**inputs, "task_image": "index.docker.io/swebench/flask:latest"}
        )
    with pytest.raises(ContractError, match="invalid shape"):
        flask.SweBenchFlaskOfficialResolver().resolve(
            **{
                **inputs,
                "image_import_receipt": dict(inputs["image_import_receipt"], private_host="x"),
            }
        )


def test_wheelhouse_and_static_candidate_fail_closed(
    inputs: dict[str, Any], tmp_path: Path
) -> None:
    wheel = inputs["wheelhouse_dir"] / "wheel-0.45.1-py3-none-any.whl"
    wheel.write_bytes(b"other")
    with pytest.raises(ContractError, match="differs from lock"):
        flask.SweBenchFlaskOfficialResolver().resolve(**inputs)
    wheel.write_bytes(b"wheel")
    extra = inputs["wheelhouse_dir"] / "extra.whl"
    extra.write_bytes(b"x")
    with pytest.raises(ContractError, match="entries differ"):
        flask.SweBenchFlaskOfficialResolver().resolve(**inputs)
    extra.unlink()
    pointer = tmp_path / "candidate-link.patch"
    pointer.symlink_to(inputs["static_candidate_file"])
    with pytest.raises(ContractError, match="regular file"):
        flask.SweBenchFlaskOfficialResolver().resolve(
            **{**inputs, "static_candidate_file": pointer}
        )


def test_same_environment_and_missing_static_candidate_fail_closed(inputs: dict[str, Any]) -> None:
    with pytest.raises(ContractError, match="distinct Environment"):
        flask.SweBenchFlaskOfficialResolver().resolve(
            **{**inputs, "verification_environment_id": "env-inference"}
        )
    with pytest.raises(ContractError, match="explicit patch file"):
        flask.SweBenchFlaskOfficialResolver().resolve(**{**inputs, "static_candidate_file": None})
