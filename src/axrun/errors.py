"""Stable Axrun errors."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast


class AxrunError(RuntimeError):
    """Base error for runner-owned failures."""


class ContractError(AxrunError, ValueError):
    """A caller-owned episode or adapter contract is invalid."""


class InfrastructureError(AxrunError):
    """The execution platform could not produce a trustworthy outcome."""


class DiagnosedInfrastructureError(InfrastructureError):
    """Infrastructure failure with an allowlisted, caller-safe diagnosis."""

    def __init__(self, diagnostic_code: str, details: Mapping[str, Any] | None = None) -> None:
        self.diagnostic_code = diagnostic_code
        self.details = safe_diagnostic_details(details or {})
        rendered = json.dumps(self.details, sort_keys=True, separators=(",", ":"))
        super().__init__(f"{diagnostic_code}: {rendered}")


def safe_diagnostic_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only bounded model metadata that is safe for durable diagnosis."""
    result: dict[str, Any] = {}
    for key in ("method", "protocol", "path", "model", "reason_code"):
        value = details.get(key)
        if isinstance(value, str):
            result[key] = value
    for key in ("status", "request_bytes", "response_bytes", "latency_ms"):
        value = details.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    usage = details.get("usage")
    if isinstance(usage, Mapping):
        safe_usage = {
            key: value
            for key, value in cast(Mapping[object, object], usage).items()
            if isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        }
        result["usage"] = safe_usage
    return result


class RecoveryRequiredError(AxrunError):
    """A persisted stage must be inspected instead of silently rerun."""


class SdkCapabilityError(AxrunError):
    """The installed public Axern SDK lacks a required stable capability."""
