"""Synthetic tests for the one approved Django receipt; no Axern or private assets."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, cast

import pytest

from axrun.errors import ContractError
from axrun.models import canonical_json
from axrun.tasks import django_admission as lock
from axrun.tasks import django_image_audit as scanner
from axrun.tasks import flask_image_audit as shared


def _audit() -> dict[str, Any]:
    audit_fields = cast(frozenset[str], shared.__dict__["_AUDIT_FIELDS"])
    bool_fields = cast(frozenset[str], shared.__dict__["_BOOL_FIELDS"])
    value: dict[str, Any] = {key: 0 for key in audit_fields}
    value.update({key: False for key in bool_fields})
    value.update(
        image_head=scanner.IMAGE_HEAD,
        image_clean=True,
        row_base_present=True,
        filesystem_scan_complete=True,
        git_all_object_scan_complete=True,
        test_patch_forward_applies=True,
        gold_patch_forward_applies=True,
        test_target_count=1,
        gold_target_count=1,
        added_target_count=0,
        modified_target_count=1,
        filesystem_entry_count=76_818,
        filesystem_regular_file_count=60_000,
        filesystem_regular_file_bytes=1_000_000_000,
        git_all_object_count=339_152,
        git_all_object_bytes=200_000_000,
    )
    return value


def _receipt() -> dict[str, Any]:
    return {
        "schema_version": lock.SCHEMA,
        "status": "passed",
        "reason_code": "no_locked_patch_signatures_reachable",
        "oracle_receipt_sha256": lock.ORACLE_RECEIPT_SHA256,
        "image_import_receipt_sha256": lock.IMAGE_IMPORT_RECEIPT_SHA256,
        "runtime_image": lock.RUNTIME_IMAGE,
        "seed_image_id": lock.SEED_IMAGE_ID,
        "row_sha256": lock.ROW_SHA256,
        "scanner_sha256": lock.SCANNER_SHA256,
        "execution": dict(lock.EXECUTION),
        "run_status": "RUN_STATUS_SUCCEEDED",
        "exit_code": 0,
        "sealed_sha256": "",
        "sealed_size_bytes": 0,
        "sealed_audit": _audit(),
        "cleanup": "deleted_verified",
    }


def _write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt: dict[str, Any]) -> Path:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / "receipt.json"
    sealed = (
        canonical_json(
            {"machine": "x86_64", "request_deleted": True, "audit": receipt["sealed_audit"]}
        )
        + b"\n"
    )
    receipt["sealed_sha256"] = hashlib.sha256(sealed).hexdigest()
    receipt["sealed_size_bytes"] = len(sealed)
    monkeypatch.setattr(lock, "SEALED_SHA256", receipt["sealed_sha256"])
    monkeypatch.setattr(lock, "SEALED_SIZE_BYTES", len(sealed))
    payload = canonical_json(receipt) + b"\n"
    path.write_bytes(payload)
    path.chmod(0o600)
    monkeypatch.setattr(lock, "RECEIPT_SHA256", hashlib.sha256(payload).hexdigest())
    return path


def test_approved_receipt_is_recomputed_locally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _receipt()
    path = _write(tmp_path, monkeypatch, receipt)
    assert (
        lock.load_django_admission(
            path, task_image=lock.RUNTIME_IMAGE, expected_sha256=lock.RECEIPT_SHA256
        )
        == receipt
    )
    with pytest.raises(ContractError, match="SHA-256"):
        lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE, expected_sha256="0" * 64)
    with pytest.raises(ContractError, match="task image"):
        lock.load_django_admission(
            path, task_image="index.docker.io/library/other@sha256:" + "0" * 64
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", "old"),
        ("status", "blocked"),
        ("reason_code", "scan_incomplete"),
        ("oracle_receipt_sha256", "0" * 64),
        ("image_import_receipt_sha256", "0" * 64),
        ("runtime_image", "wrong"),
        ("seed_image_id", "wrong"),
        ("row_sha256", "0" * 64),
        ("scanner_sha256", "0" * 64),
        ("run_status", "RUN_STATUS_FAILED"),
        ("exit_code", True),
        ("cleanup", "retained_for_ambiguous_run"),
    ],
)
def test_identity_or_outcome_tamper_fails_after_digest_repin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, value: object
) -> None:
    receipt = _receipt()
    receipt[key] = value
    path = _write(tmp_path, monkeypatch, receipt)
    with pytest.raises(ContractError):
        lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE)


@pytest.mark.parametrize("key", ["environment_id", "run_id", "allocation_id"])
def test_public_execution_identity_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    receipt = _receipt()
    receipt["execution"][key] = "wrong"
    path = _write(tmp_path, monkeypatch, receipt)
    with pytest.raises(ContractError, match="execution identity"):
        lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("filesystem_scan_complete", False),
        ("git_all_object_scan_complete", False),
        ("test_full_filesystem_match_count", 1),
        ("gold_all_git_object_match_count", 1),
        ("test_patch_reverse_applies", True),
        ("filesystem_entry_count", 76_817),
        ("git_all_object_count", 339_151),
    ],
)
def test_incomplete_or_reachable_sealed_audit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, value: object
) -> None:
    receipt = _receipt()
    receipt["sealed_audit"][key] = value
    path = _write(tmp_path, monkeypatch, receipt)
    with pytest.raises(ContractError):
        lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE)


def test_receipt_byte_tamper_and_shape_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _receipt()
    path = _write(tmp_path, monkeypatch, receipt)
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ContractError, match="SHA-256"):
        lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE)
    receipt = copy.deepcopy(_receipt())
    receipt["extra"] = "unknown"
    path = _write(tmp_path, monkeypatch, receipt)
    with pytest.raises(ContractError, match="shape"):
        lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE)


def test_duplicate_json_and_nonfinite_values_fail_even_with_recomputed_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, monkeypatch, _receipt())
    for payload in (b'{"a":1,"a":2}\n', b'{"a":NaN}\n'):
        path.write_bytes(payload)
        monkeypatch.setattr(lock, "RECEIPT_SHA256", hashlib.sha256(payload).hexdigest())
        with pytest.raises(ContractError):
            lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE)


def test_private_regular_file_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(tmp_path, monkeypatch, _receipt())
    path.chmod(0o644)
    with pytest.raises(ContractError, match="private"):
        lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE)
    path.chmod(0o600)
    link = path.with_name("receipt-link.json")
    link.symlink_to(path)
    with pytest.raises(ContractError, match="private"):
        lock.load_django_admission(link, task_image=lock.RUNTIME_IMAGE)


def test_scanner_implementation_drift_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, monkeypatch, _receipt())
    monkeypatch.setattr(scanner, "scanner_implementation_sha256", lambda: "0" * 64)
    with pytest.raises(ContractError, match="scanner implementation"):
        lock.load_django_admission(path, task_image=lock.RUNTIME_IMAGE)


def test_constants_are_exactly_the_recorded_approval() -> None:
    assert lock.RECEIPT_SHA256 == "4048174c34249a072649c1bf887a9f710243ad67212b8486e765040e65be7c6e"
    assert lock.SEALED_SHA256 == "a1dc99b2aa846f4fa42f59a75681007e899539614c8c560e67c9b26e3d0003bc"
    assert scanner.scanner_implementation_sha256() == lock.SCANNER_SHA256
