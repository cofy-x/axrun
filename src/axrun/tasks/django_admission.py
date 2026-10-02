"""Read-only admission of the one audited Django imported runtime.

This is caller-owned evidence, not a signature or a new image-audit operation.
The approved private probe receipt is checked against its exact bytes and its
sealed, model-free scanner result. No Axern, Docker, or network call is made.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError
from axrun.models import canonical_json
from axrun.tasks import django_image_audit as scanner

SCHEMA = "axrun.swebench-django-axern-runtime-probe@1"
RECEIPT_SHA256 = "4048174c34249a072649c1bf887a9f710243ad67212b8486e765040e65be7c6e"
ORACLE_RECEIPT_SHA256 = "c6836ffddff8ed673e38073980614fd0a23e00eb046b8dbbce14b5773292eb8e"
IMAGE_IMPORT_RECEIPT_SHA256 = "fd6ac363b9c0d0f8cc9cb5f092d3dec90b7990cb54d37d3daba696a56ab7a8ab"
RUNTIME_IMAGE = (
    "index.docker.io/library/axrun-django-seed-0121"
    "@sha256:3912793ab27162e63adec6835a9267b150341b9b5cba1532e6d7ac8933c8cbb6"
)
SEED_IMAGE_ID = "sha256:22e52c3ff1f69caa7cba8b84dd0075da761c9d09ad795b76c6ec04cbfd58134d"
ROW_SHA256 = "6eea69026b82f8c17d1c2e299d39fada46d60acf6a9f39a4de20ab84749f1d37"
SCANNER_SHA256 = "1fa36d9f120263e81170393c5be75e1771b3878b6537bba335db073cc9e0d0c1"
SEALED_SHA256 = "a1dc99b2aa846f4fa42f59a75681007e899539614c8c560e67c9b26e3d0003bc"
SEALED_SIZE_BYTES = 1_428
EXECUTION = {
    "environment_id": "env-90e1900f-e4f6-40d6-a917-4f491feca71b",
    "run_id": "run-56f60e5f-47ea-4e57-b054-c897fdf2c9d5",
    "allocation_id": "alloc-5eb23a89-0281-4f25-b079-2c92320a6318",
}
_MAX_RECEIPT_BYTES = 128 << 10
_FIELDS = {
    "schema_version",
    "status",
    "reason_code",
    "oracle_receipt_sha256",
    "image_import_receipt_sha256",
    "runtime_image",
    "seed_image_id",
    "row_sha256",
    "scanner_sha256",
    "execution",
    "run_status",
    "exit_code",
    "sealed_sha256",
    "sealed_size_bytes",
    "sealed_audit",
    "cleanup",
}


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractError("Django admission has duplicate JSON fields")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ContractError("Django admission contains a non-finite JSON value")


def _private_receipt(path: Path) -> bytes:
    try:
        if not path.is_absolute() or path.is_symlink() or path.parent.is_symlink():
            raise ContractError("Django admission receipt requires a private absolute file")
        metadata = path.lstat()
        parent = path.parent.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or stat.S_IMODE(parent.st_mode) & 0o077
            or metadata.st_size > _MAX_RECEIPT_BYTES
        ):
            raise ContractError("Django admission receipt is not bounded and private")
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError("Django admission receipt is unavailable") from exc
    if len(payload) > _MAX_RECEIPT_BYTES:
        raise ContractError("Django admission receipt exceeds its size bound")
    return payload


def _receipt_json(payload: bytes) -> dict[str, Any]:
    try:
        value: object = json.loads(
            payload, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("Django admission receipt is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("Django admission receipt must be a JSON object")
    receipt = cast(dict[str, Any], value)
    if payload != canonical_json(receipt) + b"\n":
        raise ContractError("Django admission receipt encoding is not canonical")
    return receipt


def _checked_audit(value: object) -> dict[str, Any]:
    try:
        audit = scanner.check_audit_result(value, 1)
        status, reason = scanner.audit_status(audit)
    except (scanner.SecrecyError, TypeError, ValueError) as exc:
        raise ContractError("Django admission sealed audit is invalid") from exc
    if status != "passed" or reason != "no_locked_patch_signatures_reachable":
        raise ContractError("Django admission sealed audit did not pass")
    if (
        audit["gold_target_count"] != 1
        or audit["filesystem_entry_count"] != 76_818
        or not 0 < audit["filesystem_regular_file_count"] <= 76_818
        or not 0 < audit["filesystem_regular_file_bytes"] <= 16 << 30
        or audit["git_all_object_count"] != 339_152
        or not 0 < audit["git_all_object_bytes"] <= 8 << 30
    ):
        raise ContractError("Django admission sealed scan counts differ from approval")
    return audit


def load_django_admission(
    path: Path, *, task_image: str, expected_sha256: str = ""
) -> dict[str, Any]:
    """Validate the approved local receipt without re-querying or rerunning Axern."""
    if task_image != RUNTIME_IMAGE:
        raise ContractError("Django task image differs from admitted runtime")
    payload = _private_receipt(path)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != RECEIPT_SHA256 or (expected_sha256 and digest != expected_sha256):
        raise ContractError("Django admission receipt SHA-256 differs from approval")
    receipt = _receipt_json(payload)
    if set(receipt) != _FIELDS:
        raise ContractError("Django admission receipt has an invalid shape")
    expected = {
        "schema_version": SCHEMA,
        "status": "passed",
        "reason_code": "no_locked_patch_signatures_reachable",
        "oracle_receipt_sha256": ORACLE_RECEIPT_SHA256,
        "image_import_receipt_sha256": IMAGE_IMPORT_RECEIPT_SHA256,
        "runtime_image": RUNTIME_IMAGE,
        "seed_image_id": SEED_IMAGE_ID,
        "row_sha256": ROW_SHA256,
        "scanner_sha256": SCANNER_SHA256,
        "run_status": "RUN_STATUS_SUCCEEDED",
        "cleanup": "deleted_verified",
    }
    if any(receipt[key] != value for key, value in expected.items()):
        raise ContractError("Django admission identity or outcome differs from approval")
    if type(receipt["exit_code"]) is not int or receipt["exit_code"] != 0:
        raise ContractError("Django admission Run did not exit successfully")
    execution = receipt["execution"]
    if not isinstance(execution, dict) or execution != EXECUTION:
        raise ContractError("Django admission public execution identity differs")
    if scanner.scanner_implementation_sha256() != SCANNER_SHA256:
        raise ContractError("Django admission scanner implementation has changed")
    audit = _checked_audit(receipt["sealed_audit"])
    sealed = canonical_json({"machine": "x86_64", "request_deleted": True, "audit": audit}) + b"\n"
    if (
        type(receipt["sealed_size_bytes"]) is not int
        or receipt["sealed_size_bytes"] != SEALED_SIZE_BYTES
        or len(sealed) != SEALED_SIZE_BYTES
        or receipt["sealed_sha256"] != SEALED_SHA256
        or hashlib.sha256(sealed).hexdigest() != SEALED_SHA256
    ):
        raise ContractError("Django admission sealed output integrity differs")
    return receipt
