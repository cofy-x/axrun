#!/usr/bin/env python3
"""One private real-Claude acceptance after locked Flask deterministic parity.

This is deliberately not a catalog entry or a suite runner. The caller supplies
two fresh, task-image-backed Environments in a closed, non-secret config. Full
test identities and sealed artifacts remain in the Git-ignored evidence root;
stdout and the receipt contain only bounded identities, digests and counts.
"""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, cast

from axern_sdk import AxernClient, SandboxNotFoundError, TunnelConnector

from axrun.adapters._candidate import load_candidate
from axrun.adapters.swebench_flask_official import SweBenchFlaskOfficialVerifierAdapter
from axrun.axern_backend import AxernBackend
from axrun.candidates import GitPatchCandidateAdapter
from axrun.catalog import AdapterSelection, resolve_model_protocol
from axrun.datasets.swebench_flask_official import SweBenchFlaskOfficialResolver
from axrun.harnesses import ClaudeCodeHarness
from axrun.lifecycle.base import CompositePreStartLifecycle
from axrun.lifecycle.model_tunnel import ModelTunnelLifecycle
from axrun.lifecycle.stage_progress import StageProgressObserver
from axrun.models import EpisodePhase, HarnessSpec, StageNetworkPolicy, canonical_json
from axrun.proxy.model import ModelProxy
from axrun.qualification import qualify_episode
from axrun.report import verify_record
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore
from axrun.tasks import GitWorktreeTaskAdapter
from axrun.trajectories.adapters import ClaudeCodeTrajectoryAdapter
from axrun.trajectories.bundle import load_trajectory_bundle

# Reuse the companion private validator's locked inputs and public-SDK checks.
if __package__:
    from . import swebench_flask_axern_parity as parity
    from . import swebench_flask_image_secrecy as image_secrecy
else:
    import swebench_flask_axern_parity as parity
    import swebench_flask_image_secrecy as image_secrecy


_EVIDENCE_ROOT = Path(__file__).parents[2] / ".axrun/validation/swebench-flask-5014"
_ROOTFS_IMAGE = (
    "index.docker.io/library/axrun-claude-code-rootfs"
    "@sha256:df44581291434e694b4f9f054be19df394653d0e1fc5c1e893ed754cbe3fb13b"
)
_UPSTREAM = "https://api.deepseek.com/anthropic"
_CREDENTIAL_ENV = "DEEPSEEK_API_KEY"
_GRPC_STATUS_NAMES = frozenset(
    {
        "CANCELLED",
        "UNKNOWN",
        "INVALID_ARGUMENT",
        "DEADLINE_EXCEEDED",
        "NOT_FOUND",
        "ALREADY_EXISTS",
        "PERMISSION_DENIED",
        "RESOURCE_EXHAUSTED",
        "FAILED_PRECONDITION",
        "ABORTED",
        "OUT_OF_RANGE",
        "UNIMPLEMENTED",
        "INTERNAL",
        "UNAVAILABLE",
        "DATA_LOSS",
        "UNAUTHENTICATED",
    }
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_EPISODE_ID = re.compile(r"^flask-5014-(?:gold|known_bad|empty)-[0-9a-f]{32}$")
_PATH_KEYS = frozenset(
    {
        "context_config",
        "row",
        "image_import_receipt",
        "wheelhouse",
        "parity_receipt",
        "image_safety_receipt",
    }
)
_CONFIG_KEYS = _PATH_KEYS | {
    "endpoint",
    "parity_receipt_sha256",
    "image_safety_receipt_sha256",
    "image_safety_image_id",
    "inference_environment_id",
    "verification_environment_id",
    "claude_rootfs_image",
    "model_upstream_url",
    "model",
    "default_opus_model",
    "default_sonnet_model",
    "default_haiku_model",
    "subagent_model",
    "effort_level",
    "auto_compact_window",
    "max_turns",
}
_PARITY_KEYS = {
    "schema_version",
    "status",
    "platform",
    "axern_sdk",
    "task_image_source",
    "task_image_runtime",
    "inference_environment_id",
    "verification_environment_id",
    "oracle_receipt_sha256",
    "environment_cleanup",
    "cases",
    "client_cleanup",
}
_CASE_KEYS = {
    "case",
    "episode_id",
    "seed_digest",
    "qualification",
    "inference",
    "candidate_digest",
    "verification",
    "sealed_outputs",
    "verification_result_digest",
    "verdict",
    "score",
    "diagnostic_code",
    "parity",
}
_SCORING_CHECKS = {
    "classification",
    "all_test_statuses",
    "test_category_arrays",
    "missing_expected",
    "resolution",
    "score",
    "diagnostic",
    "eval_exit_code",
}
_EMPTY_CHECKS = {
    "classification",
    "no_fabricated_statuses",
    "unscored",
    "verdict",
    "diagnostic",
    "no_test_execution",
}
_PARITY_SUMMARY_KEYS = {
    "schema_version",
    "case",
    "parity",
    "official_sha256",
    "axrun_verification_sha256",
    "expected_tests",
    "official_observed_tests",
    "axrun_observed_tests",
    "checks",
}
_SEALED = (
    ("candidate.patch", "/outputs/candidate.patch"),
    ("trajectory.jsonl", "/outputs/trajectory.jsonl"),
    ("harness.log", "/outputs/harness.log"),
    ("usage.json", "/outputs/usage.json"),
)


class ValidationError(parity.ValidationError):
    """A stable, non-sensitive failure reason."""


class _TunnelCleanupEvidence:
    """Track only public session identity in memory, never the connector token."""

    def __init__(self, client: AxernClient) -> None:
        self.client = client
        self.session_id = ""
        self.revoked = False
        self.create_error_type = ""
        self.create_grpc_status = ""

    def create_tunnel_session(self, **kwargs: Any) -> Any:
        try:
            response = self.client.create_tunnel_session(**kwargs)
        except Exception as exc:
            name = type(exc).__name__
            self.create_error_type = (
                name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) else "unknown"
            )
            status_fn = getattr(exc, "code", None)
            if callable(status_fn):
                try:
                    status = status_fn()
                    status_name = getattr(status, "name", "")
                    if status_name in _GRPC_STATUS_NAMES:
                        self.create_grpc_status = status_name
                except Exception:
                    pass
            raise
        self.session_id = str(response.session.session_id)
        return response

    def revoke_tunnel_session(self, session_id: str, **kwargs: Any) -> Any:
        result = self.client.revoke_tunnel_session(session_id, **kwargs)
        self.revoked = bool(self.session_id and session_id == self.session_id)
        return result

    def connector_factory(self, **kwargs: Any) -> TunnelConnector:
        # Connector receives the real released-SDK client. The token remains
        # transient caller memory and never enters this evidence object's state.
        return TunnelConnector(
            client=self.client,
            session=kwargs["session"],
            client_token=kwargs["client_token"],
            local_target=kwargs["local_target"],
        )


