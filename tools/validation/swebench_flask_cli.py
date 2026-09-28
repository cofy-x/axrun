"""Private acceptance helper invoking the same installed CLI as normal callers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast


class CliValidationError(RuntimeError):
    """Closed diagnostics: subprocess output stays in private evidence files."""


def run_cli(
    *,
    state_dir: Path,
    context_config: Path,
    command: list[str],
    log_dir: Path,
    label: str,
    model_options: tuple[str, ...] = (),
) -> dict[str, Any]:
    if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,95}", label) is None or not command:
        raise CliValidationError("formal_cli_invocation_invalid")
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stdout_path = log_dir / f"{label}.stdout.json"
    stderr_path = log_dir / f"{label}.stderr.log"
    arguments = [
        sys.executable,
        "-m",
        "axrun.cli",
        "--state-dir",
        str(state_dir.resolve()),
        "--context-file",
        str(context_config.resolve()),
        *model_options,
        *command,
    ]
    try:
        # Never log argv, context contents, environment values, or child output
        # to the terminal. Evidence files are exclusive and caller-private.
        with (
            os.fdopen(
                os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stdout,
            os.fdopen(
                os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stderr,
        ):
            result = subprocess.run(
                arguments, stdout=stdout, stderr=stderr, check=False, timeout=7200.0
            )
    except (OSError, subprocess.TimeoutExpired):
        raise CliValidationError("formal_cli_process_failed") from None
    if result.returncode != 0:
        raise CliValidationError("formal_cli_command_failed")
    if stdout_path.stat().st_size > 4 << 20:
        raise CliValidationError("formal_cli_output_exceeds_limit")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in values:
            if key in parsed:
                raise CliValidationError("formal_cli_output_duplicate_field")
            parsed[key] = value
        return parsed

    def constant(_value: str) -> None:
        raise CliValidationError("formal_cli_output_invalid_constant")

    try:
        value: object = json.loads(
            stdout_path.read_bytes(), object_pairs_hook=pairs, parse_constant=constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CliValidationError("formal_cli_output_invalid_json") from None
    if not isinstance(value, dict):
        raise CliValidationError("formal_cli_output_not_object")
    return cast(dict[str, Any], value)
