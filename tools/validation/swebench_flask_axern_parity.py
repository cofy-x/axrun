#!/usr/bin/env python3
"""Private, bounded Axern parity run for the unregistered official Flask instance.

This is not a suite runner or a public benchmark adapter. It consumes the pinned
native oracle's private assets, uses two pre-existing immutable Environments, and
prints only identities, digests, counts, and parity booleans. Full per-test results
remain under the Git-ignored .axrun/validation directory.
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
import sys
import sysconfig
import time
import uuid
from pathlib import Path
from typing import Any, cast

import axern_sdk
from axern_sdk import AxernClient

from axrun.adapters import StaticCandidateHarness
from axrun.adapters._candidate import load_candidate
from axrun.adapters.swebench_flask_official import SweBenchFlaskOfficialVerifierAdapter
from axrun.axern_backend import AxernBackend, _status_name
from axrun.candidates import GitPatchCandidateAdapter
from axrun.catalog import AdapterSelection
from axrun.datasets.swebench_flask_official import SweBenchFlaskOfficialResolver
from axrun.models import EpisodePhase, HarnessSpec, canonical_digest
from axrun.qualification import qualify_episode
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore
from axrun.tasks import GitWorktreeTaskAdapter

if __package__:
    from .swebench_flask_compare import ParityError, compare_empty, compare_scored
else:
    from swebench_flask_compare import ParityError, compare_empty, compare_scored

_SDK_VERSION = "0.12.0"
_ENDPOINT = "127.0.0.1:25000"
_SOURCE_IMAGE = (
    "docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014"
    "@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4"
)
_CANONICAL_SOURCE_IMAGE = _SOURCE_IMAGE.replace("docker.io/", "index.docker.io/", 1)
_ROW_SHA256 = "36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e"
_ORACLE_RECEIPT_SHA256 = "e16e32a970bf18028ca37f186440d1c064203525f909ad034d8a16c59c18856c"
_GOLD_PATCH_SHA256 = "087d51d66413bfa35111ac0eca31f1db1636572702cfd967c428049b453f451d"
_KNOWN_BAD_PATCH_SHA256 = "174037c0c2018173a2fe413b5b8ec30bd4900365b488588fcec3243f433b8114"
_GOLD_GRADE_SHA256 = "bddca4fbdf735900724faee6494a3c3acdeb6e78fcf813e7ef6147dc7659cd51"
_KNOWN_BAD_GRADE_SHA256 = "4c74cb52462c87d522b4482ff7345d4d5f49d4241df4d5f432579c5eed1a30f9"
_EMPTY_REPORT_SHA256 = "09810ce087eefcfc908446ce94e1e86a2c12a12c90c88234ed311cd1dcb0c46f"
_MAX_INPUT_BYTES = 16 << 20
_EVIDENCE_ROOT = Path(__file__).parents[2] / ".axrun/validation/swebench-flask-5014"
_PATH_ARGUMENTS = frozenset(
    {
        "context_config",
        "row",
        "image_import_receipt",
        "wheelhouse",
        "oracle_receipt",
        "gold_patch",
        "known_bad_patch",
        "official_gold_grade",
        "official_known_bad_grade",
        "official_empty_report",
    }
)
_CONFIG_KEYS = _PATH_ARGUMENTS | {
    "endpoint",
    "inference_environment_id",
    "verification_environment_id",
}


class ValidationError(RuntimeError):
    """Stable, non-sensitive validation failure."""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("input_duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValidationError("input_invalid_json_constant")


def _bounded_file(path: Path, *, max_bytes: int = _MAX_INPUT_BYTES) -> bytes:
    try:
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            raise ValidationError("input_not_regular_file")
        if path.stat().st_size > max_bytes:
            raise ValidationError("input_too_large")
        data = path.read_bytes()
    except OSError as exc:
        raise ValidationError("input_unavailable") from exc
    if len(data) > max_bytes:
        raise ValidationError("input_too_large")
    return data


def _locked_file(path: Path, expected_sha256: str, *, max_bytes: int = _MAX_INPUT_BYTES) -> bytes:
    data = _bounded_file(path, max_bytes=max_bytes)
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValidationError("input_digest_mismatch")
    return data


def _json_object(data: bytes) -> dict[str, Any]:
    try:
        value: Any = json.loads(
            data, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("input_invalid_json") from exc
    if not isinstance(value, dict):
        raise ValidationError("input_not_json_object")
    return cast(dict[str, Any], value)


def _official_row(path: Path) -> dict[str, Any]:
    row = _json_object(_bounded_file(path))
    if canonical_digest(row) != _ROW_SHA256:
        raise ValidationError("official_row_digest_mismatch")
    return row


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--endpoint")
    for name in sorted(_PATH_ARGUMENTS):
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path)
    parser.add_argument("--inference-environment-id")
    parser.add_argument("--verification-environment-id")
    args = parser.parse_args(argv)
    if args.config is not None:
        if any(getattr(args, key) is not None for key in _CONFIG_KEYS):
            parser.error("--config cannot be combined with explicit validation inputs")
        config = _json_object(_bounded_file(args.config, max_bytes=1 << 20))
        if set(config) != _CONFIG_KEYS or any(
            not isinstance(value, str) or not value for value in config.values()
        ):
            raise ValidationError("validation_config_invalid_shape")
        repo = Path(__file__).parents[2]
        for key in _PATH_ARGUMENTS:
            path = Path(cast(str, config[key]))
            setattr(args, key, path if path.is_absolute() else repo / path)
        for key in _CONFIG_KEYS - _PATH_ARGUMENTS:
            setattr(args, key, config[key])
    elif any(getattr(args, key) is None for key in _CONFIG_KEYS):
        parser.error("all explicit validation inputs are required without --config")
    return args


def _check_host_and_sdk() -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValidationError("native_linux_amd64_required")
    if importlib.metadata.version("axern-sdk") != _SDK_VERSION:
        raise ValidationError("released_sdk_version_mismatch")
    sdk_path = Path(axern_sdk.__file__).resolve()
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    if not sdk_path.is_relative_to(site_packages):
        raise ValidationError("sdk_not_installed_in_site_packages")


def _client(endpoint: str, context_config: Path) -> AxernClient:
    if endpoint != _ENDPOINT:
        raise ValidationError("endpoint_not_forge_loopback")
    config = _json_object(_bounded_file(context_config, max_bytes=1 << 20))
    if config.get("current_context") != "local":
        raise ValidationError("axern_local_context_not_selected")
    contexts = config.get("contexts")
    if not isinstance(contexts, dict) or not isinstance(contexts.get("local"), dict):
        raise ValidationError("axern_context_invalid")
    context = cast(dict[str, Any], contexts["local"])
    if context.get("endpoint") != endpoint or not isinstance(context.get("tls"), dict):
        raise ValidationError("axern_context_endpoint_or_tls_mismatch")
    tls = cast(dict[str, Any], context["tls"])
    if any(not isinstance(tls.get(key), str) or not tls[key] for key in ("ca_cert", "cert", "key")):
        raise ValidationError("axern_context_tls_incomplete")
    return AxernClient.from_env(
        target=endpoint,
        tls_ca_cert=tls["ca_cert"],
        tls_cert=tls["cert"],
        tls_key=tls["key"],
        tls_server_name="gatewayd",
        proxy_mode="direct",
    )


def _selection() -> AdapterSelection:
    static = StaticCandidateHarness()
    return AdapterSelection(
        task=GitWorktreeTaskAdapter(name="swebench-flask-official"),
        inference=static,
        candidate=GitPatchCandidateAdapter(),
        verifier=SweBenchFlaskOfficialVerifierAdapter(),
        trajectory=None,
        runtime=static.runtime_requirements,
    )


def _image_import_receipt(path: Path) -> dict[str, str]:
    raw = _json_object(_bounded_file(path, max_bytes=1 << 20))
    expected = {"source_ref", "canonical_ref", "immutable_ref", "content_digest", "platform"}
    if set(raw) != expected or any(
        not isinstance(value, str) or not value for value in raw.values()
    ):
        raise ValidationError("image_import_receipt_invalid")
    receipt = cast(dict[str, str], raw)
    runtime = receipt["immutable_ref"]
    if (
        receipt["source_ref"] != _SOURCE_IMAGE
        or receipt["canonical_ref"] != _CANONICAL_SOURCE_IMAGE
        or receipt["platform"] != "linux/amd64"
        or re.fullmatch(
            rf"{re.escape(_CANONICAL_SOURCE_IMAGE.split('@', 1)[0])}@sha256:[0-9a-f]{{64}}",
            runtime,
        )
        is None
        or receipt["content_digest"] != runtime.rsplit("@", 1)[-1]
    ):
        raise ValidationError("image_import_receipt_identity_mismatch")
    return receipt


def _check_environment(client: AxernClient, environment_id: str, image: str) -> None:
    actual = str(client.get_environment(environment_id).spec.image.ref)
    if actual != image:
        raise ValidationError("environment_image_mismatch")


def _terminal_execution(client: AxernClient, run_id: str, allocation_id: str) -> str:
    if not run_id or not allocation_id:
        raise ValidationError("run_allocation_identity_incomplete")
    run = client.get_run(run_id)
    status = _status_name(run)
    if status != "RUN_STATUS_SUCCEEDED" or str(run.allocation_id) != allocation_id:
        raise ValidationError("run_not_succeeded_or_allocation_drift")
    return status


def _sealed_summary(
    client: AxernClient, run_id: str, path: str, downloaded: Path, expected_sha256: str
) -> dict[str, Any]:
    try:
        if downloaded.is_symlink() or not stat.S_ISREG(downloaded.lstat().st_mode):
            raise ValidationError("sealed_download_not_regular_file")
        content = downloaded.read_bytes()
    except OSError as exc:
        raise ValidationError("sealed_download_unavailable") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValidationError("sealed_download_digest_mismatch")
    manifest = client.get_sealed_output_manifest(run_id)
    matches = [item for item in manifest if item.path == path]
    if (
        len(matches) != 1
        or matches[0].status != "available"
        or int(matches[0].size_bytes) != len(content)
    ):
        raise ValidationError("sealed_output_manifest_mismatch")
    return {"bytes": len(content), "sha256": digest}


def _persist(root: Path, receipt: dict[str, Any]) -> None:
    payload = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
    destination = root / "receipt.json"
    temporary = root / ".receipt.json.tmp"
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)


def _private_root() -> Path:
    root = _EVIDENCE_ROOT / f"axern-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    return root.resolve()


def _check_fresh(used: set[str], value: str, kind: str) -> None:
    if not value or value in used:
        raise ValidationError(f"{kind}_not_fresh")
    used.add(value)


def _case(
    *,
    case: str,
    episode_id: str,
    patch: Path,
    official: Path,
    row: dict[str, Any],
    import_receipt: dict[str, str],
    wheelhouse: Path,
    inference_environment_id: str,
    verification_environment_id: str,
    client: AxernClient,
    backend: AxernBackend,
    store: EpisodeStore,
    root: Path,
    seen_runs: set[str],
    seen_allocations: set[str],
) -> dict[str, Any]:
    episode = SweBenchFlaskOfficialResolver().resolve(
        row,
        asset_dir=root / "resolved-assets",
        episode_id=episode_id,
        inference_environment_id=inference_environment_id,
        verification_environment_id=verification_environment_id,
        task_image=import_receipt["immutable_ref"],
        image_import_receipt=import_receipt,
        wheelhouse_dir=wheelhouse,
        harness=HarnessSpec("static-candidate", "1"),
        static_candidate_file=patch,
    )
    selected = _selection()
    qualification = qualify_episode(
        episode, client=client, backend=backend, store=store, selection=selected
    )
    qualifications: list[dict[str, Any]] = []
    for target in qualification.targets:
        _check_fresh(seen_runs, target.run_id, "run")
        _check_fresh(seen_allocations, target.allocation_id, "allocation")
        status = _terminal_execution(client, target.run_id, target.allocation_id)
        sealed = _sealed_summary(
            client,
            target.run_id,
            "/outputs/qualification.json",
            root
            / "state"
            / "qualification-artifacts"
            / episode_id
            / target.role
            / "00-qualification.json",
            target.output_sha256,
        )
        qualifications.append(
            {
                "role": target.role,
                "run_id": target.run_id,
                "allocation_id": target.allocation_id,
                "terminal_status": status,
                "sealed_output": sealed,
            }
        )
    result = EpisodeRunner(backend=backend, store=store).run(
        episode,
        inference=selected.inference,
        candidate=selected.candidate,
        verifier=selected.verifier,
        trajectory=selected.trajectory,
    )
    record = store.load(episode_id)
    if (
        record is None
        or record.phase != EpisodePhase.COMPLETED
        or record.inference is None
        or record.verification is None
        or record.inference.environment_id != inference_environment_id
        or record.verification.environment_id != verification_environment_id
    ):
        raise ValidationError("episode_not_complete_or_environment_drift")
    inference = record.inference
    verification = record.verification
    for execution in (inference, verification):
        _check_fresh(seen_runs, execution.run_id, "run")
        _check_fresh(seen_allocations, execution.allocation_id, "allocation")
    inference_status = _terminal_execution(client, inference.run_id, inference.allocation_id)
    verification_status = _terminal_execution(
        client, verification.run_id, verification.allocation_id
    )
    candidate = load_candidate(Path(record.candidate_manifest))
    if candidate.digest != record.candidate_digest or result.candidate_digest != candidate.digest:
        raise ValidationError("candidate_result_digest_mismatch")
    patch_file = candidate.files[0]
    if patch_file.role != "patch" or len(candidate.files) != 1:
        raise ValidationError("candidate_bundle_role_mismatch")
    artifact_dir = root / "state" / "artifacts" / episode_id
    sealed = {
        "candidate.patch": _sealed_summary(
            client,
            inference.run_id,
            "/outputs/candidate.patch",
            artifact_dir / "inference" / "00-candidate.patch",
            patch_file.sha256,
        ),
        "verification.json": _sealed_summary(
            client,
            verification.run_id,
            "/outputs/verification.json",
            artifact_dir / "verification" / "00-verification.json",
            result.output_digest,
        ),
        "verifier.log": _sealed_summary(
            client,
            verification.run_id,
            "/outputs/verifier.log",
            artifact_dir / "verification" / "01-verifier.log",
            str(result.details["test_output_sha256"]),
        ),
    }
    if sealed["candidate.patch"]["bytes"] != patch_file.size_bytes:
        raise ValidationError("candidate_patch_length_mismatch")
    loaded_result = store.load_result(record.verification_result, record.verification_result_digest)
    if loaded_result != result:
        raise ValidationError("verification_result_record_mismatch")
    parity = (
        compare_empty(official, Path(record.verification_result))
        if case == "empty"
        else compare_scored(official, Path(record.verification_result))
    )
    if not parity["parity"]:
        raise ValidationError("official_test_level_parity_mismatch")
    expected_verdict = "passed" if case == "gold" else "failed"
    expected_score = None if case == "empty" else 1.0 if case == "gold" else 0.0
    if result.verdict != expected_verdict or result.score != expected_score:
        raise ValidationError("deterministic_control_result_mismatch")
    return {
        "case": case,
        "episode_id": episode_id,
        "seed_digest": episode.seed_digest,
        "qualification": qualifications,
        "inference": {
            "run_id": inference.run_id,
            "allocation_id": inference.allocation_id,
            "terminal_status": inference_status,
        },
        "candidate_digest": candidate.digest,
        "verification": {
            "run_id": verification.run_id,
            "allocation_id": verification.allocation_id,
            "terminal_status": verification_status,
        },
        "sealed_outputs": sealed,
        "verification_result_digest": record.verification_result_digest,
        "verdict": result.verdict,
        "score": result.score,
        "diagnostic_code": result.diagnostic_code,
        "parity": parity,
    }


def main() -> int:
    # This deterministic validation never uses a model. Discard even an inherited
    # caller key before opening the SDK client or creating any Run.
    os.environ.pop("DEEPSEEK_API_KEY", None)
    try:
        args = _parse_args(sys.argv[1:])
    except ValidationError as exc:
        print(f"Flask Axern parity failed closed: {exc}", flush=True)
        return 2
    os.umask(0o077)
    root = _private_root()
    receipt: dict[str, Any] = {
        "schema_version": "axrun.swebench-flask-axern-parity@1",
        "status": "started",
        "platform": "linux/amd64",
        "axern_sdk": _SDK_VERSION,
        "task_image_source": "",
        "task_image_runtime": "",
        "inference_environment_id": args.inference_environment_id,
        "verification_environment_id": args.verification_environment_id,
        "oracle_receipt_sha256": _ORACLE_RECEIPT_SHA256,
        "environment_cleanup": "caller_owned_retained",
        "cases": [],
    }
    _persist(root, receipt)
    client: AxernClient | None = None
    exit_code = 1
    try:
        _check_host_and_sdk()
        if (
            not args.inference_environment_id
            or not args.verification_environment_id
            or args.inference_environment_id == args.verification_environment_id
        ):
            raise ValidationError("fresh_environment_binding_required")
        row = _official_row(args.row)
        _locked_file(args.oracle_receipt, _ORACLE_RECEIPT_SHA256)
        gold_patch = _locked_file(args.gold_patch, _GOLD_PATCH_SHA256)
        _locked_file(args.known_bad_patch, _KNOWN_BAD_PATCH_SHA256)
        _locked_file(args.official_gold_grade, _GOLD_GRADE_SHA256)
        _locked_file(args.official_known_bad_grade, _KNOWN_BAD_GRADE_SHA256)
        _locked_file(args.official_empty_report, _EMPTY_REPORT_SHA256)
        if gold_patch != row.get("patch", "").encode():
            raise ValidationError("gold_patch_differs_from_locked_row")
        import_receipt = _image_import_receipt(args.image_import_receipt)
        image = import_receipt["immutable_ref"]
        receipt["task_image_source"] = _SOURCE_IMAGE
        receipt["task_image_runtime"] = image
        _persist(root, receipt)
        client = _client(args.endpoint, args.context_config)
        _check_environment(client, args.inference_environment_id, image)
        _check_environment(client, args.verification_environment_id, image)
        backend = AxernBackend(client)
        store = EpisodeStore(root / "state")
        empty_patch = root / "empty.patch"
        empty_patch.write_bytes(b"")
        seen_runs: set[str] = set()
        seen_allocations: set[str] = set()
        for case, patch, official in (
            ("gold", args.gold_patch, args.official_gold_grade),
            ("known_bad", args.known_bad_patch, args.official_known_bad_grade),
            ("empty", empty_patch, args.official_empty_report),
        ):
            episode_id = f"flask-5014-{case}-{uuid.uuid4().hex}"
            receipt["active_case"] = case
            receipt["active_episode_id"] = episode_id
            _persist(root, receipt)
            summary = _case(
                case=case,
                episode_id=episode_id,
                patch=patch,
                official=official,
                row=row,
                import_receipt=import_receipt,
                wheelhouse=args.wheelhouse,
                inference_environment_id=args.inference_environment_id,
                verification_environment_id=args.verification_environment_id,
                client=client,
                backend=backend,
                store=store,
                root=root,
                seen_runs=seen_runs,
                seen_allocations=seen_allocations,
            )
            cast(list[dict[str, Any]], receipt["cases"]).append(summary)
            receipt.pop("active_case")
            receipt.pop("active_episode_id")
            _persist(root, receipt)
        if len(receipt["cases"]) != 3:
            raise ValidationError("deterministic_cases_incomplete")
        receipt["status"] = "complete"
        exit_code = 0
    except Exception as exc:
        receipt["status"] = "failed_closed"
        receipt["failure_type"] = type(exc).__name__
        if isinstance(exc, (ValidationError, ParityError)):
            receipt["failure_reason"] = str(exc)
        active_episode_id = receipt.get("active_episode_id")
        if isinstance(active_episode_id, str):
            try:
                record = EpisodeStore(root / "state").load(active_episode_id)
                if record is not None:
                    receipt["active_inference_run_id"] = (
                        record.inference.run_id if record.inference else None
                    )
                    receipt["active_inference_allocation_id"] = (
                        record.inference.allocation_id if record.inference else None
                    )
                    receipt["active_verification_run_id"] = (
                        record.verification.run_id if record.verification else None
                    )
                    receipt["active_verification_allocation_id"] = (
                        record.verification.allocation_id if record.verification else None
                    )
                    receipt["active_diagnostic_code"] = record.diagnostic_code
            except Exception:
                pass
        print(f"Flask Axern parity failed closed: {type(exc).__name__}", flush=True)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                receipt["status"] = "failed_closed"
                receipt["client_cleanup"] = "failed"
                exit_code = 1
            else:
                receipt["client_cleanup"] = "closed"
        _persist(root, receipt)
        print(f"private_evidence={root}", flush=True)
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
