"""Synthetic contract tests; no official row, patch, or hidden test is checked in."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from axrun.datasets import swebench_django_official as django
from axrun.errors import ContractError
from axrun.models import StageNetworkPolicy, TaskSpec, canonical_digest, canonical_json
from axrun.tasks import django_admission


def _row() -> dict[str, Any]:
    return {
        "FAIL_TO_PASS": ["synthetic_expected_test"],
        "PASS_TO_PASS": [],
        "base_commit": django.IMAGE_HEAD,
        "created_at": "2024-01-01T00:00:00Z",
        "difficulty": "synthetic",
        "environment_setup_commit": "0668164b4ac93a5be79f5b87fae83c657124d9ab",
        "eval_script": "#!/bin/bash\necho synthetic-eval\n",
        "eval_type": "pass_and_fail",
        "hints_text": "HINT-SENTINEL-NEVER-TO-EPISODE",
        "image": django.ROW_IMAGE,
        "instance_id": django.INSTANCE,
        "log_parser": "parse_log_django",
        "patch": "GOLD-SENTINEL-NEVER-TO-EPISODE",
        "problem_statement": "Fix the synthetic Django bug.",
        "repo": "django/django",
        "test_patch": "TEST-PATCH-SENTINEL-NEVER-TO-EPISODE",
        "version": "3.1",
    }


def _import_receipt() -> dict[str, Any]:
    return {
        "source_ref": "axrun-django-seed-0121:ielv1j-v2",
        "canonical_ref": "index.docker.io/library/axrun-django-seed-0121:ielv1j-v2",
        "immutable_ref": django.TASK_IMAGE,
        "content_digest": django.TASK_IMAGE.rsplit("@", 1)[-1],
        "archive_digest": django._IMPORT_ARCHIVE_DIGEST,
        "platform": "linux/amd64",
        "size_bytes": 1_155_144_704,
        "reused": False,
    }


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    row = _row()
    for field, digest in (
        ("PROMPT_SHA256", hashlib.sha256(row["problem_statement"].encode()).hexdigest()),
        ("EVAL_SCRIPT_SHA256", hashlib.sha256(row["eval_script"].encode()).hexdigest()),
        ("GOLD_PATCH_SHA256", hashlib.sha256(row["patch"].encode()).hexdigest()),
        ("TEST_PATCH_SHA256", hashlib.sha256(row["test_patch"].encode()).hexdigest()),
        ("ROW_SHA256", canonical_digest(row)),
        (
            "TEST_SELECTION_DIGEST",
            canonical_digest(
                {"fail_to_pass": row["FAIL_TO_PASS"], "pass_to_pass": row["PASS_TO_PASS"]}
            ),
        ),
        (
            "SEED_DIGEST",
            canonical_digest({"dataset": django.DATASET, "row_schema": django.SCHEMA, "row": row}),
        ),
    ):
        monkeypatch.setattr(django, field, digest)
    import_file = tmp_path / "image-import.json"
    import_file.write_bytes(canonical_json(_import_receipt()) + b"\n")
    monkeypatch.setattr(
        django, "IMPORT_RECEIPT_SHA256", hashlib.sha256(import_file.read_bytes()).hexdigest()
    )
    admission_file = tmp_path / "admission.json"
    admission_file.write_bytes(b'{"synthetic":"receipt"}\n')
    monkeypatch.setattr(
        django, "ADMISSION_RECEIPT_SHA256", hashlib.sha256(admission_file.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(
        django_admission,
        "load_django_admission",
        lambda path, *, task_image, expected_sha256="": {"status": "passed"},
    )
    candidate = tmp_path / "candidate.patch"
    candidate.write_bytes(b"synthetic candidate patch\n")
    candidate.chmod(0o600)
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir(mode=0o700)
    return {
        "row": row,
        "asset_dir": asset_dir,
        "episode_id": "django-locked-synthetic",
        "inference_environment_id": "env-inference",
        "verification_environment_id": "env-verification",
        "task_image": django.TASK_IMAGE,
        "image_import_receipt_file": import_file,
        "admission_receipt_file": admission_file,
        "static_candidate_file": candidate,
    }


def test_public_lock_constants_are_fixed() -> None:
    assert django.ROW_SHA256 == "6eea69026b82f8c17d1c2e299d39fada46d60acf6a9f39a4de20ab84749f1d37"
    assert django.SEED_DIGEST == "b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471"
    assert (
        django.TEST_SELECTION_DIGEST
        == "452bd1de2fd32e99ec6f365e0dc44a09212104be795b7904965b3cfedae7a23a"
    )
    assert django.TASK_IMAGE.endswith(
        "@sha256:3912793ab27162e63adec6835a9267b150341b9b5cba1532e6d7ac8933c8cbb6"
    )


def test_resolver_materializes_only_allowed_assets(inputs: dict[str, Any]) -> None:
    episode = django.SweBenchDjangoOfficialResolver().resolve(**inputs)
    another = django.SweBenchDjangoOfficialResolver().resolve(
        **{**inputs, "episode_id": "another-django-episode"}
    )
    assert episode.seed_digest == another.seed_digest == django.SEED_DIGEST
    assert episode.schema_version == 2
    assert episode.task.identity == "swebench-django-official"
    assert episode.verifier.identity == "swebench-django-official"
    assert episode.candidate.identity == "git-patch"
    assert episode.harness.identity == "static-candidate"
    assert episode.inference_network_policy == StageNetworkPolicy.DENY_ALL
    assert episode.verification_network_policy == StageNetworkPolicy.DENY_ALL
    assert (
        episode.inference_environment.environment_id
        != episode.verification_environment.environment_id
    )
    assert (
        episode.inference_environment.image
        == episode.verification_environment.image
        == django.TASK_IMAGE
    )
    assert Path(episode.prompt_file).read_text() == inputs["row"]["problem_statement"]
    assert (
        Path(episode.verifier.config["eval_script_file"]).read_text()
        == inputs["row"]["eval_script"]
    )
    assert (
        Path(episode.candidate.config["source_file"]).read_bytes() == b"synthetic candidate patch\n"
    )
    assert (
        Path(episode.task.config["admission_receipt_file"]).read_bytes()
        == inputs["admission_receipt_file"].read_bytes()
    )
    serialized = json.dumps(asdict(episode), sort_keys=True)
    for hidden in (
        inputs["row"]["FAIL_TO_PASS"][0],
        inputs["row"]["patch"],
        inputs["row"]["test_patch"],
        inputs["row"]["hints_text"],
    ):
        assert hidden not in serialized
        assert hidden not in Path(episode.prompt_file).read_text()
    inputs["static_candidate_file"].write_bytes(b"later mutation")
    assert (
        Path(episode.candidate.config["source_file"]).read_bytes() == b"synthetic candidate patch\n"
    )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("instance_id", "foreign__django-12419"),
        ("image", "other:latest"),
        ("base_commit", "0" * 40),
        ("log_parser", "parse_log_flask"),
        ("FAIL_TO_PASS", ["replacement_expected_test"]),
        ("PASS_TO_PASS", ["unexpected_test"]),
        ("eval_script", "changed"),
        ("created_at", "changed"),
    ],
)
def test_row_drift_fails_closed(inputs: dict[str, Any], field: str, bad: object) -> None:
    row = dict(inputs["row"], **{field: bad})
    with pytest.raises(ContractError):
        django.SweBenchDjangoOfficialResolver().resolve(**{**inputs, "row": row})


def test_unknown_row_field_and_same_environment_fail_closed(inputs: dict[str, Any]) -> None:
    with pytest.raises(ContractError, match="invalid shape"):
        django.SweBenchDjangoOfficialResolver().resolve(
            **{**inputs, "row": dict(inputs["row"], extra="x")}
        )
    with pytest.raises(ContractError, match="distinct Environment"):
        django.SweBenchDjangoOfficialResolver().resolve(
            **{**inputs, "verification_environment_id": "env-inference"}
        )


def test_import_receipt_requires_exact_bytes_and_runtime(inputs: dict[str, Any]) -> None:
    receipt = inputs["image_import_receipt_file"]
    payload = receipt.read_bytes()
    receipt.write_bytes(payload + b" ")
    with pytest.raises(ContractError, match="SHA-256"):
        django.SweBenchDjangoOfficialResolver().resolve(**inputs)
    receipt.write_bytes(payload)
    with pytest.raises(ContractError, match="runtime"):
        django.SweBenchDjangoOfficialResolver().resolve(
            **{**inputs, "task_image": "index.docker.io/library/other@sha256:" + "0" * 64}
        )


def test_static_candidate_symlink_fails_closed(inputs: dict[str, Any], tmp_path: Path) -> None:
    pointer = tmp_path / "candidate-link.patch"
    pointer.symlink_to(inputs["static_candidate_file"])
    with pytest.raises(ContractError, match="regular file"):
        django.SweBenchDjangoOfficialResolver().resolve(
            **{**inputs, "static_candidate_file": pointer}
        )


def test_private_materialization_rejects_public_directory_and_existing_file(
    inputs: dict[str, Any], tmp_path: Path
) -> None:
    directory = inputs["asset_dir"]
    directory.chmod(0o755)
    with pytest.raises(ContractError, match="mode 0700"):
        django.SweBenchDjangoOfficialResolver().resolve(**inputs)
    directory.chmod(0o700)
    episode = django.SweBenchDjangoOfficialResolver().resolve(**inputs)
    eval_script = Path(episode.verifier.config["eval_script_file"])
    assert stat.S_IMODE(eval_script.stat().st_mode) == 0o600
    eval_script.chmod(0o644)
    with pytest.raises(ContractError, match="materialized eval asset differs"):
        django.SweBenchDjangoOfficialResolver().resolve(**inputs)


def test_private_materialization_rejects_git_and_public_candidate(
    inputs: dict[str, Any], tmp_path: Path
) -> None:
    candidate = inputs["static_candidate_file"]
    candidate.chmod(0o644)
    with pytest.raises(ContractError, match="mode 0600"):
        django.SweBenchDjangoOfficialResolver().resolve(**inputs)
    candidate.chmod(0o600)
    (tmp_path / ".git").mkdir()
    with pytest.raises(ContractError, match="inside Git"):
        django.SweBenchDjangoOfficialResolver().resolve(**inputs)


def test_task_admission_is_mandatory_even_for_legacy_adapter_override(
    inputs: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from axrun.catalog import resolve_required_admission, resolve_task
    from axrun.qualification import require_admission
    from axrun.store import EpisodeStore
    from axrun.tasks import swebench_django_official as task_module

    receipt = {
        "schema_version": "axrun.swebench-django-axern-runtime-probe@1",
        "runtime_image": django.TASK_IMAGE,
        "scanner_sha256": "0" * 64,
        "execution": {"environment_id": "env-a", "run_id": "run-a", "allocation_id": "alloc-a"},
        "sealed_sha256": "1" * 64,
        "sealed_size_bytes": 1428,
        "status": "passed",
        "reason_code": "no_locked_patch_signatures_reachable",
        "cleanup": "deleted_verified",
    }
    monkeypatch.setattr(task_module, "load_django_admission", lambda *_args, **_kwargs: receipt)
    monkeypatch.setattr(task_module, "validated_django_verifier_inputs", lambda _episode: None)
    episode = django.SweBenchDjangoOfficialResolver().resolve(**inputs)
    task = resolve_task(episode)
    assert isinstance(task, task_module.SweBenchDjangoOfficialTaskAdapter)
    assert isinstance(
        resolve_required_admission(episode), task_module.SweBenchDjangoOfficialTaskAdapter
    )
    assert task.admission_report(episode)["trust_boundary"] == "caller-owned-state"
    for role in ("inference", "verification"):
        requirement = task.qualification_requirements(episode, role)
        assert requirement.mode == "git" and requirement.base_commit == django.IMAGE_HEAD

    store = EpisodeStore(tmp_path / "state")
    for bad in (
        replace(
            episode, task=TaskSpec("swebench-verified", "1", {"base_commit": django.IMAGE_HEAD})
        ),
        replace(episode, task=replace(episode.task, version="2")),
        replace(episode, task_id="other__django-12419"),
        replace(episode, verification_network_policy="unrestricted"),
        replace(episode, verifier=replace(episode.verifier, version="2")),
    ):
        with pytest.raises(ContractError):
            require_admission(store, bad)


def test_cli_exposes_only_static_locked_django_resolver(
    inputs: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from axrun import cli, cli_resolve

    episode = django.SweBenchDjangoOfficialResolver().resolve(**inputs)
    row_file = tmp_path / "row.json"
    row_file.write_bytes(canonical_json(inputs["row"]) + b"\n")
    output = tmp_path / "episode.json"

    class Resolver:
        def resolve(self, row: dict[str, Any], **kwargs: Any) -> Any:
            assert row == inputs["row"]
            assert kwargs["task_image"] == django.TASK_IMAGE
            assert kwargs["static_candidate_file"] == inputs["static_candidate_file"]
            return episode

    monkeypatch.setattr(cli_resolve, "SweBenchDjangoOfficialResolver", Resolver)
    args = [
        "resolve-swebench-django-official",
        str(row_file),
        "--episode-id",
        episode.episode_id,
        "--candidate-file",
        str(inputs["static_candidate_file"]),
        "--assets-dir",
        str(inputs["asset_dir"]),
        "--task-image",
        django.TASK_IMAGE,
        "--image-import-receipt",
        str(inputs["image_import_receipt_file"]),
        "--admission-receipt",
        str(inputs["admission_receipt_file"]),
        "--inference-environment",
        "env-inference",
        "--verification-environment",
        "env-verification",
        "--output",
        str(output),
    ]
    assert cli.main(args) == 0
    assert json.loads(output.read_text())["task"]["identity"] == "swebench-django-official"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(SystemExit):
        cli._parser().parse_args([*args, "--harness", "claude-code"])
