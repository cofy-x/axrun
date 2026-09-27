"""Closed real-Claude Flask acceptance boundary; all tests are model-free."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from axern_sdk import SandboxNotFoundError

from axrun.models import EpisodePhase, ImageMountSpec, OutputSpec, StagePlan

PATH = Path(__file__).parents[1] / "tools/validation/swebench_flask_claude_axern.py"
SPEC = importlib.util.spec_from_file_location("swebench_flask_claude_axern", PATH)
assert SPEC and SPEC.loader
sys.path.insert(0, str(PATH.parent))
claude = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(claude)
sys.path.pop(0)


def _config(tmp_path: Path) -> dict[str, Any]:
    value: dict[str, Any] = {key: str(tmp_path / f"{key}.json") for key in claude._PATH_KEYS}
    value.update(
        endpoint="127.0.0.1:25000",
        parity_receipt_sha256="a" * 64,
        image_safety_receipt_sha256="b" * 64,
        image_safety_image_id=f"sha256:{'c' * 64}",
        inference_environment_id="env-new-inference",
        verification_environment_id="env-new-verification",
        claude_rootfs_image=claude._ROOTFS_IMAGE,
        model_upstream_url="https://api.deepseek.com/anthropic",
        model="deepseek-flash",
        default_opus_model="deepseek-flash[1m]",
        default_sonnet_model="deepseek-flash[1m]",
        default_haiku_model="deepseek-flash",
        subagent_model="deepseek-flash",
        effort_level="max",
        auto_compact_window=786432,
        max_turns=40,
    )
    return value


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_config_is_closed_and_cannot_contain_credential(tmp_path: Path) -> None:
    value = _config(tmp_path)
    path = _write(tmp_path / "config.json", value)
    result = claude._config(path)
    assert result["model"] == "deepseek-flash"
    assert result["row"] == tmp_path / "row.json"
    _write(path, {**value, "model_credential": "secret-value"})
    with pytest.raises(claude.ValidationError, match="invalid_shape"):
        claude._config(path)
    _write(path, {**value, "claude_rootfs_image": "axrun-claude:mutable"})
    with pytest.raises(claude.ValidationError, match="identity_mismatch"):
        claude._config(path)
    _write(path, {**value, "model_upstream_url": "https://api.deepseek.com/anthropic。"})
    with pytest.raises(claude.ValidationError, match="identity_mismatch"):
        claude._config(path)


def _parity_receipt(task_image: str) -> dict[str, Any]:
    return {
        "schema_version": "axrun.swebench-flask-axern-parity@1",
        "status": "complete",
        "platform": "linux/amd64",
        "axern_sdk": "0.11.4",
        "task_image_source": claude.parity._SOURCE_IMAGE,
        "task_image_runtime": task_image,
        "inference_environment_id": "env-old-inference",
        "verification_environment_id": "env-old-verification",
        "oracle_receipt_sha256": claude.parity._ORACLE_RECEIPT_SHA256,
        "environment_cleanup": "caller_owned_retained",
        "client_cleanup": "closed",
        "cases": [],
    }


def _gate(path: Path, value: dict[str, Any], task_image: str) -> tuple[str, set[str], set[str]]:
    _write(path, value)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return claude._parity_gate(
        path,
        digest,
        client=cast(Any, object()),
        task_image=task_image,
        model_environment_ids=("env-new-inference", "env-new-verification"),
    )


def test_parity_gate_rejects_incomplete_cases_and_reused_environment(tmp_path: Path) -> None:
    task_image = f"example.invalid/task@sha256:{'a' * 64}"
    value = _parity_receipt(task_image)
    path = tmp_path / "receipt.json"
    with pytest.raises(claude.ValidationError, match="cases_invalid"):
        _gate(path, value, task_image)
    value["verification_environment_id"] = "env-new-inference"
    with pytest.raises(claude.ValidationError, match="environment_not_fresh"):
        _gate(path, value, task_image)
    value["verification_environment_id"] = "env-old-verification"
    value["status"] = "failed_closed"
    with pytest.raises(claude.ValidationError, match="receipt_invalid"):
        _gate(path, value, task_image)


def test_image_safety_receipt_is_sha_locked_and_recomputed(tmp_path: Path) -> None:
    row = {"test_patch": "private-test-patch", "patch": "private-gold-patch"}
    task_image = f"example.invalid/task@sha256:{'d' * 64}"
    image_id = f"sha256:{'e' * 64}"
    details: dict[str, Any] = {
        key: False if key in claude.image_secrecy._BOOL_FIELDS else 0
        for key in claude.image_secrecy._AUDIT_FIELDS
    }
    details.update(
        image_head=claude.image_secrecy.IMAGE_HEAD,
        image_clean=True,
        row_base_present=True,
        filesystem_scan_complete=True,
        git_all_object_scan_complete=True,
        test_patch_forward_applies=True,
        gold_patch_forward_applies=True,
        test_target_count=1,
        gold_target_count=1,
        added_target_count=1,
    )
    receipt = {
        "schema_version": claude.image_secrecy.SCHEMA,
        "instance_id": "pallets__flask-5014",
        "row_sha256": claude.parity._ROW_SHA256,
        "source_image": claude.parity._SOURCE_IMAGE,
        "image_id": image_id,
        "test_patch_sha256": hashlib.sha256(row["test_patch"].encode()).hexdigest(),
        "gold_patch_sha256": hashlib.sha256(row["patch"].encode()).hexdigest(),
        "status": "passed",
        "reason_code": "no_locked_patch_signatures_reachable",
        **details,
    }
    path = _write(tmp_path / "safety.json", receipt)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    image_import = {"source_ref": claude.parity._SOURCE_IMAGE, "immutable_ref": task_image}

    def gate(value: dict[str, Any], expected_digest: str = digest) -> str:
        _write(path, value)
        return claude._image_safety_gate(
            path,
            expected_digest,
            expected_image_id=image_id,
            row=row,
            task_image=task_image,
            image_import=image_import,
        )

    assert gate(receipt) == digest
    with pytest.raises(claude.ValidationError, match="integrity_invalid"):
        gate(receipt, "0" * 64)
    blocked = {**receipt, "status": "blocked"}
    with pytest.raises(claude.ValidationError, match="not_passed"):
        gate(blocked, hashlib.sha256(_write(path, blocked).read_bytes()).hexdigest())
    wrong_identity = {**receipt, "image_id": f"sha256:{'0' * 64}"}
    with pytest.raises(claude.ValidationError, match="identity_mismatch"):
        gate(wrong_identity, hashlib.sha256(_write(path, wrong_identity).read_bytes()).hexdigest())


def test_parity_gate_rechecks_every_run_and_result_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_image = f"example.invalid/task@sha256:{'b' * 64}"
    value = _parity_receipt(task_image)
    records: dict[str, Any] = {}
    episodes: dict[str, Any] = {}
    queried: list[tuple[str, str]] = []
    for index, case in enumerate(("gold", "known_bad", "empty")):
        episode_id = f"flask-5014-{case}-{'a' * 31}{index}"
        result_path = tmp_path / f"{case}.json"
        result_path.write_text(f'{{"case":"{case}"}}\n', encoding="utf-8")
        result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
        qualification = [
            SimpleNamespace(run_id=f"run-q-{index}-{role}", allocation_id=f"alloc-q-{index}-{role}")
            for role in ("inference", "verification")
        ]
        inference = SimpleNamespace(run_id=f"run-i-{index}", allocation_id=f"alloc-i-{index}")
        verification = SimpleNamespace(run_id=f"run-v-{index}", allocation_id=f"alloc-v-{index}")
        record = SimpleNamespace(
            phase=EpisodePhase.COMPLETED,
            inference=inference,
            verification=verification,
            qualifications=qualification,
            candidate_digest="c" * 64,
            candidate_manifest=str(tmp_path / f"{case}-candidate.json"),
            verification_result=str(result_path),
            verification_result_digest="d" * 64,
        )
        records[episode_id] = record
        episodes[episode_id] = SimpleNamespace(
            seed_digest="e" * 64,
            inference_environment=SimpleNamespace(
                environment_id="env-old-inference", image=task_image
            ),
            verification_environment=SimpleNamespace(
                environment_id="env-old-verification", image=task_image
            ),
        )
        value["cases"].append(
            {
                "case": case,
                "episode_id": episode_id,
                "seed_digest": "e" * 64,
                "qualification": [
                    {
                        "role": role,
                        "run_id": run.run_id,
                        "allocation_id": run.allocation_id,
                        "terminal_status": "RUN_STATUS_SUCCEEDED",
                    }
                    for role, run in zip(("inference", "verification"), qualification, strict=True)
                ],
                "inference": {
                    "run_id": inference.run_id,
                    "allocation_id": inference.allocation_id,
                    "terminal_status": "RUN_STATUS_SUCCEEDED",
                },
                "verification": {
                    "run_id": verification.run_id,
                    "allocation_id": verification.allocation_id,
                    "terminal_status": "RUN_STATUS_SUCCEEDED",
                },
                "candidate_digest": "c" * 64,
                "verification_result_digest": "d" * 64,
                "verdict": "passed" if case == "gold" else "failed",
                "score": 1.0 if case == "gold" else 0.0 if case == "known_bad" else None,
                "diagnostic_code": "",
                "sealed_outputs": {},
                "parity": {
                    "schema_version": "axrun.swebench-flask-parity@1",
                    "case": "empty" if case == "empty" else "scored",
                    "parity": True,
                    "checks": {
                        key: True
                        for key in (
                            claude._EMPTY_CHECKS if case == "empty" else claude._SCORING_CHECKS
                        )
                    },
                    "official_sha256": "f" * 64,
                    "axrun_verification_sha256": result_sha,
                    "expected_tests": None if case == "empty" else 60,
                    "official_observed_tests": None if case == "empty" else 60,
                    "axrun_observed_tests": None if case == "empty" else 60,
                },
            }
        )

    class Store:
        def __init__(self, _root: Path) -> None:
            pass

        def load(self, episode_id: str) -> Any:
            return records[episode_id]

        def load_spec(self, episode_id: str) -> Any:
            return episodes[episode_id]

        def load_result(self, path: str, digest: str) -> Any:
            assert digest == "d" * 64 and Path(path).is_file()
            case = Path(path).stem
            return SimpleNamespace(
                candidate_digest="c" * 64,
                verdict="passed" if case == "gold" else "failed",
                score=1.0 if case == "gold" else 0.0 if case == "known_bad" else None,
                diagnostic_code="",
            )

    monkeypatch.setattr(claude, "EpisodeStore", Store)

    def fake_candidate(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(digest="c" * 64)

    monkeypatch.setattr(claude, "load_candidate", fake_candidate)

    def fake_terminal(_client: Any, run_id: str, allocation_id: str) -> None:
        queried.append((run_id, allocation_id))

    monkeypatch.setattr(
        claude.parity,
        "_terminal_execution",
        fake_terminal,
    )
    path = tmp_path / "receipt.json"
    _gate(path, value, task_image)
    assert len(queried) == 12
    value["cases"][1]["parity"]["checks"]["all_test_statuses"] = False
    with pytest.raises(claude.ValidationError, match="test_level_parity_missing"):
        _gate(path, value, task_image)
    value["cases"][1]["parity"]["checks"]["all_test_statuses"] = True
    value["cases"][2]["parity"]["axrun_verification_sha256"] = "0" * 64
    with pytest.raises(claude.ValidationError, match="result_file_mismatch"):
        _gate(path, value, task_image)


def test_stage_plan_rejects_real_credential_and_unsafe_mount() -> None:
    secret = "secret-sentinel-never-print"
    image = claude._ROOTFS_IMAGE
    plan = StagePlan(
        environment_id="env-new-inference",
        argv=("/bin/sh", "-lc", "claude --disallowedTools WebFetch WebSearch"),
        cwd="/testbed",
        outputs=(OutputSpec("/outputs/candidate.patch"),),
        image_mounts=(ImageMountSpec(image=image, target="/__claude_code"),),
        env={
            "ANTHROPIC_AUTH_TOKEN": "axrun-local-tunnel",
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:8765",
        },
    )
    episode = SimpleNamespace(
        inference_network=claude.StageNetworkPolicy.DENY_ALL,
        verification_network=claude.StageNetworkPolicy.DENY_ALL,
        harness=SimpleNamespace(config={"mount_image": image}),
        as_dict=lambda: {"harness": {"mount_image": image}},
    )

    def fake_plan(_episode: Any, _capture: Any) -> StagePlan:
        return plan

    def fake_capture(_episode: Any) -> object:
        return object()

    selection = SimpleNamespace(
        inference=SimpleNamespace(plan=fake_plan),
        candidate=SimpleNamespace(capture_plan=fake_capture),
    )
    claude._assert_safe_plan(episode, selection, secret)
    plan.env["ANTHROPIC_AUTH_TOKEN"] = secret
    with pytest.raises(claude.ValidationError, match="stage_plan_security_mismatch"):
        claude._assert_safe_plan(episode, selection, secret)


def test_credential_scan_and_environment_cleanup(tmp_path: Path) -> None:
    marker = "secret-sentinel-never-print"
    (tmp_path / "artifact").write_bytes(b"x" * ((1 << 20) - 4) + marker.encode())
    assert claude._credential_scan(tmp_path, marker) == 1

    deleted: list[str] = []

    class Client:
        def delete_environment(self, environment_id: str) -> None:
            deleted.append(environment_id)

        def get_environment(self, _environment_id: str) -> None:
            raise SandboxNotFoundError(operation="GetEnvironment", code="NOT_FOUND", details="")

    assert (
        claude._cleanup_environments(cast(Any, Client()), ("env-i", "env-v"))
        == "deleted_and_absent"
    )
    assert deleted == ["env-i", "env-v"]


def test_sealed_outputs_reject_ambiguous_manifest_and_changed_digest(tmp_path: Path) -> None:
    payload = b"sealed candidate"
    digest = hashlib.sha256(payload).hexdigest()

    def entry(path: str, output_id: str, sha256: str = digest) -> SimpleNamespace:
        return SimpleNamespace(
            path=path,
            output_id=output_id,
            status="available",
            size_bytes=len(payload),
            sha256=sha256,
        )

    class Client:
        def __init__(self, manifest: list[SimpleNamespace], verified: SimpleNamespace) -> None:
            self.manifest = manifest
            self.verified = verified

        def get_sealed_output_manifest(self, _run_id: str) -> list[SimpleNamespace]:
            return self.manifest

        def download_sealed_output(
            self, _run_id: str, _output_id: str, stream: Any
        ) -> SimpleNamespace:
            stream.write(payload)
            return self.verified

    first = entry("/outputs/candidate.patch", "out-1")
    with pytest.raises(claude.ValidationError, match="manifest_ambiguous"):
        claude._sealed_outputs(
            cast(Any, Client([first, entry(first.path, "out-2")], first)), "run-1", tmp_path
        )
    with pytest.raises(claude.ValidationError, match="integrity_mismatch"):
        claude._sealed_outputs(
            cast(Any, Client([entry(first.path, "out-1", "0" * 64)], first)),
            "run-1",
            tmp_path,
        )


def test_tunnel_cleanup_evidence_uses_real_sdk_client_without_storing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "ephemeral-token-never-persist"

    class Client:
        def create_tunnel_session(self, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(session=SimpleNamespace(session_id="tun-1"), client_token=token)

        def revoke_tunnel_session(self, session_id: str, **_kwargs: Any) -> None:
            assert session_id == "tun-1"

    client = Client()
    evidence = claude._TunnelCleanupEvidence(cast(Any, client))
    response = evidence.create_tunnel_session(allocation_id="alloc-1")
    assert response.client_token == token
    assert evidence.session_id == "tun-1" and evidence.revoked is False
    connector_args: dict[str, Any] = {}

    def fake_connector(**kwargs: Any) -> object:
        connector_args.update(kwargs)
        return object()

    monkeypatch.setattr(claude, "TunnelConnector", fake_connector)
    session = response.session
    evidence.connector_factory(
        client=evidence,
        session=session,
        client_token=token,
        local_target="127.0.0.1:9999",
    )
    assert connector_args["client"] is client
    assert connector_args["session"] is session
    evidence.revoke_tunnel_session("tun-1")
    assert evidence.revoked is True
    assert token not in repr(cast(dict[str, Any], vars(evidence)))


def test_tunnel_create_failure_records_only_safe_status() -> None:
    class UnavailableError(RuntimeError):
        def code(self) -> SimpleNamespace:
            return SimpleNamespace(name="UNAVAILABLE", secret="never-record-me")

    class Client:
        def create_tunnel_session(self, **_kwargs: Any) -> None:
            raise UnavailableError("sensitive server message")

    evidence = claude._TunnelCleanupEvidence(cast(Any, Client()))
    with pytest.raises(UnavailableError):
        evidence.create_tunnel_session(allocation_id="alloc-1")
    assert evidence.create_error_type == "UnavailableError"
    assert evidence.create_grpc_status == "UNAVAILABLE"
    assert "sensitive" not in repr(vars(evidence))
    assert "never-record-me" not in repr(vars(evidence))
