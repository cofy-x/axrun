"""Closed resolver for the admitted django__django-12419 amd64 vertical.

Only the locked problem statement and evaluator script are materialized. The
gold patch, test patch, and hints remain in the caller's private row; neither
the prompt nor the resolved episode contains those bodies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError
from axrun.models import (
    CandidateSpec,
    EnvironmentBinding,
    HarnessSpec,
    ResolvedEpisode,
    StageNetworkPolicy,
    TaskSpec,
    VerifierSpec,
    canonical_digest,
)

DATASET = "SWE-bench/SWE-bench_Verified"
DATASET_COMMIT = "91aa3ed51b709be6457e12d00300a6a596d4c6a3"
SCHEMA = "enriched-v1"
HARNESS_COMMIT = "f7bbbb2ccdf479001d6467c9e34af59e44a840f9"
INSTANCE = "django__django-12419"
ROW_SHA256 = "6eea69026b82f8c17d1c2e299d39fada46d60acf6a9f39a4de20ab84749f1d37"
SEED_DIGEST = "b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471"
PROMPT_SHA256 = "1f07796a60c95eb7974ea0084d52158fa47471e45dff3dde4ad328aeff3a17f6"
TEST_SELECTION_DIGEST = "452bd1de2fd32e99ec6f365e0dc44a09212104be795b7904965b3cfedae7a23a"
EVAL_SCRIPT_SHA256 = "da94f6e6b371f5f4f929fd0e71d2de2aa38427429380e7a18dfdc4498e5e5cd7"
GOLD_PATCH_SHA256 = "a1f6c1f9598eda33d4de4b85f018d759390b8e6c951af3f554b9df5b90ff7862"
TEST_PATCH_SHA256 = "ee1374e13a6aaff38f08d96759e2f3d51a9c6d39a8b8820e30c9e74c4293af97"
SOURCE_IMAGE = (
    "docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419"
    "@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768"
)
TASK_IMAGE = (
    "index.docker.io/library/axrun-django-seed-0121"
    "@sha256:3912793ab27162e63adec6835a9267b150341b9b5cba1532e6d7ac8933c8cbb6"
)
IMAGE_HEAD = "7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
ROW_IMAGE = "swebench/sweb.eval.x86_64.django_1776_django-12419:latest"
IMPORT_RECEIPT_SHA256 = "fd6ac363b9c0d0f8cc9cb5f092d3dec90b7990cb54d37d3daba696a56ab7a8ab"
ADMISSION_RECEIPT_SHA256 = "4048174c34249a072649c1bf887a9f710243ad67212b8486e765040e65be7c6e"
_ROW_FIELDS = frozenset(
    {
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "base_commit",
        "created_at",
        "difficulty",
        "environment_setup_commit",
        "eval_script",
        "eval_type",
        "hints_text",
        "image",
        "instance_id",
        "log_parser",
        "patch",
        "problem_statement",
        "repo",
        "test_patch",
        "version",
    }
)
_IMPORT_FIELDS = {
    "source_ref",
    "canonical_ref",
    "immutable_ref",
    "content_digest",
    "archive_digest",
    "platform",
    "size_bytes",
    "reused",
}
_IMPORT_SOURCE = "axrun-django-seed-0121:ielv1j-v2"
_IMPORT_CANONICAL = "index.docker.io/library/" + _IMPORT_SOURCE
_IMPORT_ARCHIVE_DIGEST = "sha256:78bdf5b873b07bf470b122b7f5b75a347ffa2083cddbc7187d3118636a01c05c"


def admission_contract() -> dict[str, str]:
    """Public, non-sensitive identities for the one locked task."""
    return {
        "DATASET": DATASET,
        "DATASET_COMMIT": DATASET_COMMIT,
        "SCHEMA": SCHEMA,
        "HARNESS_COMMIT": HARNESS_COMMIT,
        "INSTANCE": INSTANCE,
        "ROW_SHA256": ROW_SHA256,
        "SEED_DIGEST": SEED_DIGEST,
        "PROMPT_SHA256": PROMPT_SHA256,
        "TEST_SELECTION_DIGEST": TEST_SELECTION_DIGEST,
        "EVAL_SCRIPT_SHA256": EVAL_SCRIPT_SHA256,
        "GOLD_PATCH_SHA256": GOLD_PATCH_SHA256,
        "TEST_PATCH_SHA256": TEST_PATCH_SHA256,
        "SOURCE_IMAGE": SOURCE_IMAGE,
        "TASK_IMAGE": TASK_IMAGE,
        "IMAGE_HEAD": IMAGE_HEAD,
        "IMPORT_RECEIPT_SHA256": IMPORT_RECEIPT_SHA256,
        "ADMISSION_RECEIPT_SHA256": ADMISSION_RECEIPT_SHA256,
        "PLATFORM": "linux/amd64",
    }


def checked_django_row(
    row: dict[str, Any],
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    if set(row) != set(_ROW_FIELDS):
        raise ContractError("official Django enriched row has an invalid shape")
    strings: dict[str, str] = {}
    for key in _ROW_FIELDS - {"FAIL_TO_PASS", "PASS_TO_PASS"}:
        value = row[key]
        if not isinstance(value, str) or (not value and key != "hints_text"):
            raise ContractError(f"official Django row {key} must be a string")
        strings[key] = value
    expected = {
        "instance_id": INSTANCE,
        "repo": "django/django",
        "base_commit": IMAGE_HEAD,
        "environment_setup_commit": "0668164b4ac93a5be79f5b87fae83c657124d9ab",
        "version": "3.1",
        "image": ROW_IMAGE,
        "eval_type": "pass_and_fail",
        "log_parser": "parse_log_django",
    }
    if any(strings[key] != value for key, value in expected.items()):
        raise ContractError("official Django row identity differs from lock")
    if re.fullmatch(r"[0-9a-f]{40}", strings["base_commit"]) is None:
        raise ContractError("official Django base commit is malformed")
    fail_to_pass = _tests(row["FAIL_TO_PASS"], "FAIL_TO_PASS", 1)
    pass_to_pass = _tests(row["PASS_TO_PASS"], "PASS_TO_PASS", 0)
    if set(fail_to_pass) & set(pass_to_pass):
        raise ContractError("official Django expected test classes overlap")
    if (
        canonical_digest({"fail_to_pass": fail_to_pass, "pass_to_pass": pass_to_pass})
        != TEST_SELECTION_DIGEST
    ):
        raise ContractError("official Django test selection differs from lock")
    for key, digest in (
        ("problem_statement", PROMPT_SHA256),
        ("eval_script", EVAL_SCRIPT_SHA256),
        ("patch", GOLD_PATCH_SHA256),
        ("test_patch", TEST_PATCH_SHA256),
    ):
        if hashlib.sha256(strings[key].encode()).hexdigest() != digest:
            raise ContractError(f"official Django {key} differs from lock")
    if canonical_digest(row) != ROW_SHA256:
        raise ContractError("official Django enriched row digest differs from lock")
    return strings, fail_to_pass, pass_to_pass


def _tests(value: object, name: str, expected: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractError(f"official Django {name} must contain {expected} tests")
    tests = cast(list[object], value)
    if len(tests) != expected:
        raise ContractError(f"official Django {name} must contain {expected} tests")
    if any(not isinstance(item, str) or not item for item in tests):
        raise ContractError(f"official Django {name} must contain strings")
    result = tuple(cast(list[str], tests))
    if len(set(result)) != len(result):
        raise ContractError(f"official Django {name} contains duplicates")
    return result


def _checked_json(path: Path, *, max_bytes: int) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            raise ContractError("Django receipt must be a regular file")
        if path.stat().st_size > max_bytes:
            raise ContractError("Django receipt exceeds its bound")
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError("Django receipt is unavailable") from exc
    if len(payload) > max_bytes:
        raise ContractError("Django receipt exceeds its bound")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ContractError("Django receipt contains duplicate fields")
            result[key] = value
        return result

    def reject(_value: str) -> None:
        raise ContractError("Django receipt contains a non-finite value")

    try:
        value: object = json.loads(payload, object_pairs_hook=pairs, parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("Django receipt is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("Django receipt must be a JSON object")
    return cast(dict[str, Any], value), payload


def checked_django_import_receipt(path: Path, task_image: str) -> dict[str, Any]:
    if task_image != TASK_IMAGE:
        raise ContractError("Django task image differs from the admitted immutable runtime")
    receipt, payload = _checked_json(path, max_bytes=128 << 10)
    if hashlib.sha256(payload).hexdigest() != IMPORT_RECEIPT_SHA256:
        raise ContractError("Django image import receipt SHA-256 differs from lock")
    if set(receipt) != _IMPORT_FIELDS:
        raise ContractError("Django image import receipt has an invalid shape")
    expected: dict[str, Any] = {
        "source_ref": _IMPORT_SOURCE,
        "canonical_ref": _IMPORT_CANONICAL,
        "immutable_ref": TASK_IMAGE,
        "content_digest": TASK_IMAGE.rsplit("@", 1)[-1],
        "archive_digest": _IMPORT_ARCHIVE_DIGEST,
        "platform": "linux/amd64",
        "size_bytes": 1_155_144_704,
        "reused": False,
    }
    if receipt != expected or any(
        type(receipt[key]) is not type(value) for key, value in expected.items()
    ):
        raise ContractError("Django image import receipt differs from the accepted seed")
    return receipt


def checked_private_directory(directory: Path) -> None:
    """Keep verifier-only material out of Git and inaccessible to other users."""
    if not directory.is_absolute():
        raise ContractError("Django private directory must be absolute")
    try:
        metadata = directory.lstat()
    except OSError as exc:
        raise ContractError("Django private directory must already exist") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ContractError("Django private directory must be owned and mode 0700")
    for ancestor in (directory, *directory.parents):
        if ancestor.is_symlink() or (ancestor / ".git").exists():
            raise ContractError("Django private directory cannot be symlinked or inside Git")


def _materialize(directory: Path, stem: str, suffix: str, payload: bytes) -> Path:
    if not directory.is_absolute() or directory.is_symlink():
        raise ContractError("Django asset directory must be absolute and not symlinked")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    checked_private_directory(directory)
    destination = directory / f"{stem}-{hashlib.sha256(payload).hexdigest()}{suffix}"
    if destination.exists() or destination.is_symlink():
        try:
            fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as source:
                metadata = os.fstat(source.fileno())
                existing = source.read()
        except OSError as exc:
            raise ContractError(f"Django materialized {stem} asset is unavailable") from exc
        if not (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.geteuid()
            and stat.S_IMODE(metadata.st_mode) == 0o600
            and existing == payload
        ):
            raise ContractError(f"Django materialized {stem} asset differs")
        return destination
    created = False
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        if created:
            destination.unlink(missing_ok=True)
        raise ContractError(f"Django materialized {stem} asset could not be written") from exc
    return destination


def _candidate_file(path: Path) -> bytes:
    checked_private_directory(path.parent)
    if path.is_symlink():
        raise ContractError("Django static candidate must be a regular file")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise ContractError("Django static candidate must be an owned regular file")
            if stat.S_IMODE(metadata.st_mode) != 0o600:
                raise ContractError("Django static candidate must be mode 0600")
            if metadata.st_size > 64 << 20:
                raise ContractError("Django static candidate exceeds 64 MiB")
            payload = source.read((64 << 20) + 1)
            if len(payload) > 64 << 20:
                raise ContractError("Django static candidate exceeds 64 MiB")
            return payload
    except OSError as exc:
        raise ContractError("Django static candidate is unavailable") from exc


class SweBenchDjangoOfficialResolver:
    """Resolve exactly one pinned row, image, admission, and static candidate."""

    identity = DATASET
    version = SCHEMA

    def resolve(
        self,
        row: dict[str, Any],
        *,
        asset_dir: Path,
        episode_id: str,
        inference_environment_id: str,
        verification_environment_id: str,
        task_image: str,
        image_import_receipt_file: Path,
        admission_receipt_file: Path,
        static_candidate_file: Path,
    ) -> ResolvedEpisode:
        checked_private_directory(asset_dir)
        strings, _, _ = checked_django_row(row)
        checked_django_import_receipt(image_import_receipt_file, task_image)
        if inference_environment_id == verification_environment_id:
            raise ContractError("Django verification requires a distinct Environment")
        from axrun.tasks.django_admission import load_django_admission

        load_django_admission(admission_receipt_file, task_image=task_image)
        seed_digest = canonical_digest({"dataset": DATASET, "row_schema": SCHEMA, "row": row})
        if seed_digest != SEED_DIGEST:
            raise ContractError("official Django seed differs from lock")
        assets = asset_dir / seed_digest
        prompt = _materialize(assets, "problem", ".txt", strings["problem_statement"].encode())
        eval_script = _materialize(assets, "eval", ".sh", strings["eval_script"].encode())
        admission_payload = admission_receipt_file.read_bytes()
        admission = _materialize(assets, "admission", ".json", admission_payload)
        candidate = _materialize(
            assets / "static-candidates",
            "candidate",
            ".patch",
            _candidate_file(static_candidate_file),
        )
        verifier = (
            Path(__file__).parents[1] / "fixtures" / "swebench_django_official" / "run_verifier.py"
        )
        if not verifier.is_file() or verifier.is_symlink():
            raise ContractError("packaged Django verifier is missing")
        return ResolvedEpisode(
            schema_version=2,
            episode_id=episode_id,
            task_id=INSTANCE,
            seed_digest=seed_digest,
            prompt_file=str(prompt),
            task=TaskSpec(
                identity="swebench-django-official",
                version="1",
                config={
                    "base_commit": IMAGE_HEAD,
                    "admission_receipt_file": str(admission),
                    "admission_receipt_sha256": ADMISSION_RECEIPT_SHA256,
                },
            ),
            inference_environment=EnvironmentBinding(
                inference_environment_id, task_image, "linux/amd64", "/testbed"
            ),
            verification_environment=EnvironmentBinding(
                verification_environment_id, task_image, "linux/amd64", "/testbed"
            ),
            harness=HarnessSpec("static-candidate", "1"),
            candidate=CandidateSpec("git-patch", "1", {"source_file": str(candidate)}),
            verifier=VerifierSpec(
                identity="swebench-django-official",
                version="1",
                timeout_seconds=1860,
                config={
                    "verifier_file": str(verifier),
                    "eval_script_file": str(eval_script),
                    "eval_script_sha256": EVAL_SCRIPT_SHA256,
                    "test_selection_digest": TEST_SELECTION_DIGEST,
                    "log_parser": "parse_log_django",
                    "harness_commit": HARNESS_COMMIT,
                    "instance_id": INSTANCE,
                    "eval_timeout_seconds": 1800,
                },
            ),
            inference_network_policy=StageNetworkPolicy.DENY_ALL,
            verification_network_policy=StageNetworkPolicy.DENY_ALL,
            metadata={
                "dataset_identity": DATASET,
                "dataset_commit": DATASET_COMMIT,
                "dataset_version": SCHEMA,
                "official_row_sha256": ROW_SHA256,
                "official_row_base_commit": IMAGE_HEAD,
                "official_image_head": IMAGE_HEAD,
                "official_source_image": SOURCE_IMAGE,
                "task_image": task_image,
                "task_platform": "linux/amd64",
                "official_instance_scope": "locked-single-instance",
            },
        )