def _config(path: Path) -> dict[str, Any]:
    raw = parity._json_object(parity._bounded_file(path, max_bytes=1 << 20))
    if set(raw) != set(_CONFIG_KEYS):
        raise ValidationError("claude_config_invalid_shape")
    config = dict(raw)
    repo = Path(__file__).parents[2]
    for key in _PATH_KEYS:
        value = config[key]
        if not isinstance(value, str) or not value:
            raise ValidationError("claude_config_invalid_path")
        location = Path(value)
        config[key] = location if location.is_absolute() else repo / location
    for key in _CONFIG_KEYS - _PATH_KEYS - {"auto_compact_window", "max_turns"}:
        value = config[key]
        if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
            raise ValidationError("claude_config_invalid_value")
    for key in ("auto_compact_window", "max_turns"):
        value = config[key]
        if type(value) is not int or value <= 0:
            raise ValidationError("claude_config_invalid_limit")
    if (
        config["endpoint"] != parity._ENDPOINT
        or config["claude_rootfs_image"] != _ROOTFS_IMAGE
        or config["model_upstream_url"] != _UPSTREAM
        or config["effort_level"] != "max"
        or config["auto_compact_window"] != 786432
        or not 1 <= config["max_turns"] <= 200
        or _DIGEST.fullmatch(config["parity_receipt_sha256"]) is None
        or _DIGEST.fullmatch(config["image_safety_receipt_sha256"]) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", config["image_safety_image_id"]) is None
    ):
        raise ValidationError("claude_config_identity_mismatch")
    # Model IDs are opaque to Axrun; these exact acceptance values are a caller
    # decision, not a DeepSeek-specific branch in the reusable harness.
    expected_models = {
        "model": "deepseek-flash",
        "default_opus_model": "deepseek-flash[1m]",
        "default_sonnet_model": "deepseek-flash[1m]",
        "default_haiku_model": "deepseek-flash",
        "subagent_model": "deepseek-flash",
    }
    if any(config[key] != value for key, value in expected_models.items()):
        raise ValidationError("claude_config_model_mismatch")
    return config


