"""Mandatory Flask admission integrity and public-Run recovery, without Docker."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from flask_admission_fixtures import (
    RUNTIME_IMAGE,
    import_receipt,
    pin_synthetic_row,
    receipt,
    safe_audit,
    write_receipt,
)

from axrun.errors import ContractError, InfrastructureError, RecoveryRequiredError
from axrun.models import Artifact, ExecutionRef, StagePlan, StageResult, canonical_json
from axrun.tasks import flask_admission as admission
from axrun.tasks import flask_image_audit as scanner


def _seal(value: dict[str, Any]) -> None:
    payload = canonical_json(value["sealed_audit"]) + b"\n"
    value["sealed_size_bytes"] = len(payload)
    value["sealed_sha256"] = hashlib.sha256(payload).hexdigest()


def test_admission_checks_exact_receipt_and_independent_byte_digest(tmp_path: Path) -> None:
    value = receipt()
    path = write_receipt(tmp_path / "admission.json", value)
    expected_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert (
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE, expected_sha256=expected_sha)
        == value
    )
    with pytest.raises(ContractError, match="SHA-256 mismatch"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE, expected_sha256="0" * 64)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ContractError, match="SHA-256 mismatch"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE, expected_sha256=expected_sha)


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("schema_version", "axrun.swebench-flask-admission@0"),
        ("source_image", RUNTIME_IMAGE),
        ("runtime_image", "docker.io/example:latest"),
        ("platform", "linux/arm64"),
        ("row_sha256", "0" * 64),
        ("seed_digest", "0" * 64),
        ("eval_script_sha256", "0" * 64),
        ("prompt_sha256", "0" * 64),
        ("test_selection_digest", "0" * 64),
        ("gold_patch_sha256", "0" * 64),
        ("test_patch_sha256", "0" * 64),
        ("scanner_sha256", "0" * 64),
        ("status", "blocked"),
        ("reason_code", "trust_me_passed"),
    ],
)
def test_admission_binds_source_runtime_assets_platform_and_implementation(
    tmp_path: Path, field: str, wrong: object
) -> None:
    value = {**receipt(), field: wrong}
    path = write_receipt(tmp_path / "admission.json", value)
    with pytest.raises(ContractError, match="identity or implementation differs"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)


def test_import_provenance_digest_and_contract_are_not_interchangeable(tmp_path: Path) -> None:
    value = receipt()
    path = tmp_path / "admission.json"
    value["import_digest"] = "0" * 64
    write_receipt(path, value)
    with pytest.raises(ContractError, match="provenance digest mismatch"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)
    value = receipt()
    value["import_provenance"]["platform"] = "linux/arm64"
    write_receipt(path, value)
    with pytest.raises(ContractError, match="source/platform"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)
    value = receipt()
    value["import_provenance"]["extra_conversion_claim"] = "passed"
    write_receipt(path, value)
    with pytest.raises(ContractError, match="invalid shape"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("filesystem_scan_complete", False),
        ("git_all_object_scan_complete", False),
        ("test_full_filesystem_match_count", 1),
        ("gold_all_git_object_match_count", 1),
        ("gold_patch_reverse_applies", True),
        ("test_unprovable_fragment_count", 1),
        ("gold_target_count", 2),
        ("test_target_count", 2),
        ("filesystem_entry_count", 0),
        ("filesystem_regular_file_count", 0),
        ("filesystem_regular_file_bytes", 0),
        ("filesystem_regular_file_bytes", (8 << 30) + 1),
        ("git_all_object_count", 0),
        ("git_all_object_bytes", 0),
        ("git_all_object_bytes", (4 << 30) + 1),
        ("git_all_object_count", -1),
        ("filesystem_scan_complete", 1),
    ],
)
def test_passed_flag_cannot_bypass_full_scan_and_recomputed_status(
    tmp_path: Path, field: str, wrong: object
) -> None:
    value = receipt()
    value["sealed_audit"]["audit"][field] = wrong
    _seal(value)
    path = write_receipt(tmp_path / "admission.json", value)
    with pytest.raises(ContractError):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)


@pytest.mark.parametrize(("field", "wrong"), [("machine", "aarch64"), ("request_deleted", False)])
def test_runtime_platform_and_exact_hidden_input_removal_are_mandatory(
    tmp_path: Path, field: str, wrong: object
) -> None:
    value = receipt()
    value["sealed_audit"][field] = wrong
    _seal(value)
    path = write_receipt(tmp_path / "admission.json", value)
    with pytest.raises(ContractError, match="platform or input deletion"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)


@pytest.mark.parametrize(
    ("field", "wrong"), [("sealed_sha256", "0" * 64), ("sealed_size_bytes", 0)]
)
def test_sealed_length_and_sha_are_independently_verified(
    tmp_path: Path, field: str, wrong: object
) -> None:
    path = write_receipt(tmp_path / "admission.json", {**receipt(), field: wrong})
    with pytest.raises(ContractError, match="sealed result integrity mismatch"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)


@pytest.mark.parametrize(
    "execution",
    [
        {},
        {"environment_id": "env-audit", "run_id": "run-audit"},
        {"environment_id": "env-audit", "run_id": "", "allocation_id": "alloc-audit"},
        {"environment_id": "run-audit", "run_id": "alloc-audit", "allocation_id": "env-audit"},
        {"environment_id": "arbitrary", "run_id": "arbitrary", "allocation_id": "arbitrary"},
        {"environment_id": "env-audit", "run_id": "run-", "allocation_id": "alloc-audit"},
    ],
)
def test_receipt_requires_correct_public_execution_identities(
    tmp_path: Path, execution: dict[str, str]
) -> None:
    path = write_receipt(tmp_path / "admission.json", {**receipt(), "execution": execution})
    with pytest.raises(ContractError, match="execution"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)


def test_receipt_shape_json_and_regular_file_fail_closed(tmp_path: Path) -> None:
    path = write_receipt(tmp_path / "admission.json", {**receipt(), "unknown": True})
    with pytest.raises(ContractError, match="invalid shape"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)
    path.write_bytes(b'{"status":"passed","status":"blocked"}')
    with pytest.raises(ContractError, match="duplicate"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)
    path.write_bytes(b'{"status":NaN}')
    with pytest.raises(ContractError, match="invalid JSON constant"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ContractError, match="regular file"):
        admission.load_flask_admission(link, task_image=RUNTIME_IMAGE)
    path.write_bytes(b"x" * ((128 << 10) + 1))
    with pytest.raises(ContractError, match="regular file"):
        admission.load_flask_admission(path, task_image=RUNTIME_IMAGE)


_PATCH = """diff --git a/project.py b/project.py
--- a/project.py
+++ b/project.py
@@ -1,2 +1,2 @@
 existing_code()
