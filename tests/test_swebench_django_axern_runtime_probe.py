"""Input and output contracts for the one-shot Django imported-runtime probe."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from axrun.models import Artifact, ExecutionRef, StageResult

TOOLS = Path(__file__).parents[1] / "tools/validation"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    "swebench_django_axern_runtime_probe", TOOLS / "swebench_django_axern_runtime_probe.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SEED = MODULE.EXPECTED_SEED_IMAGE_ID
RUNTIME = "sha256:" + "2" * 64
MANIFEST = "3" * 64


def _save(path: Path, value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _oracle() -> dict:
    return {
        "schema_version": MODULE.NATIVE_ORACLE_SCHEMA,
        "status": "completed",
        "official_source_image": MODULE.native_oracle.OFFICIAL_SOURCE_IMAGE,
        "source_image_id": MODULE.native_oracle.OFFICIAL_SOURCE_IMAGE.rsplit("@", 1)[-1],
        "row_sha256": MODULE.asset_lock.ROW_SHA256,
        "assets_manifest_sha256": MANIFEST,
        "harness_commit": MODULE.asset_lock.HARNESS_COMMIT,
        "platform": "linux/amd64",
        "seed_image_id": SEED,
        "seed_audit": {
            "git_head": MODULE.asset_lock.BASE_COMMIT,
            "git_dirty": False,
            "base_commit_present": True,
        },
        "cases": {
            "empty": {
                "container_removed": True,
                "official_summary": {
                    "classification": "official_empty_patch_unscored",
                    "resolved": None,
                },
            },
            "gold": {
                "container_removed": True,
                "official_summary": {
                    "resolved": True,
                    "fail_to_pass_success": 1,
                    "fail_to_pass_failure": 0,
                },
            },
            "known_bad": {
                "container_removed": True,
                "official_summary": {"resolved": False, "fail_to_pass_failure": 1},
            },
        },
    }


def test_oracle_receipt_is_digest_bound_and_order_independent(tmp_path: Path) -> None:
    path = tmp_path / "oracle.json"
    payload = _oracle()
    digest = _save(path, payload)
    assert MODULE._native_receipt(path, digest, MANIFEST) == payload
    with pytest.raises(MODULE.ProbeError, match="oracle_digest_mismatch"):
        MODULE._native_receipt(path, "0" * 64, MANIFEST)
    payload["cases"]["known_bad"]["official_summary"]["resolved"] = True
    bad_digest = _save(path, payload)
    with pytest.raises(MODULE.ProbeError, match="oracle_verdict_invalid"):
        MODULE._native_receipt(path, bad_digest, MANIFEST)


def test_import_receipt_binds_local_seed_and_immutable_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "axrun-django-seed-0121:private-v2"
    receipt = {
        "source_ref": source,
        "canonical_ref": "index.docker.io/library/" + source,
        "immutable_ref": "index.docker.io/library/axrun-django-seed-0121@" + RUNTIME,
        "content_digest": RUNTIME,
        "archive_digest": "sha256:" + "4" * 64,
        "platform": "linux/amd64",
        "size_bytes": 1234,
        "reused": False,
    }
    path = tmp_path / "import.json"
    digest = _save(path, receipt)

    def inspect(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[:3] == ["docker", "image", "inspect"]
        return subprocess.CompletedProcess(args, 0, SEED + "\n", "")

    monkeypatch.setattr(MODULE.subprocess, "run", inspect)
    assert MODULE._import_receipt(path, SEED) == (receipt, digest)
    receipt["immutable_ref"] = "index.docker.io/library/foreign@" + RUNTIME
    _save(path, receipt)
    with pytest.raises(MODULE.ProbeError, match="import_identity_invalid"):
        MODULE._import_receipt(path, SEED)


def test_unexpected_failure_does_not_print_exception_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_args: object) -> None:
        raise RuntimeError("secret-looking exception body")

    monkeypatch.setattr(MODULE, "run_probe", fail)
    with monkeypatch.context() as context:
        context.setattr(
            sys,
            "argv",
            [
                "probe",
                "--assets-dir",
                "x",
                "--oracle-receipt",
                "x",
                "--oracle-sha256",
                "x",
                "--image-import-receipt",
                "x",
                "--context-file",
                "x",
                "--output-dir",
                "x",
            ],
        )
        assert MODULE.main() == 1
    output = capsys.readouterr()
    assert "secret-looking" not in output.err
    assert "runtime_probe_failed_closed" in output.err


class _FakeClient:
    def __init__(self, runtime_ref: str) -> None:
        self.runtime_ref = runtime_ref
        self.created = 0
        self.deleted: list[str] = []
        self.closed = 0
        self.returned_run: object | None = None

    def create_environment(self, *, image_ref: str, labels: dict[str, str]) -> SimpleNamespace:
        assert image_ref == self.runtime_ref
        assert labels == {"axrun.validation": "django-runtime-audit"}
        self.created += 1
        return SimpleNamespace(
            id="env-owned", spec=SimpleNamespace(image=SimpleNamespace(ref=image_ref))
        )

    def get_run(self, run_id: str) -> object:
        assert run_id == "run-owned"
        assert self.returned_run is not None
        return self.returned_run

    def delete_environment(self, environment_id: str) -> None:
        self.deleted.append(environment_id)

    def get_environment(self, environment_id: str) -> object:
        raise AssertionError(f"unexpected Environment query: {environment_id}")

    def close(self) -> None:
        self.closed += 1


def _mock_probe_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Namespace, _FakeClient]:
    runtime_ref = "index.docker.io/library/axrun-django-seed-0121@" + RUNTIME
    client = _FakeClient(runtime_ref)
    monkeypatch.setattr(MODULE.native_oracle, "check_private_output_destination", lambda _: None)
    monkeypatch.setattr(MODULE.native_oracle, "check_native_docker", lambda: None)
    monkeypatch.setattr(MODULE.native_oracle, "check_images", lambda _: None)
    monkeypatch.setattr(MODULE, "_check_context", lambda _: None)
    monkeypatch.setattr(MODULE.importlib.metadata, "version", lambda _: "0.12.1")
    sdk_path = Path(MODULE.axern_sdk.__file__).resolve()
    monkeypatch.setattr(
        MODULE.sysconfig, "get_paths", lambda: {"purelib": str(sdk_path.parent.parent)}
    )
    monkeypatch.setattr(MODULE.asset_lock, "validate_assets", lambda _: {"test": "manifest"})
    monkeypatch.setattr(MODULE.asset_lock, "load_locked_row", lambda _: {"test": "row"})
    monkeypatch.setattr(MODULE, "_native_receipt", lambda *_: {"seed_image_id": SEED})
    monkeypatch.setattr(
        MODULE,
        "_import_receipt",
        lambda *_: ({"immutable_ref": runtime_ref}, MODULE.EXPECTED_IMPORT_SHA256),
    )
    monkeypatch.setattr(MODULE.scanner, "build_request", lambda _: b'{"locked":"opaque"}')
    monkeypatch.setattr(MODULE.scanner, "runtime_scan_script", lambda: b"pass\n")
    monkeypatch.setattr(MODULE.scanner, "scanner_implementation_sha256", lambda: "5" * 64)

    def from_context(path: str, name: str) -> _FakeClient:
        assert (path, name) == (str(tmp_path / "context.json"), "local")
        return client

    monkeypatch.setattr(MODULE.AxernClient, "from_context", from_context)
    args = Namespace(
        assets_dir=tmp_path / "assets",
        oracle_receipt=tmp_path / "oracle.json",
        oracle_sha256=MODULE.EXPECTED_ORACLE_SHA256,
        image_import_receipt=tmp_path / "import.json",
        context_file=tmp_path / "context.json",
        output_dir=tmp_path / "probe",
    )
    return args, client


def test_bound_run_survives_transport_failure_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, client = _mock_probe_preflight(tmp_path, monkeypatch)
    calls = 0

    class FailingBackend:
        def __init__(self, bound_client: object) -> None:
            assert bound_client is client

        def execute(self, _plan: object, *, artifact_dir: Path, on_bound: object) -> None:
            nonlocal calls
            calls += 1
            assert artifact_dir == args.output_dir / "artifacts"
            on_bound(ExecutionRef("env-owned", "run-owned"))
            persisted = json.loads((args.output_dir / "receipt.json").read_text())
            assert persisted["execution"] == {
                "environment_id": "env-owned",
                "run_id": "run-owned",
                "allocation_id": "",
            }
            raise ConnectionError("transport lost after Run binding")

    monkeypatch.setattr(MODULE, "AxernBackend", FailingBackend)
    with pytest.raises(MODULE.ProbeError, match="ConnectionError"):
        MODULE.run_probe(args)
    receipt = json.loads((args.output_dir / "receipt.json").read_text())
    assert receipt["status"] == "incomplete"
    assert receipt["execution"]["run_id"] == "run-owned"
    assert receipt["cleanup"] == "retained_for_ambiguous_run"
    assert calls == client.created == client.closed == 1
    assert client.deleted == []


@pytest.mark.parametrize("wrong_field", ["id", "environment_id", "allocation_id"])
def test_terminal_looking_foreign_run_does_not_trigger_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong_field: str
) -> None:
    args, client = _mock_probe_preflight(tmp_path, monkeypatch)
    run_fields = {"id": "run-owned", "environment_id": "env-owned", "allocation_id": "alloc-owned"}
    run_fields[wrong_field] = "foreign"
    client.returned_run = SimpleNamespace(**run_fields)
    monkeypatch.setattr(MODULE, "_status_name", lambda _: "RUN_STATUS_SUCCEEDED")
    execution = ExecutionRef("env-owned", "run-owned", "alloc-owned")

    class BoundBackend:
        def __init__(self, bound_client: object) -> None:
            assert bound_client is client

        def execute(self, _plan: object, *, artifact_dir: Path, on_bound: object) -> StageResult:
            assert artifact_dir == args.output_dir / "artifacts"
            on_bound(ExecutionRef("env-owned", "run-owned"))
            on_bound(execution)
            return StageResult(execution, 0, "", ())

    monkeypatch.setattr(MODULE, "AxernBackend", BoundBackend)
    with pytest.raises(MODULE.ProbeError, match="run_terminal_identity_invalid"):
        MODULE.run_probe(args)
    receipt = json.loads((args.output_dir / "receipt.json").read_text())
    assert receipt["status"] == "incomplete"
    assert receipt["execution"] == {
        "environment_id": "env-owned",
        "run_id": "run-owned",
        "allocation_id": "alloc-owned",
    }
    assert receipt["cleanup"] == "retained_for_ambiguous_run"
    assert client.created == client.closed == 1
    assert client.deleted == []


@pytest.mark.parametrize("public_status", ["RUN_STATUS_FAILED", "RUN_STATUS_CANCELLED"])
def test_zero_exit_never_overrides_failed_public_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, public_status: str
) -> None:
    args, client = _mock_probe_preflight(tmp_path, monkeypatch)
    execution = ExecutionRef("env-owned", "run-owned", "alloc-owned")
    client.returned_run = SimpleNamespace(
        id="run-owned", environment_id="env-owned", allocation_id="alloc-owned"
    )
    monkeypatch.setattr(MODULE, "_status_name", lambda _: public_status)
    monkeypatch.setattr(MODULE, "_checked_sealed_error", lambda *_: "runtime_run_failed")
    monkeypatch.setattr(client, "get_environment", lambda _: object())

    class Backend:
        def __init__(self, bound_client: object) -> None:
            assert bound_client is client

        def execute(self, _plan: object, *, artifact_dir: Path, on_bound: object) -> StageResult:
            on_bound(execution)
            return StageResult(execution, 0, "", ())

    monkeypatch.setattr(MODULE, "AxernBackend", Backend)
    with pytest.raises(MODULE.ProbeError, match="run_terminal_failure"):
        MODULE.run_probe(args)
    receipt = json.loads((args.output_dir / "receipt.json").read_text())
    assert receipt["status"] == "blocked"
    assert receipt["run_status"] == public_status
    assert receipt["exit_code"] == 0
    assert client.deleted == ["env-owned"]


def test_passed_audit_with_unverified_deletion_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, client = _mock_probe_preflight(tmp_path, monkeypatch)
    execution = ExecutionRef("env-owned", "run-owned", "alloc-owned")
    client.returned_run = SimpleNamespace(
        id="run-owned", environment_id="env-owned", allocation_id="alloc-owned"
    )
    monkeypatch.setattr(MODULE, "_status_name", lambda _: "RUN_STATUS_SUCCEEDED")
    monkeypatch.setattr(client, "get_environment", lambda _: object())
    monkeypatch.setattr(
        MODULE.scanner,
        "check_audit_result",
        lambda *_: {
            "git_all_object_count": 1,
            "git_all_object_bytes": 1,
            "filesystem_regular_file_count": 1,
            "filesystem_entry_count": 1,
            "filesystem_regular_file_bytes": 1,
        },
    )
    monkeypatch.setattr(MODULE.scanner, "audit_status", lambda _: ("passed", "clean"))

    class Backend:
        def __init__(self, bound_client: object) -> None:
            assert bound_client is client

        def execute(self, _plan: object, *, artifact_dir: Path, on_bound: object) -> StageResult:
            on_bound(execution)
            payload = b'{"machine":"x86_64","request_deleted":true,"audit":{}}'
            artifact_dir.mkdir()
            path = artifact_dir / "audit.json"
            path.write_bytes(payload)
            artifact = Artifact(
                MODULE.scanner.OUTPUT_PATH,
                str(path),
                len(payload),
                hashlib.sha256(payload).hexdigest(),
                "application/json",
            )
            return StageResult(execution, 0, "", (artifact,))

    monkeypatch.setattr(MODULE, "AxernBackend", Backend)
    with pytest.raises(MODULE.ProbeError, match="cleanup_unverified"):
        MODULE.run_probe(args)
    receipt = json.loads((args.output_dir / "receipt.json").read_text())
    assert receipt["status"] == "incomplete"
    assert receipt["reason_code"] == "cleanup_unverified"
    assert receipt["cleanup"] == "delete_unverified"
    assert client.deleted == ["env-owned"]