def _image_safety_gate(
    path: Path,
    expected_digest: str,
    *,
    expected_image_id: str,
    row: dict[str, Any],
    task_image: str,
    image_import: dict[str, str],
) -> str:
    try:
        receipt = parity._json_object(parity._locked_file(path, expected_digest, max_bytes=1 << 20))
    except parity.ValidationError as exc:
        raise ValidationError("image_safety_receipt_integrity_invalid") from exc
    expected_keys = {
        "schema_version",
        "instance_id",
        "row_sha256",
        "source_image",
        "image_id",
        "test_patch_sha256",
        "gold_patch_sha256",
        "status",
        "reason_code",
    } | set(image_secrecy._AUDIT_FIELDS)
    if set(receipt) != expected_keys:
        raise ValidationError("image_safety_receipt_shape_invalid")
    if (
        receipt["schema_version"] != image_secrecy.SCHEMA
        or receipt["instance_id"] != "pallets__flask-5014"
        or receipt["row_sha256"] != parity._ROW_SHA256
        or receipt["source_image"] != parity._SOURCE_IMAGE
        or receipt["source_image"] != image_import["source_ref"]
        or receipt["image_id"] != expected_image_id
        or task_image != image_import["immutable_ref"]
        or receipt["image_head"] != image_secrecy.IMAGE_HEAD
        or receipt["test_patch_sha256"]
        != hashlib.sha256(str(row["test_patch"]).encode()).hexdigest()
        or receipt["gold_patch_sha256"] != hashlib.sha256(str(row["patch"]).encode()).hexdigest()
    ):
        raise ValidationError("image_safety_identity_mismatch")
    details = {key: receipt[key] for key in image_secrecy._AUDIT_FIELDS}
    try:
        checked = image_secrecy._check_audit(details, int(receipt["test_target_count"]))
        recomputed_status, recomputed_reason = image_secrecy._status(checked)
    except (image_secrecy.SecrecyError, TypeError, ValueError) as exc:
        raise ValidationError("image_safety_attestation_invalid") from exc
    if (
        type(receipt["test_target_count"]) is not int
        or receipt["test_target_count"] <= 0
        or type(receipt["gold_target_count"]) is not int
        or receipt["gold_target_count"] <= 0
        or receipt["status"] != "passed"
        or receipt["reason_code"] != "no_locked_patch_signatures_reachable"
        or recomputed_status != receipt["status"]
        or recomputed_reason != receipt["reason_code"]
    ):
        raise ValidationError("image_safety_not_passed")
    return expected_digest


def _selection() -> AdapterSelection:
    claude = ClaudeCodeHarness()
    return AdapterSelection(
        task=GitWorktreeTaskAdapter(name="swebench-flask-official"),
        inference=claude,
        candidate=GitPatchCandidateAdapter(),
        verifier=SweBenchFlaskOfficialVerifierAdapter(),
        trajectory=ClaudeCodeTrajectoryAdapter(),
        runtime=claude.runtime_requirements,
    )


def _run_identity(client: AxernClient, raw: object, seen: set[str]) -> tuple[str, str]:
    if not isinstance(raw, dict):
        raise ValidationError("parity_run_shape_invalid")
    values = cast(dict[str, Any], raw)
    if set(values) != {"run_id", "allocation_id", "terminal_status"}:
        raise ValidationError("parity_run_shape_invalid")
    run_id, allocation_id = values["run_id"], values["allocation_id"]
    if (
        not isinstance(run_id, str)
        or not isinstance(allocation_id, str)
        or not run_id.startswith("run-")
        or not allocation_id.startswith("alloc-")
        or run_id in seen
        or values["terminal_status"] != "RUN_STATUS_SUCCEEDED"
    ):
        raise ValidationError("parity_run_identity_invalid")
    seen.add(run_id)
    parity._terminal_execution(client, run_id, allocation_id)
    return run_id, allocation_id