-old_behavior()
+assert synthetic_private_behavior()
"""


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    row: dict[str, Any] = {
        "FAIL_TO_PASS": ["synthetic_fail"],
        "PASS_TO_PASS": [f"synthetic_pass_{index}" for index in range(59)],
        "base_commit": "7ee9ceb71e868944a46e1ff00b506772a53a4f1d",
        "created_at": "2024-01-01T00:00:00Z",
        "difficulty": "synthetic",
        "environment_setup_commit": "a" * 40,
        "eval_script": "#!/bin/bash\necho synthetic-offline\n",
        "eval_type": "pass_and_fail",
        "hints_text": "synthetic-hint-not-materialized",
        "image": "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest",
        "instance_id": "pallets__flask-5014",
        "log_parser": "parse_log_flask",
        "patch": _PATCH,
        "problem_statement": "Fix the synthetic behavior.",
        "repo": "pallets/flask",
        "test_patch": _PATCH.replace("project.py", "test_project.py"),
        "version": "2.3",
    }
    pin_synthetic_row(row, monkeypatch)
    path = tmp_path / "row.json"
    path.write_bytes(canonical_json(row))
    return {
        "row_path": path,
        "state_root": tmp_path / "state",
        "environment_id": "env-audit",
        "task_image": RUNTIME_IMAGE,
        "image_import_receipt": import_receipt(),
        "output": tmp_path / "admission.json",
    }


class _Backend:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self.execution = ExecutionRef("env-audit", "run-audit", "alloc-audit")
        self.execute_count = 0
        self.recovered: list[ExecutionRef] = []
        self.interrupt = False
        self.interrupt_before_bound = False
        self.active = False
        self.exit_code = 0
        self.bad_output = ""
        self.returned_execution: ExecutionRef | None = None

    def execute(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
        lifecycle: Any = None,
    ) -> StageResult:
        self.execute_count += 1
        assert lifecycle is None
        assert plan.network_policy == "deny_all"
        assert plan.env == {} and plan.secret_env == () and not plan.image_mounts
        assert plan.labels == {"axrun.stage": "admission"}
        assert len(plan.inputs) == 2
        if self.interrupt_before_bound:
            raise ConnectionError("submission outcome ambiguous before Run binding")
        on_bound(self.execution)
        records = list(self.state_root.glob("admissions/*/execution.json"))
        assert len(records) == 1
        durable = records[0].read_text()
        assert "synthetic_private_behavior" not in durable and '"inputs"' not in durable
        assert json.loads(durable)["execution"]["run_id"] == self.execution.run_id
        if self.interrupt:
            raise ConnectionError("caller disconnected after public Run persisted")
        return self._result(artifact_dir)

    def recover(self, execution: ExecutionRef, plan: StagePlan, *, artifact_dir: Path):
        self.recovered.append(execution)
        assert execution == self.execution
        return None if self.active else self._result(artifact_dir)

    def cancel(self, execution: ExecutionRef) -> None:
        raise AssertionError("ordinary admission recovery does not cancel or rerun")

    def wait(self, execution: ExecutionRef, *, timeout: float | None = None) -> None:
        raise AssertionError("recovery queries the existing public Run")

    def _result(self, artifact_dir: Path) -> StageResult:
        payload = canonical_json(safe_audit()) + b"\n"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / "flask-image-audit.json"
        path.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        size = len(payload)
        if self.bad_output == "sha":
            sha = "0" * 64
        elif self.bad_output == "size":
            size += 1
        elif self.bad_output == "missing":
            path.unlink()
        artifact = Artifact(scanner.OUTPUT_PATH, str(path), size, sha, "application/json")
        return StageResult(
            self.returned_execution or self.execution, self.exit_code, "", (artifact,)
        )


def _admit(prepared: dict[str, Any], backend: _Backend) -> dict[str, Any]:
    client = SimpleNamespace(
        get_environment=lambda _id: SimpleNamespace(
            spec=SimpleNamespace(image=SimpleNamespace(ref=RUNTIME_IMAGE))
        )
    )
    return admission.admit_flask_image(**prepared, client=client, backend=backend)


def test_model_free_admission_persists_run_before_data_operations_and_reuses_evidence(
    prepared: dict[str, Any],
) -> None:
    backend = _Backend(prepared["state_root"])
    result = _admit(prepared, backend)
    assert result["execution"]["run_id"] == "run-audit"
    assert result["runtime_image"] == RUNTIME_IMAGE
    assert result["source_image"] != result["runtime_image"]
    assert _admit(prepared, backend) == result
    assert backend.execute_count == 1 and backend.recovered == []


def test_caller_disconnect_recovers_original_run_without_creating_second_run(
    prepared: dict[str, Any],
) -> None:
    backend = _Backend(prepared["state_root"])
    backend.interrupt = True
    with pytest.raises(ConnectionError):
        _admit(prepared, backend)
    assert not prepared["output"].exists()
    backend.interrupt = False
    backend.active = True
    with pytest.raises(RecoveryRequiredError, match="still active"):
        _admit(prepared, backend)
    backend.active = False
    result = _admit(prepared, backend)
    assert result["execution"]["run_id"] == "run-audit"
    assert backend.execute_count == 1 and backend.recovered == [backend.execution] * 2


@pytest.mark.parametrize("changed", ["run_id", "allocation_id", "environment_id"])
def test_audit_result_must_match_persisted_public_execution_identity(
    prepared: dict[str, Any],
    changed: str,
) -> None:
    backend = _Backend(prepared["state_root"])
    backend.returned_execution = replace(backend.execution, **{changed: f"{changed}-unexpected"})
    with pytest.raises(ContractError, match=r"provenance|identity|execution"):
        _admit(prepared, backend)
    assert not prepared["output"].exists()


def test_recovery_rejects_fresh_run_substitution(prepared: dict[str, Any]) -> None:
    backend = _Backend(prepared["state_root"])
    backend.interrupt = True
    with pytest.raises(ConnectionError):
        _admit(prepared, backend)
    backend.interrupt = False
    backend.returned_execution = replace(backend.execution, run_id="run-replacement")
    with pytest.raises(ContractError, match="persisted execution"):
        _admit(prepared, backend)
    assert backend.execute_count == 1 and backend.recovered == [backend.execution]
    assert not prepared["output"].exists()


def test_ambiguous_submission_without_run_identity_never_silently_resubmits(
    prepared: dict[str, Any],
) -> None:
    backend = _Backend(prepared["state_root"])
    backend.interrupt_before_bound = True
    with pytest.raises(ConnectionError):
        _admit(prepared, backend)
    backend.interrupt_before_bound = False
    with pytest.raises(RecoveryRequiredError, match="no persisted Run"):
        _admit(prepared, backend)
    assert backend.execute_count == 1 and backend.recovered == []
    assert not prepared["output"].exists()


def test_existing_receipt_cannot_substitute_another_audit_environment(
    prepared: dict[str, Any],
) -> None:
    backend = _Backend(prepared["state_root"])
    result = _admit(prepared, backend)
    result["execution"]["environment_id"] = "env-other-audit"
    write_receipt(prepared["output"], result)
    with pytest.raises(ContractError, match="existing admission differs"):
        _admit(prepared, backend)
    assert backend.execute_count == 1


@pytest.mark.parametrize("bad_output", ["sha", "size", "missing"])
def test_audit_transport_integrity_failure_cannot_issue_admission(
    prepared: dict[str, Any],
    bad_output: str,
) -> None:
    backend = _Backend(prepared["state_root"])
    backend.bad_output = bad_output
    with pytest.raises((ContractError, InfrastructureError)):
        _admit(prepared, backend)
    assert not prepared["output"].exists()


def test_failed_audit_run_is_infrastructure_error_not_candidate_score(
    prepared: dict[str, Any],
) -> None:
    backend = _Backend(prepared["state_root"])
    backend.exit_code = 1
    with pytest.raises(InfrastructureError, match="failed closed"):
        _admit(prepared, backend)
    assert not prepared["output"].exists()
