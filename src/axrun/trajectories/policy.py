"""Safety and size policy for canonical trajectory materialization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "x-api-key",
        "api_key",
        "apikey",
        "auth_token",
        "access_token",
        "credential",
        "tunnel_token",
        "signature",
        "thinking",
    }
)


@dataclass(frozen=True, slots=True)
class TrajectoryLimits:
    native_input_bytes: int = 32 << 20
    native_line_bytes: int = 2 << 20
    canonical_event_bytes: int = 2 << 20
    canonical_total_bytes: int = 64 << 20
    max_events: int = 100_000
    tool_arguments_bytes: int = 1 << 20
    tool_result_bytes: int = 2 << 20


def sanitize(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {
            str(key): sanitize(item, secrets)
            for key, item in mapping.items()
            if str(key).lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [sanitize(item, secrets) for item in cast(list[object], value)]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)


def bounded_json_size(value: Any, maximum: int, label: str) -> None:
    size = len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    if size > maximum:
        raise ValueError(f"{label} exceeds size bound")
