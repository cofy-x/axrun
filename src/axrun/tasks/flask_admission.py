"""Caller-owned, model-free admission for the locked Flask runtime image.

Receipts bind a public SDK audit Run and its independently verified sealed result.
They are not signatures: a caller able to rewrite all local state can forge that
state. The public image-load result records import provenance, not a cryptographic
proof that the source and imported manifests have identical filesystem content.
We therefore scan the actual imported runtime, never substitute a source scan.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from axrun.backend import ExecutionBackend
from axrun.datasets import swebench_flask_official as lock
from axrun.errors import ContractError, InfrastructureError, RecoveryRequiredError
from axrun.models import (
    ExecutionRef,
    InputFile,
    OutputSpec,
    ResourceSpec,
    StagePlan,
    canonical_digest,
    canonical_json,
)
from axrun.store import EpisodeStore, atomic_write
from axrun.tasks import flask_image_audit as scanner

SCHEMA = "axrun.swebench-flask-admission@1"
_MAX_BYTES = 128 << 10
_FIELDS = {
    "schema_version",
    "source_image",
    "runtime_image",
    "platform",
    "row_sha256",
    "seed_digest",
    "eval_script_sha256",
    "prompt_sha256",
    "test_selection_digest",
    "gold_patch_sha256",
    "test_patch_sha256",
    "import_provenance",
    "import_digest",
    "scanner_sha256",
    "execution",
    "sealed_sha256",
    "sealed_size_bytes",
    "sealed_audit",
    "status",
    "reason_code",
}


def _json(payload: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ContractError("Flask admission has duplicate JSON fields")
            result[key] = value
        return result

    def reject(_value: str) -> None:
        raise ContractError("Flask admission contains an invalid JSON constant")

    try:
        value: object = json.loads(payload, object_pairs_hook=pairs, parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("Flask admission is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("Flask admission must be an object")
    return cast(dict[str, Any], value)


def _read(path: Path, *, maximum: int = _MAX_BYTES) -> bytes:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
            raise ContractError("Flask admission requires a bounded regular file")
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError("Flask admission file is unavailable") from exc
    if len(payload) > maximum:
        raise ContractError("Flask admission file exceeds its limit")
    return payload


def _audit(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(cast(dict[str, Any], value)) != {
        "machine",
        "request_deleted",
        "audit",
    }:
        raise ContractError("Flask runtime audit has an invalid shape")
    values = cast(dict[str, Any], value)
    if values["machine"] != "x86_64" or values["request_deleted"] is not True:
        raise ContractError("Flask runtime audit platform or input deletion is invalid")
    try:
        audit = scanner.check_audit_result(values["audit"], 1)
        status, reason = scanner.audit_status(audit)
    except (scanner.SecrecyError, TypeError, ValueError) as exc:
        raise ContractError("Flask runtime audit checks are invalid") from exc
    if status != "passed" or reason != "no_locked_patch_signatures_reachable":
        raise ContractError("Flask runtime image did not pass admission")
    if (
        audit["gold_target_count"] != 1
        or not 0 < audit["filesystem_regular_file_count"] <= audit["filesystem_entry_count"]
        or not 0 < audit["filesystem_regular_file_bytes"] <= 8 << 30
        or not 0 < audit["git_all_object_count"] <= 100_000
        or not 0 < audit["git_all_object_bytes"] <= 4 << 30
    ):
        raise ContractError("Flask runtime audit scan evidence is incomplete")
    return values


def load_flask_admission(
    path: Path, *, task_image: str, expected_sha256: str = ""
) -> dict[str, Any]:
    payload = _read(path)
    if expected_sha256 and hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ContractError("Flask admission receipt SHA-256 mismatch")
    receipt = _json(payload)
    if set(receipt) != _FIELDS:
        raise ContractError("Flask admission receipt has an invalid shape")
    expected = {
        "schema_version": SCHEMA,
        "source_image": lock.admission_contract()["SOURCE_IMAGE"],
        "runtime_image": task_image,
        "platform": lock.admission_contract()["PLATFORM"],
        "row_sha256": lock.admission_contract()["ROW_SHA256"],
        "seed_digest": lock.admission_contract()["SEED_DIGEST"],
        "eval_script_sha256": lock.admission_contract()["EVAL_SCRIPT_SHA256"],
        "prompt_sha256": lock.admission_contract()["PROMPT_SHA256"],
        "test_selection_digest": lock.admission_contract()["TEST_SELECTION_DIGEST"],
        "gold_patch_sha256": lock.admission_contract()["GOLD_PATCH_SHA256"],
        "test_patch_sha256": lock.admission_contract()["TEST_PATCH_SHA256"],
        "scanner_sha256": scanner.scanner_implementation_sha256(),
        "status": "passed",
        "reason_code": "no_locked_patch_signatures_reachable",
    }
    if any(receipt[key] != value for key, value in expected.items()):
        raise ContractError("Flask admission identity or implementation differs from lock")
    provenance = receipt["import_provenance"]
    if not isinstance(provenance, dict):
        raise ContractError("Flask admission import provenance is invalid")
    lock.check_flask_import_receipt(cast(dict[str, str], provenance), task_image)
    if receipt["import_digest"] != canonical_digest(provenance):
        raise ContractError("Flask admission import provenance digest mismatch")
    execution: object = receipt["execution"]
    if (
        not isinstance(execution, dict)
        or set(cast(dict[str, Any], execution)) != {"environment_id", "run_id", "allocation_id"}
        or any(
            not isinstance(value, str) or not value
            for value in cast(dict[str, Any], execution).values()
        )
    ):
        raise ContractError("Flask admission audit execution is incomplete")
    checked_execution = cast(dict[str, str], execution)
    for key, prefix in (
        ("environment_id", "env-"),
        ("run_id", "run-"),
        ("allocation_id", "alloc-"),
    ):
        identity = checked_execution[key]
        if (
            not identity.startswith(prefix)
            or len(identity) <= len(prefix)
            or any(character.isspace() or character in "/\\" for character in identity)
        ):
            raise ContractError("Flask admission public execution identity is invalid")
    safe_audit = _audit(receipt["sealed_audit"])
    sealed = canonical_json(safe_audit) + b"\n"
    if (
        type(receipt["sealed_size_bytes"]) is not int
        or receipt["sealed_size_bytes"] != len(sealed)
        or receipt["sealed_sha256"] != hashlib.sha256(sealed).hexdigest()
    ):
        raise ContractError("Flask admission sealed result integrity mismatch")
    return receipt


def _environment(client: Any, environment_id: str, image: str) -> None:
    environment = client.get_environment(environment_id)
    if str(environment.spec.image.ref) != image:
        raise ContractError("Flask audit Environment image differs from import receipt")


def admit_flask_image(
    row_path: Path,
    *,
    client: Any,
    backend: ExecutionBackend,
    state_root: Path,
    environment_id: str,
    task_image: str,
    image_import_receipt: dict[str, str],
    output: Path,
) -> dict[str, Any]:
    """One finite SDK audit; a repeated invocation recovers only its saved Run."""
    row = _json(_read(row_path, maximum=16 << 20))
    strings, fail, passed = lock.check_flask_row(row)
    lock.check_flask_import_receipt(image_import_receipt, task_image)
    _environment(client, environment_id, task_image)
    identity = {
        "schema_version": SCHEMA,
        "source_image": lock.admission_contract()["SOURCE_IMAGE"],
        "runtime_image": task_image,
        "platform": lock.admission_contract()["PLATFORM"],
        "row_sha256": lock.admission_contract()["ROW_SHA256"],
        "seed_digest": lock.admission_contract()["SEED_DIGEST"],
        "eval_script_sha256": lock.admission_contract()["EVAL_SCRIPT_SHA256"],
        "prompt_sha256": hashlib.sha256(strings["problem_statement"].encode()).hexdigest(),
        "test_selection_digest": canonical_digest(
            {"fail_to_pass": list(fail), "pass_to_pass": list(passed)}
        ),
        "gold_patch_sha256": hashlib.sha256(strings["patch"].encode()).hexdigest(),
        "test_patch_sha256": hashlib.sha256(strings["test_patch"].encode()).hexdigest(),
        "import_provenance": image_import_receipt,
        "import_digest": canonical_digest(image_import_receipt),
        "scanner_sha256": scanner.scanner_implementation_sha256(),
    }
    key = canonical_digest({**identity, "environment_id": environment_id})
    root = state_root.resolve() / "admissions" / key
    record_path = root / "execution.json"
    output = output.absolute()
    store = EpisodeStore(state_root.resolve())
    with store.lock(f"admission-{key}"):
        if output.exists() or output.is_symlink():
            accepted = load_flask_admission(output, task_image=task_image)
            if (
                any(accepted[field] != value for field, value in identity.items())
                or accepted["execution"]["environment_id"] != environment_id
            ):
                raise ContractError("Flask existing admission differs from audit request")
            return accepted
        record = _json(_read(record_path)) if record_path.exists() else None
        if record is not None and (
            set(record) != {"identity", "execution"} or record.get("identity") != identity
        ):
            raise ContractError("Flask audit durable identity mismatch")
        if record is not None and record["execution"] is None:
            raise RecoveryRequiredError(
                "Flask audit submission has no persisted Run; do not resubmit"
            )
        if record is None:
            atomic_write(
                record_path, canonical_json({"identity": identity, "execution": None}) + b"\n"
            )

    # Hidden signatures exist only in this private temporary input and in the
    # separate model-free Allocation. Never retain them in a durable plan/record.
    with tempfile.TemporaryDirectory(prefix="axrun-flask-audit-") as temporary:
        directory = Path(temporary)
        request = directory / "request.json"
        request.write_bytes(scanner.build_request(row))
        os.chmod(request, 0o600)
        script = directory / "audit.py"
        script.write_bytes(scanner.runtime_scan_script())
        plan = StagePlan(
            environment_id=environment_id,
            argv=("/opt/miniconda3/bin/python", "/opt/axrun/flask-image-audit.py"),
            cwd="/testbed",
            inputs=(
                InputFile(
                    str(request),
                    scanner.REQUEST_PATH,
                    hashlib.sha256(request.read_bytes()).hexdigest(),
                ),
                InputFile(
                    str(script),
                    "/opt/axrun/flask-image-audit.py",
                    hashlib.sha256(script.read_bytes()).hexdigest(),
                ),
            ),
            outputs=(
                OutputSpec(
                    scanner.OUTPUT_PATH,
                    media_type="application/json",
                    max_bytes=scanner.MAX_AUDIT_OUTPUT,
                ),
            ),
            resources=ResourceSpec(
                request_cpu="1", limit_cpu="1", request_memory="2Gi", limit_memory="2Gi"
            ),
            timeout_seconds=scanner.AUDIT_TIMEOUT_SECONDS,
            labels={"axrun.stage": "admission"},
        )

        def bound(execution: ExecutionRef) -> None:
            with store.lock(f"admission-{key}"):
                previous = _json(_read(record_path)) if record_path.exists() else None
                previous_execution = previous["execution"] if previous is not None else None
                if execution.environment_id != environment_id:
                    raise ContractError("Flask audit Environment identity changed")
                if previous_execution is not None and (
                    previous_execution["run_id"] != execution.run_id
                    or previous_execution["environment_id"] != execution.environment_id
                    or (
                        previous_execution["allocation_id"]
                        and previous_execution["allocation_id"] != execution.allocation_id
                    )
                ):
                    raise ContractError("Flask audit execution identity changed")
                atomic_write(
                    record_path,
                    canonical_json({"identity": identity, "execution": asdict(execution)}) + b"\n",
                )

        if record is None:
            stage = backend.execute(plan, artifact_dir=root / "artifacts", on_bound=bound)
        else:
            execution = ExecutionRef(**record["execution"])
            stage = backend.recover(execution, plan, artifact_dir=root / "artifacts")
            if stage is None:
                raise RecoveryRequiredError(
                    "Flask model-free audit Run is still active; query the persisted Run"
                )
        if stage.exit_code != 0:
            raise InfrastructureError("Flask model-free runtime audit failed closed")
        if stage.execution.environment_id != environment_id or not stage.execution.allocation_id:
            raise ContractError("Flask audit execution provenance mismatch")
        accepted_record = _json(_read(record_path))
        persisted = accepted_record["execution"]
        if not isinstance(persisted, dict):
            raise ContractError("Flask audit result has no persisted execution")
        persisted = cast(dict[str, Any], persisted)
        if (
            persisted.get("run_id") != stage.execution.run_id
            or persisted.get("environment_id") != stage.execution.environment_id
            or (
                persisted.get("allocation_id")
                and persisted.get("allocation_id") != stage.execution.allocation_id
            )
        ):
            raise ContractError("Flask audit result differs from persisted execution")
        bound(stage.execution)
        artifact = stage.artifact_for_path(scanner.OUTPUT_PATH)
        payload = _read(Path(artifact.path), maximum=scanner.MAX_AUDIT_OUTPUT)
        if (
            len(payload) != artifact.size_bytes
            or hashlib.sha256(payload).hexdigest() != artifact.sha256
        ):
            raise InfrastructureError("Flask audit sealed output integrity mismatch")
        safe = _audit(_json(payload))
        if payload != canonical_json(safe) + b"\n":
            raise ContractError("Flask sealed audit encoding is not canonical")
        receipt = {
            **identity,
            "execution": asdict(stage.execution),
            "sealed_audit": safe,
            "sealed_sha256": artifact.sha256,
            "sealed_size_bytes": artifact.size_bytes,
            "status": "passed",
            "reason_code": "no_locked_patch_signatures_reachable",
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with store.lock(f"admission-{key}"):
            if output.exists() or output.is_symlink():
                raise ContractError("Flask admission output already exists")
            atomic_write(output, canonical_json(receipt) + b"\n")
        return load_flask_admission(output, task_image=task_image)
