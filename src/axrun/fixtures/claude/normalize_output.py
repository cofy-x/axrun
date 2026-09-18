"""Normalize bounded Claude stream-json output and extract non-sensitive usage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

MAX_INPUT_BYTES = 32 << 20
MAX_LINE_BYTES = 2 << 20
SENSITIVE_KEYS = {"authorization", "cookie", "api_key", "apikey", "auth_token", "access_token"}
USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def redact(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else redact(item, secrets)
            for key, item in mapping.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in cast(list[object], value)]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, "[REDACTED]")
        return result
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--usage", type=Path, required=True)
    parser.add_argument("--redact-value", action="append", default=[])
    args = parser.parse_args()
    if args.input.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Claude trajectory exceeds input bound")
    args.trajectory.parent.mkdir(parents=True, exist_ok=True)
    aggregate = {key: 0 for key in USAGE_KEYS}
    observations = 0
    with args.input.open("rb") as source, args.trajectory.open("w", encoding="utf-8") as target:
        for raw_line in source:
            if len(raw_line) > MAX_LINE_BYTES:
                raise ValueError("Claude trajectory line exceeds bound")
            value = json.loads(raw_line)
            cleaned = redact(value, tuple(args.redact_value))
            target.write(json.dumps(cleaned, sort_keys=True, separators=(",", ":")) + "\n")
            usage = cast(dict[str, object], value).get("usage") if isinstance(value, dict) else None
            if isinstance(usage, dict):
                usage_values = cast(dict[str, object], usage)
                observations += 1
                for key in USAGE_KEYS:
                    amount = usage_values.get(key, 0)
                    if isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
                        aggregate[key] = max(aggregate[key], amount)
    args.usage.write_text(
        json.dumps(
            {"schema_version": 1, "observations": observations, **aggregate},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
