"""Audit the released Axern SDK for ProgramBench post-compile branch isolation.

This reproducer imports only public symbols from ``axern_sdk``. It does not inspect Axern source,
generated Proto modules, server reflection, or node-local state.
"""

from __future__ import annotations

import inspect
import json
from importlib.metadata import version
from typing import Any

from axern_sdk import AxernClient

_REQUIRED_VERSION = "0.11.2"
_CAPABILITY = "post-compile-allocation-snapshot-v1"


def audit_public_sdk() -> dict[str, Any]:
    client_methods = _public_methods(AxernClient)
    create_run_signature = inspect.signature(AxernClient.create_run)
    snapshot_parameter = create_run_signature.parameters.get("rootfs_snapshot")
    wait_method = getattr(AxernClient, "wait_rootfs_snapshot", None)
    wait_signature = inspect.signature(wait_method) if callable(wait_method) else None
    sdk_version = version("axern-sdk")
    supported = (
        snapshot_parameter is not None
        and snapshot_parameter.default is False
        and wait_signature is not None
        and "run_id" in wait_signature.parameters
    )
    return {
        "schema_version": 2,
        "axern_sdk_version": sdk_version,
        "required_axern_sdk_version": _REQUIRED_VERSION,
        "capability": _CAPABILITY,
        "required_semantics": (
            "request rootfs sealing for one successful candidate-specific compile Run, wait for "
            "its immutable derived Environment, and create every test branch as a fresh Run"
        ),
        "supported": supported,
        "create_run_rootfs_snapshot": {
            "present": snapshot_parameter is not None,
            "default": snapshot_parameter.default if snapshot_parameter is not None else None,
        },
        "wait_rootfs_snapshot": {
            "present": wait_signature is not None,
            "parameters": list(wait_signature.parameters) if wait_signature is not None else [],
        },
        "public_axern_client_methods": sorted(client_methods),
        "evidence": (
            "AxernClient.create_run explicitly requests rootfs sealing and "
            "AxernClient.wait_rootfs_snapshot returns the derived Environment result"
            if supported
            else "the released public client lacks the exact rootfs sealing request/wait contract"
        ),
        "missing_capability": ("" if supported else _CAPABILITY),
    }


def _public_methods(value: type[object]) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(value, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def main() -> int:
    report = audit_public_sdk()
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["axern_sdk_version"] != _REQUIRED_VERSION:
        return 3
    return 0 if report["supported"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