def _parity_gate(
    path: Path,
    expected_digest: str,
    *,
    client: AxernClient,
    task_image: str,
    model_environment_ids: tuple[str, str],
) -> tuple[str, set[str], set[str]]:
    receipt = parity._json_object(parity._locked_file(path, expected_digest, max_bytes=1 << 20))
    if set(receipt) != _PARITY_KEYS or (
        receipt["schema_version"] != "axrun.swebench-flask-axern-parity@1"
        or receipt["status"] != "complete"
        or receipt["platform"] != "linux/amd64"
        or receipt["axern_sdk"] != parity._SDK_VERSION
        or receipt["task_image_source"] != parity._SOURCE_IMAGE
        or receipt["task_image_runtime"] != task_image
        or receipt["oracle_receipt_sha256"] != parity._ORACLE_RECEIPT_SHA256
        or receipt["environment_cleanup"] != "caller_owned_retained"
        or receipt["client_cleanup"] != "closed"
    ):
        raise ValidationError("deterministic_parity_receipt_invalid")
    old_environments = (
        receipt["inference_environment_id"],
        receipt["verification_environment_id"],
    )
    if (
        any(
            not isinstance(value, str) or not value.startswith("env-") for value in old_environments
        )
        or len(set((*old_environments, *model_environment_ids))) != 4
    ):
        raise ValidationError("model_environment_not_fresh")
    raw_cases: object = receipt["cases"]
    if not isinstance(raw_cases, list):
        raise ValidationError("deterministic_parity_cases_invalid")
    cases = cast(list[Any], raw_cases)
    if len(cases) != 3:
        raise ValidationError("deterministic_parity_cases_invalid")
    state = EpisodeStore(path.parent / "state")
    seen_runs: set[str] = set()
    seen_allocations: set[str] = set()
    for expected_case, raw_item in zip(("gold", "known_bad", "empty"), cases, strict=True):
        if not isinstance(raw_item, dict):
            raise ValidationError("deterministic_parity_case_shape_invalid")
        item = cast(dict[str, Any], raw_item)
        if set(item) != _CASE_KEYS or item["case"] != expected_case:
            raise ValidationError("deterministic_parity_case_shape_invalid")
        episode_id = item["episode_id"]
        if not isinstance(episode_id, str) or _EPISODE_ID.fullmatch(episode_id) is None:
            raise ValidationError("deterministic_parity_episode_invalid")
        raw_checked: object = item["parity"]
        checked = cast(dict[str, Any], raw_checked) if isinstance(raw_checked, dict) else None
        if (
            not isinstance(checked, dict)
            or set(checked) != _PARITY_SUMMARY_KEYS
            or checked.get("schema_version") != "axrun.swebench-flask-parity@1"
            or checked.get("parity") is not True
            or checked.get("case") != ("empty" if expected_case == "empty" else "scored")
            or not isinstance(checked.get("checks"), dict)
            or set(checked["checks"])
            != (_EMPTY_CHECKS if expected_case == "empty" else _SCORING_CHECKS)
            or any(value is not True for value in checked["checks"].values())
        ):
            raise ValidationError("deterministic_test_level_parity_missing")
        record = state.load(episode_id)
        if (
            record is None
            or record.phase != EpisodePhase.COMPLETED
            or record.inference is None
            or record.verification is None
            or record.candidate_digest != item["candidate_digest"]
            or record.verification_result_digest != item["verification_result_digest"]
        ):
            raise ValidationError("deterministic_parity_record_mismatch")
        episode = state.load_spec(episode_id)
        if (
            episode.seed_digest != item["seed_digest"]
            or episode.inference_environment.environment_id != old_environments[0]
            or episode.verification_environment.environment_id != old_environments[1]
            or episode.inference_environment.image != task_image
            or episode.verification_environment.image != task_image
        ):
            raise ValidationError("deterministic_parity_episode_mismatch")
        candidate = load_candidate(Path(record.candidate_manifest))
        result = state.load_result(record.verification_result, record.verification_result_digest)
        if (
            candidate.digest != record.candidate_digest
            or result.candidate_digest != candidate.digest
            or result.verdict != item["verdict"]
            or result.score != item["score"]
            or result.diagnostic_code != item["diagnostic_code"]
        ):
            raise ValidationError("deterministic_parity_result_mismatch")
        result_bytes = parity._bounded_file(Path(record.verification_result))
        if hashlib.sha256(result_bytes).hexdigest() != checked.get("axrun_verification_sha256"):
            raise ValidationError("deterministic_parity_result_file_mismatch")
        raw_qualifications: object = item["qualification"]
        if not isinstance(raw_qualifications, list):
            raise ValidationError("deterministic_parity_qualification_invalid")
        qualifications = cast(list[Any], raw_qualifications)
        if len(qualifications) != 2:
            raise ValidationError("deterministic_parity_qualification_invalid")
        for role, raw_target in zip(("inference", "verification"), qualifications, strict=True):
            if not isinstance(raw_target, dict):
                raise ValidationError("deterministic_parity_qualification_invalid")
            target = cast(dict[str, Any], raw_target)
            if target.get("role") != role:
                raise ValidationError("deterministic_parity_qualification_invalid")
            run_id, allocation_id = _run_identity(
                client,
                {
                    "run_id": target.get("run_id"),
                    "allocation_id": target.get("allocation_id"),
                    "terminal_status": target.get("terminal_status"),
                },
                seen_runs,
            )
            if allocation_id in seen_allocations or run_id not in {
                value.run_id for value in record.qualifications
            }:
                raise ValidationError("deterministic_parity_qualification_mismatch")
            seen_allocations.add(allocation_id)
        for role, execution in (
            ("inference", record.inference),
            ("verification", record.verification),
        ):
            run_id, allocation_id = _run_identity(client, item[role], seen_runs)
            if (
                execution.run_id != run_id
                or execution.allocation_id != allocation_id
                or allocation_id in seen_allocations
            ):
                raise ValidationError("deterministic_parity_execution_mismatch")
            seen_allocations.add(allocation_id)
    return expected_digest, seen_runs, seen_allocations


