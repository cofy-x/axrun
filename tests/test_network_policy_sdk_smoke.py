"""The released-SDK smoke rejects policy/result mismatches before acceptance."""

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
    class Backend:
        def __init__(self, _client: object) -> None:
            pass

        def execute(self, plan, *, artifact_dir, on_bound):
            assert plan.network_policy is StageNetworkPolicy.DENY_ALL
            on_bound(ExecutionRef("env", "run"))
            on_bound(ExecutionRef("env", "run", "alloc"))
            artifact_dir.mkdir()
            output = artifact_dir / "network.json"
            data = json.dumps({"egress_http_success": permitted}).encode()
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
    if permitted:
        with pytest.raises(RuntimeError, match="contradicts"):
            MODULE._probe(object(), "env", tmp_path, StageNetworkPolicy.DENY_ALL)
    else:
        result = MODULE._probe(object(), "env", tmp_path, StageNetworkPolicy.DENY_ALL)
        assert result["bound_before_release"] is True
        assert result["run_id"] == "run" and result["allocation_id"] == "alloc"
