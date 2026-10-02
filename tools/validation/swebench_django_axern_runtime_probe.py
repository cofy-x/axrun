#!/usr/bin/env python3
"""One finite, model-free audit of the Axern-imported Django runtime.

This is a native validation probe, not a registered Django task adapter. It
binds a checked native oracle and Axern's public image-load receipt, executes
the bounded Django scanner through the released SDK, preserves the public Run
identity before releasing inputs, and deletes only its own Environment after a
confirmed terminal Run. An ambiguous submission is never retried automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import stat
import subprocess
import sys
import sysconfig
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import axern_sdk
import swebench_django_assets as asset_lock
import swebench_django_native_oracle as native_oracle
from axern_sdk import AxernClient, SandboxNotFoundError

from axrun._atomic_file import atomic_write
from axrun.axern_backend import AxernBackend, _status_name
from axrun.models import InputFile, OutputSpec, ResourceSpec, StagePlan, canonical_json
from axrun.tasks import django_image_audit as scanner

SCHEMA = "axrun.swebench-django-axern-runtime-probe@1"
NATIVE_ORACLE_SCHEMA = "axrun.swebench-django-native-oracle@1"
# This is the single approved HK-dev acceptance, not a generic "any receipt"
# admission API. Both receipts were independently audited before this probe.
EXPECTED_ORACLE_SHA256 = "c6836ffddff8ed673e38073980614fd0a23e00eb046b8dbbce14b5773292eb8e"
EXPECTED_IMPORT_SHA256 = "fd6ac363b9c0d0f8cc9cb5f092d3dec90b7990cb54d37d3daba696a56ab7a8ab"
EXPECTED_SEED_IMAGE_ID = "sha256:22e52c3ff1f69caa7cba8b84dd0075da761c9d09ad795b76c6ec04cbfd58134d"
EXPECTED_HOST = "wayne-hk-dev"
EXPECTED_CONTEXT_FILE = Path(
    "/data/forge-workspace/.forge/local/hosts/wayne-hk-dev/axern/config.json"
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_RECEIPT_BYTES = 128 << 10


class ProbeError(RuntimeError):
    """A stable, non-sensitive admission preflight or execution failure."""


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_file(path: Path, *, maximum: int = _MAX_RECEIPT_BYTES) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ProbeError("receipt_not_regular")
    if path.stat().st_size > maximum:
        raise ProbeError("receipt_oversized")
    payload = path.read_bytes()
    if len(payload) > maximum:
        raise ProbeError("receipt_oversized")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ProbeError("receipt_duplicate_key")
            result[key] = value
        return result

    def reject(_value: str) -> None:
        raise ProbeError("receipt_nonfinite")

    try:
        value: object = json.loads(payload, object_pairs_hook=pairs, parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError("receipt_invalid_json") from exc
    if not isinstance(value, dict):
        raise ProbeError("receipt_not_object")
    return cast(dict[str, Any], value), _sha(payload)


def _native_receipt(path: Path, expected_sha256: str, manifest_sha256: str) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ProbeError("oracle_digest_invalid")
    receipt, actual_sha256 = _json_file(path)
    if actual_sha256 != expected_sha256:
        raise ProbeError("oracle_digest_mismatch")
    if (
        receipt.get("schema_version") != NATIVE_ORACLE_SCHEMA
        or receipt.get("status") != "completed"
        or receipt.get("official_source_image") != native_oracle.OFFICIAL_SOURCE_IMAGE
        or receipt.get("row_sha256") != asset_lock.ROW_SHA256
        or receipt.get("assets_manifest_sha256") != manifest_sha256
        or receipt.get("harness_commit") != asset_lock.HARNESS_COMMIT
        or receipt.get("platform") != "linux/amd64"
    ):
        raise ProbeError("oracle_identity_invalid")
    seed_id = receipt.get("seed_image_id")
    if seed_id != EXPECTED_SEED_IMAGE_ID:
        raise ProbeError("oracle_seed_invalid")
    if receipt.get("source_image_id") != native_oracle.OFFICIAL_SOURCE_IMAGE.rsplit("@", 1)[-1]:
        raise ProbeError("oracle_source_image_invalid")
    seed_audit = receipt.get("seed_audit")
    if (
        not isinstance(seed_audit, dict)
        or seed_audit.get("git_head") != asset_lock.BASE_COMMIT
        or seed_audit.get("git_dirty") is not False
        or seed_audit.get("base_commit_present") is not True
    ):
        raise ProbeError("oracle_seed_audit_invalid")
    cases = receipt.get("cases")
    if not isinstance(cases, dict) or set(cases) != {"gold", "known_bad", "empty"}:
        raise ProbeError("oracle_cases_incomplete")
    for item in cases.values():
        if (
            not isinstance(item, dict)
            or item.get("container_removed") is not True
            or not isinstance(item.get("official_summary"), dict)
        ):
            raise ProbeError("oracle_cleanup_incomplete")
    gold, known_bad, empty = (
        cases[name]["official_summary"] for name in ("gold", "known_bad", "empty")
    )
    if (
        gold.get("resolved") is not True
        or gold.get("fail_to_pass_success") != 1
        or gold.get("fail_to_pass_failure") != 0
        or known_bad.get("resolved") is not False
        or known_bad.get("fail_to_pass_failure") != 1
        or empty.get("classification") != "official_empty_patch_unscored"
        or empty.get("resolved") is not None
    ):
        raise ProbeError("oracle_verdict_invalid")
    return receipt


def _import_receipt(path: Path, seed_image_id: str) -> tuple[dict[str, Any], str]:
    receipt, receipt_sha256 = _json_file(path)
    if set(receipt) != {
        "source_ref",
        "canonical_ref",
        "immutable_ref",
        "content_digest",
        "archive_digest",
        "platform",
        "size_bytes",
        "reused",
    }:
        raise ProbeError("import_shape_invalid")
    source = receipt["source_ref"]
    if (
        not isinstance(source, str)
        or re.fullmatch(r"axrun-django-seed-[a-z0-9-]+:[a-z0-9-]+", source) is None
    ):
        raise ProbeError("import_source_invalid")
    repository = source.split(":", 1)[0]
    canonical = "index.docker.io/library/" + source
    runtime = receipt["immutable_ref"]
    if (
        receipt["canonical_ref"] != canonical
        or not isinstance(runtime, str)
        or re.fullmatch(
            rf"index\.docker\.io/library/{re.escape(repository)}@sha256:[0-9a-f]{{64}}", runtime
        )
        is None
        or receipt["content_digest"] != runtime.rsplit("@", 1)[-1]
        or not isinstance(receipt["archive_digest"], str)
        or _SHA256.fullmatch(receipt["archive_digest"]) is None
        or receipt["platform"] != "linux/amd64"
        or type(receipt["size_bytes"]) is not int
        or receipt["size_bytes"] <= 0
        or type(receipt["reused"]) is not bool
    ):
        raise ProbeError("import_identity_invalid")
    inspected = subprocess.run(
        ["docker", "image", "inspect", source, "--format", "{{.Id}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if inspected.returncode != 0 or inspected.stdout.strip() != seed_image_id:
        raise ProbeError("import_source_tag_drift")
    return receipt, receipt_sha256


def _persist(path: Path, receipt: dict[str, Any]) -> None:
    atomic_write(path, canonical_json(receipt) + b"\n")


def _check_context(path: Path) -> None:
    if (
        platform.node() != EXPECTED_HOST
        or path.is_symlink()
        or path.resolve() != EXPECTED_CONTEXT_FILE
    ):
        raise ProbeError("host_or_context_path_invalid")
    config, _ = _json_file(path)
    contexts = config.get("contexts")
    if config.get("current_context") != "local" or not isinstance(contexts, dict):
        raise ProbeError("local_context_invalid")
    local = contexts.get("local")
    if not isinstance(local, dict) or local.get("endpoint") != "127.0.0.1:25000":
        raise ProbeError("local_endpoint_invalid")
    tls = local.get("tls")
    if (
        local.get("proxy_mode") != "direct"
        or not isinstance(tls, dict)
        or any(
            not isinstance(tls.get(key), str) or not tls[key] for key in ("ca_cert", "cert", "key")
        )
    ):
        raise ProbeError("local_transport_invalid")


def _checked_sealed_error(client: AxernClient, run_id: str, destination: Path) -> str:
    """Read a bounded public sealed error object if a failed Run produced one."""
    try:
        manifest = client.get_sealed_output_manifest(run_id)
        matches = [item for item in manifest if item.path == scanner.OUTPUT_PATH]
        if len(matches) != 1:
            return "sealed_audit_unavailable"
        item = matches[0]
        if item.status != "available" or not 0 < item.size_bytes <= scanner.MAX_AUDIT_OUTPUT:
            return "sealed_audit_unavailable"
        with destination.open("xb") as stream:
            os.chmod(destination, 0o600)
            checked = client.download_sealed_output(run_id, item.output_id, stream)
        data = destination.read_bytes()
        if (
            checked.output_id != item.output_id
            or len(data) != item.size_bytes
            or _sha(data) != item.sha256
        ):
            return "sealed_audit_integrity_error"
        value: object = json.loads(data)
        if isinstance(value, dict) and set(value) == {"error"}:
            error = value["error"]
            if isinstance(error, str) and re.fullmatch(r"[a-z0-9_]+", error):
                return error
    except Exception:
        return "sealed_audit_unavailable"
    return "runtime_run_failed"


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.absolute()
    native_oracle.check_private_output_destination(output_dir)
    native_oracle.check_native_docker()
    _check_context(args.context_file)
    if importlib.metadata.version("axern-sdk") != "0.12.1":
        raise ProbeError("public_sdk_version_invalid")
    sdk_path = Path(axern_sdk.__file__).resolve()
    if not sdk_path.is_relative_to(Path(sysconfig.get_paths()["purelib"]).resolve()):
        raise ProbeError("public_sdk_not_installed")
    manifest = asset_lock.validate_assets(args.assets_dir)
    manifest_sha256 = _sha(asset_lock.canonical_json(manifest))
    row = asset_lock.load_locked_row(args.assets_dir / "row.json")
    if args.oracle_sha256 != EXPECTED_ORACLE_SHA256:
        raise ProbeError("oracle_receipt_not_approved")
    native = _native_receipt(args.oracle_receipt, args.oracle_sha256, manifest_sha256)
    seed_image_id = cast(str, native["seed_image_id"])
    native_oracle.check_images(seed_image_id)
    imported, import_sha256 = _import_receipt(args.image_import_receipt, seed_image_id)
    if import_sha256 != EXPECTED_IMPORT_SHA256:
        raise ProbeError("image_import_receipt_not_approved")
    runtime_ref = cast(str, imported["immutable_ref"])
    request_bytes = scanner.build_request(row)
    script_bytes = scanner.runtime_scan_script()

    output_dir.mkdir(mode=0o700, parents=True)
    receipt_path = output_dir / "receipt.json"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "started",
        "oracle_receipt_sha256": args.oracle_sha256,
        "image_import_receipt_sha256": import_sha256,
        "runtime_image": runtime_ref,
        "seed_image_id": seed_image_id,
        "row_sha256": asset_lock.ROW_SHA256,
        "scanner_sha256": scanner.scanner_implementation_sha256(),
        "execution": None,
        "cleanup": "not_created",
    }
    _persist(receipt_path, receipt)
    client: AxernClient | None = None
    environment_id = ""
    terminal = False
    submission_started = False
    failure = ""
    try:
        client = AxernClient.from_context(str(args.context_file), "local")
        environment = client.create_environment(
            image_ref=runtime_ref, labels={"axrun.validation": "django-runtime-audit"}
        )
        environment_id = str(environment.id)
        receipt["execution"] = {"environment_id": environment_id, "run_id": "", "allocation_id": ""}
        _persist(receipt_path, receipt)
        if str(environment.spec.image.ref) != runtime_ref:
            raise ProbeError("environment_image_drift")
        with tempfile.TemporaryDirectory(prefix="inputs-", dir=output_dir) as temporary:
            root = Path(temporary)
            request = root / "request.json"
            script = root / "audit.py"
            request.write_bytes(request_bytes)
            script.write_bytes(script_bytes)
            os.chmod(request, 0o600)
            os.chmod(script, 0o600)
            plan = StagePlan(
                environment_id=environment_id,
                argv=("/usr/bin/python3", "/opt/axrun/django-image-audit.py"),
                cwd="/testbed",
                inputs=(
                    InputFile(str(request), scanner.REQUEST_PATH, _sha(request_bytes)),
                    InputFile(str(script), "/opt/axrun/django-image-audit.py", _sha(script_bytes)),
                ),
                outputs=(
                    OutputSpec(
                        scanner.OUTPUT_PATH,
                        media_type="application/json",
                        max_bytes=scanner.MAX_AUDIT_OUTPUT,
                    ),
                ),
                # This released local stack accepts scheduling requests but
                # does not advertise hard CPU/memory enforcement. The scanner
                # streams content with bounded Git helpers, byte/count limits,
                # and an in-process deadline. Do not present these as cgroup
                # hard limits or silently fall back after a rejected Run.
                resources=ResourceSpec(request_cpu="1", request_memory="2Gi"),
                timeout_seconds=scanner.AUDIT_TIMEOUT_SECONDS + 60,
                labels={"axrun.stage": "admission", "axrun.task": "django-12419"},
            )

            def bound(execution: Any) -> None:
                receipt["execution"] = asdict(execution)
                _persist(receipt_path, receipt)

            backend = AxernBackend(client)
            submission_started = True
            stage = backend.execute(plan, artifact_dir=output_dir / "artifacts", on_bound=bound)
        run = client.get_run(stage.execution.run_id)
        observed_terminal = _status_name(run) in {
            "RUN_STATUS_SUCCEEDED",
            "RUN_STATUS_FAILED",
            "RUN_STATUS_CANCELLED",
        }
        if (
            not observed_terminal
            or str(run.id) != stage.execution.run_id
            or str(run.environment_id) != environment_id
            or stage.execution.environment_id != environment_id
            or not stage.execution.allocation_id
            or str(run.allocation_id) != stage.execution.allocation_id
        ):
            raise ProbeError("run_terminal_identity_invalid")
        terminal = True
        receipt["run_status"] = _status_name(run)
        receipt["exit_code"] = stage.exit_code
        if receipt["run_status"] != "RUN_STATUS_SUCCEEDED" or stage.exit_code != 0:
            failure = _checked_sealed_error(
                client, stage.execution.run_id, output_dir / "sealed-error.json"
            )
            if failure == "runtime_run_failed":
                failure = "run_terminal_failure"
            receipt.update(status="blocked", reason_code=failure)
        else:
            artifact = stage.artifact_for_path(scanner.OUTPUT_PATH)
            data = Path(artifact.path).read_bytes()
            if len(data) != artifact.size_bytes or _sha(data) != artifact.sha256:
                raise ProbeError("sealed_audit_integrity_invalid")
            value: object = json.loads(data)
            if not isinstance(value, dict) or set(value) != {"machine", "request_deleted", "audit"}:
                raise ProbeError("sealed_audit_shape_invalid")
            if value["machine"] != "x86_64" or value["request_deleted"] is not True:
                raise ProbeError("runtime_platform_or_input_deletion_invalid")
            audit = scanner.check_audit_result(value["audit"], 1)
            status, reason = scanner.audit_status(audit)
            if (
                audit["git_all_object_count"] < 1
                or audit["git_all_object_count"] > scanner.MAX_GIT_OBJECTS
                or audit["git_all_object_bytes"] > 8 << 30
                or audit["filesystem_regular_file_count"] < 1
                or audit["filesystem_entry_count"] > 500_000
                or audit["filesystem_regular_file_bytes"] > 16 << 30
            ):
                raise ProbeError("audit_bounds_invalid")
            receipt.update(
                status="passed" if status == "passed" else "blocked",
                reason_code=reason,
                sealed_sha256=artifact.sha256,
                sealed_size_bytes=artifact.size_bytes,
                sealed_audit=audit,
            )
            if status != "passed":
                failure = reason
        _persist(receipt_path, receipt)
    except Exception as exc:
        if not failure:
            failure = str(exc) if isinstance(exc, ProbeError) else type(exc).__name__
        receipt.update(status="incomplete", reason_code=failure)
    finally:
        try:
            if client is not None and environment_id and (terminal or not submission_started):
                client.delete_environment(environment_id)
                try:
                    client.get_environment(environment_id)
                except SandboxNotFoundError:
                    receipt["cleanup"] = "deleted_verified"
                else:
                    receipt["cleanup"] = "delete_unverified"
            elif environment_id:
                receipt["cleanup"] = "retained_for_ambiguous_run"
        except Exception:
            receipt.update(
                status="incomplete", cleanup="delete_failed", reason_code="cleanup_failed"
            )
        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:
                receipt.update(status="incomplete", reason_code="client_close_failed")
            finally:
                if receipt["cleanup"] != "deleted_verified" and receipt["status"] == "passed":
                    receipt.update(status="incomplete", reason_code="cleanup_unverified")
                _persist(receipt_path, receipt)
    if receipt["status"] != "passed" or receipt["cleanup"] != "deleted_verified":
        raise ProbeError(cast(str, receipt.get("reason_code", "runtime_audit_incomplete")))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--oracle-receipt", type=Path, required=True)
    parser.add_argument("--oracle-sha256", required=True)
    parser.add_argument("--image-import-receipt", type=Path, required=True)
    parser.add_argument("--context-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = run_probe(args)
    except Exception as exc:
        code = str(exc) if isinstance(exc, ProbeError) else "runtime_probe_failed_closed"
        print(f"runtime probe failed closed: {code}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "reason_code": receipt["reason_code"],
                "execution": receipt["execution"],
                "cleanup": receipt["cleanup"],
                "runtime_image": receipt["runtime_image"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