def _model_harness(config: dict[str, Any]) -> HarnessSpec:
    return HarnessSpec(
        "claude-code",
        "2.1.205",
        config={
            "mount_image": config["claude_rootfs_image"],
            "model": config["model"],
            "default_opus_model": config["default_opus_model"],
            "default_sonnet_model": config["default_sonnet_model"],
            "default_haiku_model": config["default_haiku_model"],
            "subagent_model": config["subagent_model"],
            "effort_level": config["effort_level"],
            "auto_compact_window": config["auto_compact_window"],
            "max_turns": config["max_turns"],
            "working_directory": "/testbed",
            "disallowed_tools": ["WebFetch", "WebSearch"],
        },
    )


def _assert_safe_plan(episode: Any, selection: AdapterSelection, credential: str) -> None:
    plan = selection.inference.plan(episode, selection.candidate.capture_plan(episode))
    if (
        episode.inference_network != StageNetworkPolicy.DENY_ALL
        or episode.verification_network != StageNetworkPolicy.DENY_ALL
        or plan.network_policy != StageNetworkPolicy.DENY_ALL
        or plan.env.get("ANTHROPIC_AUTH_TOKEN") != "axrun-local-tunnel"
        or plan.env.get("ANTHROPIC_BASE_URL") != "http://127.0.0.1:8765"
        or any(
            not mount.readonly or mount.target != "/__claude_code" for mount in plan.image_mounts
        )
        or len(plan.image_mounts) != 1
        or plan.image_mounts[0].image != episode.harness.config["mount_image"]
        or "--disallowedTools WebFetch WebSearch" not in plan.argv[-1]
        or plan.secret_env
    ):
        raise ValidationError("claude_stage_plan_security_mismatch")
    unsafe = (canonical_json(episode.as_dict()), repr(plan).encode())
    if any(credential.encode() in item or _CREDENTIAL_ENV.encode() in item for item in unsafe):
        raise ValidationError("caller_credential_in_durable_or_run_spec")
    if any(credential in value for value in plan.env.values()):
        raise ValidationError("caller_credential_in_sandbox_env")


def _sealed_outputs(client: AxernClient, run_id: str, root: Path) -> dict[str, dict[str, Any]]:
    manifest = client.get_sealed_output_manifest(run_id)
    if len({item.path for item in manifest}) != len(manifest) or len(
        {item.output_id for item in manifest}
    ) != len(manifest):
        raise ValidationError("claude_sealed_output_manifest_ambiguous")
    by_path = {item.path: item for item in manifest}
    destination = root / "sealed"
    destination.mkdir(mode=0o700)
    summary: dict[str, dict[str, Any]] = {}
    for name, remote in _SEALED:
        item = by_path.get(remote)
        if item is None or item.status != "available":
            raise ValidationError("claude_sealed_output_missing")
        target = destination / name
        with target.open("xb") as stream:
            verified = client.download_sealed_output(run_id, item.output_id, stream)
        data = parity._bounded_file(target, max_bytes=64 << 20)
        digest = hashlib.sha256(data).hexdigest()
        if (
            len(data) != int(item.size_bytes)
            or len(data) != int(verified.size_bytes)
            or verified.output_id != item.output_id
            or verified.path != item.path
            or item.sha256 != verified.sha256
            or digest != item.sha256
            or digest != verified.sha256
        ):
            raise ValidationError("claude_sealed_output_integrity_mismatch")
        summary[name] = {"bytes": len(data), "sha256": digest}
    return summary


def _counts(details: dict[str, Any]) -> dict[str, int]:
    raw_statuses: object = details.get("tests_status")
    if not isinstance(raw_statuses, dict):
        return {"expected": 0, "passed": 0, "failed": 0, "observed": 0}
    statuses = cast(dict[str, Any], raw_statuses)
    passed = failed = 0
    for category in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        raw_section: object = statuses.get(category)
        if not isinstance(raw_section, dict):
            raise ValidationError("claude_verification_test_section_invalid")
        section = cast(dict[str, Any], raw_section)
        success, failure = section.get("success"), section.get("failure")
        if not isinstance(success, list) or not isinstance(failure, list):
            raise ValidationError("claude_verification_test_section_invalid")
        passed += len(cast(list[Any], success))
        failed += len(cast(list[Any], failure))
    raw_status_map: object = details.get("status_map")
    if not isinstance(raw_status_map, dict):
        raise ValidationError("claude_verification_status_map_invalid")
    status_map = cast(dict[str, Any], raw_status_map)
    return {"expected": 60, "passed": passed, "failed": failed, "observed": len(status_map)}


