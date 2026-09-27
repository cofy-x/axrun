"""The released-SDK smoke records both trials and rejects policy mismatches."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from axrun.models import Artifact, ExecutionRef, StageNetworkPolicy, StageResult

PATH = Path(__file__).parents[1] / "tools/validation/network_policy_sdk_smoke.py"
SPEC = importlib.util.spec_from_file_location("network_policy_sdk_smoke", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("permitted", [False, True])
def test_probe_accepts_only_expected_policy_result(tmp_path: Path, monkeypatch, permitted: bool):
    class Client:
        def get_run(self, run_id):
            assert run_id == "run"
            return object()

    class Backend:
        def __init__(self, _client: object) -> None:
            pass

        def execute(self, plan, *, artifact_dir, on_bound):
            assert plan.network_policy is StageNetworkPolicy.DENY_ALL
            on_bound(ExecutionRef("env", "run"))
            on_bound(ExecutionRef("env", "run", "alloc"))
            artifact_dir.mkdir()
            output = artifact_dir / "network.json"
            data = json.dumps(
                {
                    "egress_http_success": permitted,
                    "https_status": 200 if permitted else None,
                    "direct_ip_tcp_connected": permitted,
                }
            ).encode()
            output.write_bytes(data)
            artifact = Artifact(
                "/outputs/network.json",
                str(output),
                len(data),
                hashlib.sha256(data).hexdigest(),
                "application/json",
            )
            return StageResult(ExecutionRef("env", "run", "alloc"), 0, "", (artifact,))

    monkeypatch.setattr(MODULE, "AxernBackend", Backend)
    monkeypatch.setattr(MODULE, "_status_name", lambda _run: "RUN_STATUS_SUCCEEDED")
    receipt = {"status": "started", "results": []}
    result = MODULE._probe(Client(), "env", tmp_path, StageNetworkPolicy.DENY_ALL, receipt)
    assert result["bound_before_release"] is True
    assert result["run_id"] == "run" and result["allocation_id"] == "alloc"
    assert result["terminal_status"] == "RUN_STATUS_SUCCEEDED"
    assert result["egress_http_success"] is permitted
    assert result["direct_ip_tcp_connected"] is permitted
    assert json.loads((tmp_path / "receipt.json").read_text())["results"] == [result]


def test_probe_persists_run_identity_before_transport_failure(tmp_path: Path, monkeypatch):
    class Backend:
        def __init__(self, _client: object) -> None:
            pass

        def execute(self, _plan, *, artifact_dir, on_bound):
            on_bound(ExecutionRef("env", "run-interrupted"))
            assert (
                json.loads((tmp_path / "receipt.json").read_text())["results"][0]["run_id"]
                == "run-interrupted"
            )
            on_bound(ExecutionRef("env", "run-interrupted", "alloc-interrupted"))
            raise ConnectionError("transport lost")

    monkeypatch.setattr(MODULE, "AxernBackend", Backend)
    receipt = {"status": "started", "results": []}
    with pytest.raises(ConnectionError, match="transport lost"):
        MODULE._probe(object(), "env", tmp_path, StageNetworkPolicy.DENY_ALL, receipt)
    trial = json.loads((tmp_path / "receipt.json").read_text())["results"][0]
    assert trial == {
        "policy": "deny_all",
        "environment_id": "env",
        "status": "allocation_ready",
        "run_id": "run-interrupted",
        "allocation_id": "alloc-interrupted",
    }


def test_policy_result_pair_requires_isolation_and_public_egress() -> None:
    denied = {
        "policy": "deny_all",
        "run_id": "run-1",
        "allocation_id": "alloc-1",
        "egress_http_success": False,
        "direct_ip_tcp_connected": False,
    }
    public = {
        "policy": "unrestricted",
        "run_id": "run-2",
        "allocation_id": "alloc-2",
        "egress_http_success": True,
        "direct_ip_tcp_connected": True,
    }
    MODULE._assert_policy_results([denied, public])
    with pytest.raises(RuntimeError, match="deny_all"):
        MODULE._assert_policy_results([{**denied, "egress_http_success": True}, public])
    with pytest.raises(RuntimeError, match="unrestricted"):
        MODULE._assert_policy_results([denied, {**public, "egress_http_success": False}])
    with pytest.raises(RuntimeError, match="direct-IP"):
        MODULE._assert_policy_results([{**denied, "direct_ip_tcp_connected": True}, public])
    with pytest.raises(RuntimeError, match="direct-IP"):
        MODULE._assert_policy_results([denied, {**public, "direct_ip_tcp_connected": False}])
    with pytest.raises(RuntimeError, match="fresh Runs"):
        MODULE._assert_policy_results([denied, {**public, "run_id": "run-1"}])
