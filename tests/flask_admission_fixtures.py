"""Synthetic admission evidence; no official patch or test body is present."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from axrun.datasets import swebench_flask_official as lock
from axrun.models import canonical_digest, canonical_json
from axrun.tasks import flask_admission as admission
from axrun.tasks import flask_image_audit as scanner

RUNTIME_IMAGE = (
    f"index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:{'9' * 64}"
)


def import_receipt(image: str = RUNTIME_IMAGE) -> dict[str, str]:
    return {
        "source_ref": lock._SOURCE_IMAGE,
        "canonical_ref": lock._CANONICAL_SOURCE_IMAGE,
        "immutable_ref": image,
        "content_digest": image.rsplit("@", 1)[-1],
        "platform": "linux/amd64",
    }


def pin_synthetic_row(row: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "_ROW_SHA256": canonical_digest(row),
        "_SEED_DIGEST": canonical_digest(
            {
                "dataset_identity": lock._DATASET,
                "dataset_commit": lock._DATASET_COMMIT,
                "row_schema": lock._SCHEMA,
                "row": row,
            }
        ),
        "_EVAL_SCRIPT_SHA256": hashlib.sha256(row["eval_script"].encode()).hexdigest(),
        "_PROMPT_SHA256": hashlib.sha256(row["problem_statement"].encode()).hexdigest(),
        "_TEST_SELECTION_DIGEST": canonical_digest(
            {"fail_to_pass": row["FAIL_TO_PASS"], "pass_to_pass": row["PASS_TO_PASS"]}
        ),
        "_GOLD_PATCH_SHA256": hashlib.sha256(row["patch"].encode()).hexdigest(),
        "_TEST_PATCH_SHA256": hashlib.sha256(row["test_patch"].encode()).hexdigest(),
    }
    for key, value in values.items():
        monkeypatch.setattr(lock, key, value)


def safe_audit() -> dict[str, Any]:
    value: dict[str, Any] = {key: 0 for key in scanner._AUDIT_FIELDS}
    value.update({key: False for key in scanner._BOOL_FIELDS})
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
        modified_target_count=1,
        filesystem_entry_count=10,
        filesystem_regular_file_count=2,
        filesystem_regular_file_bytes=100,
        git_all_object_count=10,
        git_all_object_bytes=500,
    )
    return {"machine": "x86_64", "request_deleted": True, "audit": value}


def receipt(image: str = RUNTIME_IMAGE) -> dict[str, Any]:
    audit = safe_audit()
    sealed = canonical_json(audit) + b"\n"
    provenance = import_receipt(image)
    return {
        "schema_version": admission.SCHEMA,
        "source_image": lock._SOURCE_IMAGE,
        "runtime_image": image,
        "platform": lock._PLATFORM,
        "row_sha256": lock._ROW_SHA256,
        "seed_digest": lock._SEED_DIGEST,
        "eval_script_sha256": lock._EVAL_SCRIPT_SHA256,
        "prompt_sha256": lock._PROMPT_SHA256,
        "test_selection_digest": lock._TEST_SELECTION_DIGEST,
        "gold_patch_sha256": lock._GOLD_PATCH_SHA256,
        "test_patch_sha256": lock._TEST_PATCH_SHA256,
        "import_provenance": provenance,
        "import_digest": canonical_digest(provenance),
        "scanner_sha256": scanner.scanner_implementation_sha256(),
        "execution": {
            "environment_id": "env-audit",
            "run_id": "run-audit",
            "allocation_id": "alloc-audit",
        },
        "sealed_audit": audit,
        "sealed_sha256": hashlib.sha256(sealed).hexdigest(),
        "sealed_size_bytes": len(sealed),
        "status": "passed",
        "reason_code": "no_locked_patch_signatures_reachable",
    }


def write_receipt(path: Path, value: dict[str, Any] | None = None) -> Path:
    path.write_bytes(canonical_json(receipt() if value is None else value) + b"\n")
    return path