def _credential_scan(root: Path, credential: str) -> int:
    marker = credential.encode()
    found = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValidationError("private_evidence_symlink_rejected")
        if not path.is_file():
            continue
        overlap = b""
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                data = overlap + chunk
                found += data.count(marker)
                overlap = data[-(len(marker) - 1) :] if len(marker) > 1 else b""
    return found


def _private_root() -> Path:
    root = _EVIDENCE_ROOT / f"claude-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    return root.resolve()


def _cleanup_environments(
    client: AxernClient,
    ids: tuple[str, str],
    *,
    state: EpisodeStore | None = None,
    episode_id: str = "",
) -> str:
    if state is not None and episode_id:
        record = state.load(episode_id)
        if record is not None:
            for execution in (record.inference, record.verification):
                if execution is not None:
                    run = client.get_run(execution.run_id)
                    if parity._status_name(run) not in {
                        "RUN_STATUS_SUCCEEDED",
                        "RUN_STATUS_FAILED",
                        "RUN_STATUS_CANCELLED",
                    }:
                        raise ValidationError("active_run_retained_for_recovery")
    for environment_id in ids:
        client.delete_environment(environment_id)
        try:
            client.get_environment(environment_id)
        except SandboxNotFoundError:
            continue
        raise ValidationError("model_environment_cleanup_incomplete")
    return "deleted_and_absent"


