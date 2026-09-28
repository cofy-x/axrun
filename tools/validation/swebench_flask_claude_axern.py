#!/usr/bin/env python3
"""One private real-Claude acceptance after locked Flask deterministic parity.

This exercises the registered single-instance CLI, not a suite runner. The caller supplies
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
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from axern_sdk import AxernClient, SandboxNotFoundError

from axrun.adapters._candidate import load_candidate
from axrun.catalog import AdapterSelection, resolve_adapters
from axrun.models import EpisodePhase, StageNetworkPolicy, canonical_json
from axrun.progress.store import ProgressStore
from axrun.store import EpisodeStore
from axrun.tasks.flask_admission import load_flask_admission
from axrun.tasks.flask_image_audit import OUTPUT_PATH as _ADMISSION_OUTPUT
from axrun.trajectories.bundle import load_trajectory_bundle

# Reuse the companion private validator's locked inputs and public-SDK checks.
if __package__:
    from . import swebench_flask_axern_parity as parity
    from .swebench_flask_cli import CliValidationError, run_cli
else:
    import swebench_flask_axern_parity as parity
    from swebench_flask_cli import CliValidationError, run_cli


_EVIDENCE_ROOT = Path(__file__).parents[2] / ".axrun/validation/swebench-flask-5014"
_ROOTFS_IMAGE = (
    "index.docker.io/library/axrun-claude-code-rootfs"
    "@sha256:df44581291434e694b4f9f054be19df394653d0e1fc5c1e893ed754cbe3fb13b"
)
_UPSTREAM = "https://api.deepseek.com/anthropic"
_CREDENTIAL_ENV = "DEEPSEEK_API_KEY"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_EPISODE_ID = re.compile(r"^flask-5014-(?:gold|known_bad|empty)-[0-9a-f]{32}$")
_PATH_KEYS = frozenset(
    {
        "context_config",
        "row",
        "image_import_receipt",
        "wheelhouse",
        "parity_receipt",
    }
)
_CONFIG_KEYS = _PATH_KEYS | {
    "endpoint",
    "parity_receipt_sha256",
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
    "admission_receipt",
    "admission_receipt_sha256",
    "execution_path",
    "cli_commands",
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
    "completed_resume_verified",
    "record_integrity_verified",
    "report_sha256",
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


def _admission_gate(
    path: Path, expected_digest: str, *, client: AxernClient, task_image: str
) -> dict[str, Any]:
    # A source-only Docker receipt is not imported-runtime admission. Core owns
    # the closed identity, scanner-version and recomputed full-scan checks.
    checked = load_flask_admission(path, task_image=task_image, expected_sha256=expected_digest)
    execution = checked["execution"]
    parity._terminal_execution(client, execution["run_id"], execution["allocation_id"])
    manifest = client.get_sealed_output_manifest(execution["run_id"])
    matches = [item for item in manifest if item.path == _ADMISSION_OUTPUT]
    if (
        len(matches) != 1
        or matches[0].status != "available"
        or int(matches[0].size_bytes) != checked["sealed_size_bytes"]
        or str(matches[0].sha256) != checked["sealed_sha256"]
    ):
        raise ValidationError("runtime_admission_public_seal_mismatch")
    return checked


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
        receipt["schema_version"] != "axrun.swebench-flask-axern-parity@2"
        or receipt["status"] != "complete"
        or receipt["platform"] != "linux/amd64"
        or receipt["axern_sdk"] != parity._SDK_VERSION
        or receipt["task_image_source"] != parity._SOURCE_IMAGE
        or receipt["task_image_runtime"] != task_image
        or receipt["oracle_receipt_sha256"] != parity._ORACLE_RECEIPT_SHA256
        or receipt["environment_cleanup"] != "caller_owned_retained"
        or receipt["client_cleanup"] != "closed"
        or receipt["admission_receipt"] != "admission.json"
        or not isinstance(receipt["admission_receipt_sha256"], str)
        or _DIGEST.fullmatch(receipt["admission_receipt_sha256"]) is None
        or receipt["execution_path"] != "formal_cli"
        or receipt["cli_commands"]
        != [
            "admit-swebench-flask-image",
            "resolve-swebench-flask-official",
            "qualify",
            "run",
            "resume",
            "verify-record",
            "report",
        ]
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
    _admission_gate(
        path.parent / "admission.json",
        receipt["admission_receipt_sha256"],
        client=client,
        task_image=task_image,
    )
    state = EpisodeStore(path.parent / "state")
    admitted = load_flask_admission(
        path.parent / "admission.json",
        task_image=task_image,
        expected_sha256=receipt["admission_receipt_sha256"],
    )
    seen_runs: set[str] = {admitted["execution"]["run_id"]}
    seen_allocations: set[str] = {admitted["execution"]["allocation_id"]}
    for expected_case, raw_item in zip(("gold", "known_bad", "empty"), cases, strict=True):
        if not isinstance(raw_item, dict):
            raise ValidationError("deterministic_parity_case_shape_invalid")
        item = cast(dict[str, Any], raw_item)
        if (
            set(item) != _CASE_KEYS
            or item["case"] != expected_case
            or item["completed_resume_verified"] is not True
            or item["record_integrity_verified"] is not True
            or not isinstance(item["report_sha256"], str)
            or _DIGEST.fullmatch(item["report_sha256"]) is None
        ):
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
    parity_receipt = parity._json_object(
        parity._locked_file(config["parity_receipt"], parity_digest)
    )
    admission_path = config["parity_receipt"].parent / parity_receipt["admission_receipt"]
    admission = _admission_gate(
        admission_path,
        parity_receipt["admission_receipt_sha256"],
        client=client,
        task_image=task_image,
    )
    if admission["import_provenance"] != image_import:
        raise ValidationError("model_runtime_import_provenance_mismatch")
    for key in ("inference_environment_id", "verification_environment_id"):
        parity._check_environment(client, config[key], task_image)
    receipt["environment_cleanup"] = "pending"
    credential = os.environ.get(_CREDENTIAL_ENV, "")
    if not credential:
        raise ValidationError("caller_model_credential_missing")
    episode_id = f"flask-5014-claude-{uuid.uuid4().hex}"
    episode_path = root / "episode.json"
    state_dir = root / "state"
    log_dir = root / "cli"
    receipt.update(
        episode_id=episode_id,
        task_image_source=parity._SOURCE_IMAGE,
        task_image_runtime=task_image,
        claude_rootfs_image=config["claude_rootfs_image"],
        parity_receipt_sha256=parity_digest,
        admission_receipt_sha256=parity_receipt["admission_receipt_sha256"],
        execution_path="formal_cli",
        cli_commands=[],
        model_config={
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
        },
    )
    parity._persist(root, receipt)

    def invoke(command: list[str], *, model_options: tuple[str, ...] = ()) -> dict[str, Any]:
        result = run_cli(
            state_dir=state_dir,
            context_config=config["context_config"],
            command=command,
            log_dir=log_dir,
            label=command[0],
            model_options=model_options,
        )
        receipt["cli_commands"].append(command[0])
        parity._persist(root, receipt)
        return result

    invoke(
        [
            "resolve-swebench-flask-official",
            str(config["row"]),
            "--episode-id",
            episode_id,
            "--task-image",
            task_image,
            "--image-import-receipt",
            str(config["image_import_receipt"]),
            "--admission-receipt",
            str(admission_path),
            "--wheelhouse-dir",
            str(config["wheelhouse"]),
            "--assets-dir",
            str(root / "resolved-assets"),
            "--harness",
            "claude-code",
            "--claude-mount-image",
            config["claude_rootfs_image"],
            "--model",
            config["model"],
            "--claude-default-opus-model",
            config["default_opus_model"],
            "--claude-default-sonnet-model",
            config["default_sonnet_model"],
            "--claude-default-haiku-model",
            config["default_haiku_model"],
            "--claude-subagent-model",
            config["subagent_model"],
            "--claude-effort-level",
            config["effort_level"],
            "--claude-auto-compact-window",
            str(config["auto_compact_window"]),
            "--max-turns",
            str(config["max_turns"]),
            "--claude-disallowed-tools",
            "WebFetch",
            "WebSearch",
            "--inference-environment",
            config["inference_environment_id"],
            "--verification-environment",
            config["verification_environment_id"],
            "--output",
            str(episode_path),
        ]
    )
    store = EpisodeStore(state_dir)
    qualification = invoke(["qualify", str(episode_path)])
    episode = store.load_spec(episode_id)
    selected = resolve_adapters(episode)
    _assert_safe_plan(episode, selected, credential)
    receipt["seed_digest"] = episode.seed_digest
    qualifying: list[dict[str, str]] = []
    for target in qualification["targets"]:
        if target["run_id"] in old_runs or target["allocation_id"] in old_allocations:
            raise ValidationError("claude_qualification_not_fresh")
        parity._terminal_execution(client, target["run_id"], target["allocation_id"])
        checks = target["checks"]
        if target["role"] == "inference" and (
            checks.get("claude", {}).get("mount_readonly") is not True
            or checks.get("claude", {}).get("node_version") != "v22.23.2"
            or "2.1.205 (Claude Code)" not in checks.get("claude", {}).get("version", "")
        ):
            raise ValidationError("claude_rootfs_qualification_failed")
        qualifying.append(
            {key: target[key] for key in ("role", "run_id", "allocation_id", "output_sha256")}
        )
    if [target["role"] for target in qualifying] != ["inference", "verification"]:
        raise ValidationError("claude_qualification_incomplete")
    receipt["qualification"] = qualifying
    parity._persist(root, receipt)
    produced = invoke(
        ["run", str(episode_path)],
        model_options=(
            "--model-upstream-url",
            config["model_upstream_url"],
            "--model-credential-env",
            _CREDENTIAL_ENV,
        ),
    )
    # A zero exit requires the production lifecycle's health/preflight and
    # failure-propagating close. No session token/id is copied into this tool.
    receipt.update(
        cleanup_evidence="formal_cli_success_contract",
        model_proxy_cleanup="caller_process_exited",
        tunnel_cleanup="revocation_completed_by_cli_lifecycle",
        model_preflight={
            "status": "passed",
            "expected_http_status": 200,
            "evidence": "formal_cli_success_contract",
        },
    )
    resumed = invoke(["resume", episode_id])
    if produced != resumed:
        raise ValidationError("completed_resume_result_changed")
    report = invoke(["verify-record", episode_id])
    reported = invoke(["report", episode_id])
    if report != reported:
        raise ValidationError("formal_cli_report_mismatch")
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
    inference, verification = record.inference, record.verification
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
    result = store.load_result(record.verification_result, record.verification_result_digest)
    if canonical_json(produced) != canonical_json(asdict(result)):
        raise ValidationError("claude_formal_cli_result_mismatch")
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
    if (
        report["integrity_verified"] is not True
        or report["candidate_digest"] != candidate.digest
        or report["trajectory_digest"] != trajectory.digest
        or report["verification_result_digest"] != record.verification_result_digest
        or report["verdict"] != result.verdict
        or report["score"] != result.score
    ):
        raise ValidationError("claude_record_integrity_mismatch")
    progress = ProgressStore(state_dir).load(episode_id)
    if (
        progress is None
        or progress.run_id != inference.run_id
        or progress.allocation_id != inference.allocation_id
        or progress.request_count < 1
    ):
        raise ValidationError("claude_safe_progress_evidence_missing")
    verification_dir = state_dir / "artifacts" / episode_id / "verification"
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
        verification={"run_id": verification.run_id, "allocation_id": verification.allocation_id},
        sealed_outputs=sealed,
        verification_sealed_outputs=verification_sealed,
        candidate_digest=candidate.digest,
        trajectory_digest=trajectory.digest,
        trajectory_event_count=trajectory.event_count,
        verification_result_digest=record.verification_result_digest,
        record_integrity_verified=True,
        completed_resume_verified=True,
        report_sha256=hashlib.sha256((log_dir / "report.stdout.json").read_bytes()).hexdigest(),
        verdict=result.verdict,
        score=result.score,
        diagnostic_code=result.diagnostic_code,
        test_summary=_counts(result.details),
        model_request_count=progress.request_count,
        model_last_summary={
            "method": progress.last_model_method,
            "protocol": progress.last_model_protocol,
            "path": progress.last_model_path,
            "status": progress.last_model_status,
            "reason_code": progress.last_model_reason_code,
        },
    )
    parity._persist(root, receipt)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2 or arguments[0] != "--config":
        print("Flask Claude acceptance failed closed: closed_config_required", flush=True)
        return 2
    os.umask(0o077)
    root = _private_root()
    receipt: dict[str, Any] = {
        "schema_version": "axrun.swebench-flask-claude-axern@2",
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
            str(exc)
            if isinstance(exc, (ValidationError, parity.ValidationError, CliValidationError))
            else "unexpected"
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
