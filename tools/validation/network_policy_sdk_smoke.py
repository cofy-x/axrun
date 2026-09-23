"""Released-SDK truth path for Axrun's closed stage egress mapping.

Run only against an explicitly selected Axern local endpoint on native Linux.
The probe sends no credentials or request bodies and creates two fresh Runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any

from axern_sdk import AxernClient

from axrun.axern_backend import AxernBackend
from axrun.models import ExecutionRef, OutputSpec, StageNetworkPolicy, StagePlan

IMAGE = (
    "index.docker.io/library/python"
    "@sha256:2d62568c3174136030ac1da4e534cfbfe709aec913daeb2a3d49328e27438093"
)
_PROBE = """import json, os, urllib.request
try:
    with urllib.request.urlopen('https://example.com/', timeout=10) as response:
        permitted = response.status == 200
except OSError:
    permitted = False
os.makedirs('/outputs', exist_ok=True)
with open('/outputs/network.json', 'w', encoding='utf-8') as stream:
    json.dump({'egress_http_success': permitted}, stream)
"""


def _probe(
    client: AxernClient, environment_id: str, root: Path, policy: StageNetworkPolicy
) -> dict[str, Any]:
    plan = StagePlan(
        environment_id=environment_id,
        argv=("/usr/local/bin/python", "-c", _PROBE),
        cwd="/",
        outputs=(OutputSpec("/outputs/network.json", media_type="application/json"),),
        network_policy=policy,
        timeout_seconds=120,
        labels={"axrun.validation": "network-policy", "axrun.policy": policy.value},
    )
    bound: list[ExecutionRef] = []
    result = AxernBackend(client).execute(
        plan, artifact_dir=root / policy.value, on_bound=bound.append
    )
    if result.exit_code != 0 or not result.execution.allocation_id:
        raise RuntimeError(f"{policy.value} Run did not complete successfully")
    artifact = result.artifact_for_path("/outputs/network.json")
    data = Path(artifact.path).read_bytes()
    if len(data) != artifact.size_bytes or hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise RuntimeError(f"{policy.value} sealed output integrity mismatch")
    payload = json.loads(data)
    if not isinstance(payload, dict) or type(payload.get("egress_http_success")) is not bool:
        raise RuntimeError(f"{policy.value} network result has an invalid shape")
    if len(bound) != 2 or bound[0].allocation_id:
        raise RuntimeError("Run identity was not persisted before Allocation readiness")
    return {
        "policy": policy.value,
        "environment_id": environment_id,
        "run_id": result.execution.run_id,
        "allocation_id": result.execution.allocation_id,
        "egress_http_success": payload["egress_http_success"],
        "sealed_size": artifact.size_bytes,
        "sealed_sha256": artifact.sha256,
        "bound_before_release": True,
    }


def _assert_policy_results(results: list[dict[str, Any]]) -> None:
    if len(results) != 2 or [item["policy"] for item in results] != [
        StageNetworkPolicy.DENY_ALL.value,
        StageNetworkPolicy.UNRESTRICTED.value,
    ]:
        raise RuntimeError("network policy trials are incomplete")
    if (
        results[0]["run_id"] == results[1]["run_id"]
        or results[0]["allocation_id"] == results[1]["allocation_id"]
    ):
        raise RuntimeError("network policy trials did not use fresh Runs and Allocations")
    if results[0]["egress_http_success"] is not False:
        raise RuntimeError("deny_all HTTPS egress was permitted")
    if results[1]["egress_http_success"] is not True:
        raise RuntimeError("unrestricted HTTPS egress was unavailable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--context-config", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("native linux/amd64 is required")
    if args.endpoint != "127.0.0.1:25000":
        raise RuntimeError("smoke accepts only the Forge-managed loopback Axern endpoint")
    context_config = args.context_config or (
        Path("/data/forge-workspace/.forge/local/hosts") / platform.node() / "axern/config.json"
    )
    config = json.loads(context_config.read_text(encoding="utf-8"))
    if config.get("current_context") != "local":
        raise RuntimeError("Axern local context is not selected")
    context = config["contexts"]["local"]
    if context.get("endpoint") != args.endpoint:
        raise RuntimeError("Axern context endpoint does not match the requested endpoint")
    tls = context["tls"]
    if not all(isinstance(tls.get(key), str) and tls[key] for key in ("ca_cert", "cert", "key")):
        raise RuntimeError("Axern local context has incomplete TLS configuration")
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="axrun-network-policy.", dir="/data/forge-artifacts"))
    client = AxernClient.from_env(
        target=args.endpoint,
        tls_ca_cert=tls["ca_cert"],
        tls_cert=tls["cert"],
        tls_key=tls["key"],
        tls_server_name="gatewayd",
        proxy_mode="direct",
    )
    environment_id = ""
    receipt: dict[str, Any] = {"status": "started", "image": IMAGE, "environment_id": ""}
    try:
        environment = client.create_environment(
            image_ref=IMAGE, labels={"axrun.validation": "network-policy"}
        )
        environment_id = environment.id
        receipt["environment_id"] = environment_id
        results: list[dict[str, Any]] = [
            _probe(client, environment_id, root, StageNetworkPolicy.DENY_ALL),
            _probe(client, environment_id, root, StageNetworkPolicy.UNRESTRICTED),
        ]
        receipt["results"] = results
        _assert_policy_results(results)
        receipt["status"] = "complete"
    except Exception as exc:
        receipt.update({"status": "infrastructure_error", "reason": type(exc).__name__})
        raise
    finally:
        try:
            if environment_id:
                client.delete_environment(environment_id)
                receipt["cleanup"] = "deleted"
            else:
                receipt["cleanup"] = "not_created"
        except Exception:
            receipt.update({"status": "infrastructure_error", "cleanup": "failed"})
            raise
        finally:
            try:
                client.close()
            finally:
                (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"evidence={root}", flush=True)
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