def _execute(
    config: dict[str, Any], root: Path, receipt: dict[str, Any], client: AxernClient
) -> None:
    row = parity._official_row(config["row"])
    image_import = parity._image_import_receipt(config["image_import_receipt"])
    task_image = image_import["immutable_ref"]
    parity_digest, old_runs, old_allocations = _parity_gate(
        config["parity_receipt"],
        config["parity_receipt_sha256"],
        client=client,
        task_image=task_image,
        model_environment_ids=(
            config["inference_environment_id"],
            config["verification_environment_id"],
        ),
    )
    for key in ("inference_environment_id", "verification_environment_id"):
        parity._check_environment(client, config[key], task_image)
    receipt["environment_cleanup"] = "pending"
    safety_digest = _image_safety_gate(
        config["image_safety_receipt"],
        config["image_safety_receipt_sha256"],
        expected_image_id=config["image_safety_image_id"],
        row=row,
        task_image=task_image,
        image_import=image_import,
    )
    receipt["image_safety_receipt_sha256"] = safety_digest
    receipt["image_safety_status"] = "passed"
    credential = os.environ.get(_CREDENTIAL_ENV, "")
    if not credential:
        raise ValidationError("caller_model_credential_missing")
    try:
        receipt["task_image_source"] = parity._SOURCE_IMAGE
        receipt["task_image_runtime"] = task_image
        receipt["claude_rootfs_image"] = config["claude_rootfs_image"]
        receipt["parity_receipt_sha256"] = parity_digest
        parity._persist(root, receipt)
        backend = AxernBackend(client)
        store = EpisodeStore(root / "state")
        episode_id = f"flask-5014-claude-{uuid.uuid4().hex}"
        episode = SweBenchFlaskOfficialResolver().resolve(
            row,
            asset_dir=root / "resolved-assets",
            episode_id=episode_id,
            inference_environment_id=config["inference_environment_id"],
            verification_environment_id=config["verification_environment_id"],
            task_image=task_image,
            image_import_receipt=image_import,
            wheelhouse_dir=config["wheelhouse"],
            harness=_model_harness(config),
        )
        selected = _selection()
        _assert_safe_plan(episode, selected, credential)
        receipt["episode_id"] = episode_id
        receipt["seed_digest"] = episode.seed_digest
        receipt["model_config"] = {
            key: config[key]
            for key in (
                "model_upstream_url",
                "model",
                "default_opus_model",
                "default_sonnet_model",
                "default_haiku_model",
                "subagent_model",
                "effort_level",
                "auto_compact_window",
                "max_turns",
            )
        }
        parity._persist(root, receipt)
        qualification = qualify_episode(
            episode, client=client, backend=backend, store=store, selection=selected
        )
        qualifying: list[dict[str, str]] = []
        for target in qualification.targets:
            if target.run_id in old_runs or target.allocation_id in old_allocations:
                raise ValidationError("claude_qualification_not_fresh")
            parity._terminal_execution(client, target.run_id, target.allocation_id)
            checks = target.checks
            if target.role == "inference" and (
                checks.get("claude", {}).get("mount_readonly") is not True
                or checks.get("claude", {}).get("node_version") != "v22.23.2"
                or "2.1.205 (Claude Code)" not in checks.get("claude", {}).get("version", "")
            ):
                raise ValidationError("claude_rootfs_qualification_failed")
            qualifying.append(
                {
                    "role": target.role,
                    "run_id": target.run_id,
                    "allocation_id": target.allocation_id,
                    "output_sha256": target.output_sha256,
                }
            )
        receipt["qualification"] = qualifying
        parity._persist(root, receipt)
        protocol = resolve_model_protocol(selected.runtime)
        if protocol is None:
            raise ValidationError("claude_model_protocol_missing")
        proxy = ModelProxy(
            upstream_url=config["model_upstream_url"],
            credential=credential,
            protocol=protocol,
            connect_timeout_seconds=10,
            read_timeout_seconds=300,
        )
        tunnel_evidence = _TunnelCleanupEvidence(client)
        tunnel = ModelTunnelLifecycle(
            client=tunnel_evidence,
            proxy=proxy,
            model=config["model"],
            connector_factory=tunnel_evidence.connector_factory,
        )
        observer = StageProgressObserver(episode_id=episode_id, store=store, proxy=proxy)
        lifecycle = CompositePreStartLifecycle(tunnel, observer)
        try:
            result = EpisodeRunner(backend=backend, store=store).run(
                episode,
                inference=selected.inference,
                candidate=selected.candidate,
                verifier=selected.verifier,
                trajectory=selected.trajectory,
                inference_lifecycle=lifecycle,
            )
        finally:
            lifecycle.close()
            tunnel.close()
            proxy.stop()
            receipt["model_proxy_cleanup"] = "stopped"
            receipt["tunnel_cleanup"] = (
                "revoked"
                if tunnel_evidence.revoked
                else "not_started"
                if not tunnel_evidence.session_id
                else "failed_or_ambiguous"
            )
            receipt["tunnel_setup"] = {
                "session_created": bool(tunnel_evidence.session_id),
                "create_error_type": tunnel_evidence.create_error_type,
                "create_grpc_status": tunnel_evidence.create_grpc_status,
            }
            last_summary = proxy.last_summary
            if last_summary is not None:
                receipt["model_last_summary"] = last_summary.as_safe_dict()
        if receipt["tunnel_cleanup"] != "revoked":
            raise ValidationError("claude_tunnel_cleanup_unproven")
        summaries = proxy.summaries
        if (
            not summaries
            or summaries[0].method != "POST"
            or summaries[0].path != "/v1/messages"
            or summaries[0].status != 200
            or summaries[0].reason_code != "upstream_response"
        ):
            raise ValidationError("claude_model_preflight_not_proven")
        try:
            _target = proxy.local_target
        except Exception:
            receipt["model_proxy_cleanup"] = "stopped"
        else:
            raise ValidationError("claude_model_proxy_still_running")
        record = store.load(episode_id)
        if (
            record is None
            or record.phase != EpisodePhase.COMPLETED
            or record.inference is None
            or record.verification is None
            or not record.candidate_manifest
            or not record.trajectory_manifest
            or not record.verification_result
        ):
            raise ValidationError("claude_episode_not_complete")
        inference = record.inference
        verification = record.verification
        if (
            inference.run_id == verification.run_id
            or inference.allocation_id == verification.allocation_id
            or any(value.run_id in old_runs for value in (inference, verification))
            or any(value.allocation_id in old_allocations for value in (inference, verification))
            or inference.environment_id != config["inference_environment_id"]
            or verification.environment_id != config["verification_environment_id"]
        ):
            raise ValidationError("claude_verification_not_fresh")
        parity._terminal_execution(client, inference.run_id, inference.allocation_id)
        parity._terminal_execution(client, verification.run_id, verification.allocation_id)
        sealed = _sealed_outputs(client, inference.run_id, root)
        candidate = load_candidate(Path(record.candidate_manifest))
        trajectory = load_trajectory_bundle(Path(record.trajectory_manifest))
        if (
            candidate.digest != record.candidate_digest
            or trajectory.digest != record.trajectory_digest
            or result.candidate_digest != candidate.digest
            or len(candidate.files) != 1
            or candidate.files[0].role != "patch"
            or candidate.files[0].sha256 != sealed["candidate.patch"]["sha256"]
            or candidate.files[0].size_bytes != sealed["candidate.patch"]["bytes"]
            or trajectory.trajectory.sha256 != sealed["trajectory.jsonl"]["sha256"]
            or trajectory.usage.sha256 != sealed["usage.json"]["sha256"]
        ):
            raise ValidationError("claude_bundle_integrity_mismatch")
        loaded = store.load_result(record.verification_result, record.verification_result_digest)
        if loaded != result:
            raise ValidationError("claude_result_digest_mismatch")
        report = verify_record(store, episode_id, selection=selected)
        if (
            report["integrity_verified"] is not True
            or report["candidate_digest"] != candidate.digest
            or report["trajectory_digest"] != trajectory.digest
            or report["verification_result_digest"] != record.verification_result_digest
            or report["verdict"] != result.verdict
            or report["score"] != result.score
        ):
            raise ValidationError("claude_record_integrity_mismatch")
        verification_dir = root / "state" / "artifacts" / episode_id / "verification"
        verification_sealed = {
            "verification.json": parity._sealed_summary(
                client,
                verification.run_id,
                "/outputs/verification.json",
                verification_dir / "00-verification.json",
                result.output_digest,
            ),
            "verifier.log": parity._sealed_summary(
                client,
                verification.run_id,
                "/outputs/verifier.log",
                verification_dir / "01-verifier.log",
                str(result.details["test_output_sha256"]),
            ),
        }
        receipt.update(
            inference={"run_id": inference.run_id, "allocation_id": inference.allocation_id},
            verification={
                "run_id": verification.run_id,
                "allocation_id": verification.allocation_id,
            },
            sealed_outputs=sealed,
            verification_sealed_outputs=verification_sealed,
            candidate_digest=candidate.digest,
            trajectory_digest=trajectory.digest,
            trajectory_event_count=trajectory.event_count,
            verification_result_digest=record.verification_result_digest,
            record_integrity_verified=True,
            verdict=result.verdict,
            score=result.score,
            diagnostic_code=result.diagnostic_code,
            test_summary=_counts(result.details),
            model_preflight={"status": 200, "reason_code": "upstream_response"},
            model_request_count=len(summaries),
        )
        parity._persist(root, receipt)
    finally:
        parity._persist(root, receipt)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2 or arguments[0] != "--config":
        print("Flask Claude acceptance failed closed: closed_config_required", flush=True)
        return 2
    os.umask(0o077)
    root = _private_root()
    receipt: dict[str, Any] = {
        "schema_version": "axrun.swebench-flask-claude-axern@1",
        "status": "started",
        "platform": "linux/amd64",
        "axern_sdk": parity._SDK_VERSION,
        "credential_env": _CREDENTIAL_ENV,
        "environment_cleanup": "not_started",
    }
    parity._persist(root, receipt)
    client: AxernClient | None = None
    owned_environments: tuple[str, str] | None = None
    exit_code = 1
    credential = ""
    try:
        config = _config(Path(arguments[1]))
        owned_environments = (
            config["inference_environment_id"],
            config["verification_environment_id"],
        )
        parity._check_host_and_sdk()
        if platform.machine() != "x86_64":
            raise ValidationError("native_linux_amd64_required")
        client = parity._client(config["endpoint"], config["context_config"])
        _execute(config, root, receipt, client)
        receipt["status"] = "complete"
        exit_code = 0
    except Exception as exc:
        receipt["status"] = "failed_closed"
        receipt["failure_type"] = type(exc).__name__
        receipt["failure_reason"] = (
            str(exc) if isinstance(exc, (ValidationError, parity.ValidationError)) else "unexpected"
        )
        episode_id = receipt.get("episode_id")
        if isinstance(episode_id, str):
            try:
                record = EpisodeStore(root / "state").load(episode_id)
                if record is not None:
                    receipt["diagnostic_code"] = record.diagnostic_code
                    for role in ("inference", "verification"):
                        execution = getattr(record, role)
                        if execution is not None:
                            receipt[role] = {
                                "run_id": execution.run_id,
                                "allocation_id": execution.allocation_id or "",
                            }
            except Exception:
                pass
        print(f"Flask Claude acceptance failed closed: {type(exc).__name__}", flush=True)
    finally:
        if client is not None:
            if owned_environments is not None and receipt["environment_cleanup"] == "pending":
                try:
                    receipt["environment_cleanup"] = _cleanup_environments(
                        client,
                        owned_environments,
                        state=EpisodeStore(root / "state"),
                        episode_id=str(receipt.get("episode_id", "")),
                    )
                except Exception:
                    receipt["environment_cleanup"] = "failed_or_ambiguous"
                    receipt["status"] = "failed_closed"
                    exit_code = 1
            try:
                client.close()
            except Exception:
                receipt["client_cleanup"] = "failed"
                receipt["status"] = "failed_closed"
                exit_code = 1
            else:
                receipt["client_cleanup"] = "closed"
        credential = os.environ.get(_CREDENTIAL_ENV, "")
        if credential:
            try:
                receipt["credential_scan_matches"] = _credential_scan(root, credential)
                if receipt["credential_scan_matches"]:
                    receipt["status"] = "failed_closed"
                    exit_code = 1
            except Exception:
                receipt["credential_scan_matches"] = "incomplete"
                receipt["status"] = "failed_closed"
                exit_code = 1
        parity._persist(root, receipt)
        print(f"private_evidence={root}", flush=True)
        safe = {key: value for key, value in receipt.items() if key != "model_config"}
        print(json.dumps(safe, sort_keys=True, separators=(",", ":")), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
