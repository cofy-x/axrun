"""Audit the released Axern SDK for ProgramBench post-compile branch isolation.

This reproducer imports only public symbols from ``axern_sdk``. It does not inspect Axern source,
generated Proto modules, server reflection, or node-local state.
"""

from __future__ import annotations

import inspect
import json
from importlib.metadata import version
from typing import Any

from axern_sdk import AllocationClient, AxernClient

_REQUIRED_VERSION = "0.9.1"
_STATE_OPERATIONS = frozenset(
    {
        "clone",
        "clone_allocation",
        "commit",
        "commit_image",
        "create_environment_from_allocation",
        "create_environment_from_snapshot",
        "snapshot",
        "snapshot_allocation",
    }
)


def audit_public_sdk() -> dict[str, Any]:
    client_methods = _public_methods(AxernClient)
    allocation_methods = _public_methods(AllocationClient)
    create_environment_parameters = set(
        inspect.signature(AxernClient.create_environment).parameters
    )
    create_run_parameters = set(inspect.signature(AxernClient.create_run).parameters)
    state_operations = sorted(_STATE_OPERATIONS & (client_methods | allocation_methods))
    environment_sources = sorted(
        {"allocation_id", "snapshot_id", "parent_allocation_id"} & create_environment_parameters
    )
    run_sources = sorted(
        {"allocation_id", "snapshot_id", "parent_allocation_id"} & create_run_parameters
    )
    sdk_version = version("axern-sdk")
    supported = bool(state_operations or environment_sources or run_sources)
    return {
        "schema_version": 1,
        "axern_sdk_version": sdk_version,
        "required_axern_sdk_version": _REQUIRED_VERSION,
        "required_semantics": (
            "commit one candidate-specific post-compile Allocation state and create every "
            "test branch in a fresh Allocation rooted in that immutable state"
        ),
        "supported": supported,
        "state_operations": state_operations,
        "create_environment_state_sources": environment_sources,
        "create_run_state_sources": run_sources,
        "public_axern_client_methods": sorted(client_methods),
        "public_allocation_client_methods": sorted(allocation_methods),
        "evidence": (
            "sealed files and archives can move declared path content, but no public operation "
            "turns complete post-compile Allocation state into an immutable Environment"
        ),
        "missing_capability": ("post-compile-allocation-snapshot-v1" if not supported else ""),
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
