#!/usr/bin/env python3
"""Fail-closed image audit for locked Flask test/gold patch signatures.

The private official row is read by the caller. Patches and target paths reach
only a disposable, read-only Docker container over stdin, never argv, env, a
host mount, or the receipt. The container has no network and prints aggregate
booleans/counts only. This proves absence of those locked signatures in the
accessible image filesystem and Git object database, not absence of all
possible undisclosed secrets. This is a stage-zero gate, not a benchmark score.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, cast

from axrun.tasks.flask_image_audit import (
    _AUDIT_FIELDS as _AUDIT_FIELDS,
)
from axrun.tasks.flask_image_audit import (
    _BOOL_FIELDS as _BOOL_FIELDS,
)
from axrun.tasks.flask_image_audit import (
    _CONTAINER_CODE,
    _CONTAINER_ERROR_CODES,
    AUDIT_TIMEOUT_SECONDS,
    MAX_AUDIT_OUTPUT,
    SCHEMA,
    SecrecyError,
    _check_audit,
    _sha256,
    _status,
    build_request,
)
from axrun.tasks.flask_image_audit import (
    IMAGE_HEAD as IMAGE_HEAD,
)
from axrun.tasks.flask_image_audit import (
    _patch_targets_and_hunks as _patch_targets_and_hunks,
)

if __package__:
    from . import swebench_flask_official_oracle as oracle
else:
    import swebench_flask_official_oracle as oracle


def _docker_audit(image_id: str, row: dict[str, Any]) -> dict[str, Any]:
    request = build_request(row)
    target_count = len(json.loads(request)["test_targets"])
    container_name = f"axrun-sweb-flask-secrecy-{uuid.uuid4().hex[:16]}"
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--pull",
        "never",
        "--platform",
        "linux/amd64",
        "--read-only",
        "--user",
        "0:0",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "DAC_READ_SEARCH",
        "--security-opt",
        "no-new-privileges",
        "--cpus",
        "1",
        "--memory",
        "2g",
        "--pids-limit",
        "128",
        "--log-driver",
        "none",
        "--workdir",
        "/testbed",
        "--entrypoint",
        "/opt/miniconda3/bin/python",
        "-i",
        image_id,
        "-c",
        _CONTAINER_CODE,
    ]
    try:
        with tempfile.TemporaryFile() as output:
            completed = subprocess.run(
                command,
                input=request,
                stdout=output,
                stderr=subprocess.DEVNULL,
                env=oracle.safe_subprocess_env(),
                timeout=AUDIT_TIMEOUT_SECONDS,
                check=False,
            )
            output.seek(0)
            payload = output.read(MAX_AUDIT_OUTPUT + 1)
    except subprocess.TimeoutExpired as exc:
        raise SecrecyError("image_audit_timed_out") from exc
    finally:
        _ensure_removed(container_name)
    if len(payload) > MAX_AUDIT_OUTPUT:
        raise SecrecyError("image_audit_output_unbounded")
    if completed.returncode:
        try:
            failed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            failed = None
        if (
            isinstance(failed, dict)
            and set(failed) == {"error"}
            and isinstance(failed["error"], str)
            and failed["error"] in _CONTAINER_ERROR_CODES
        ):
            raise SecrecyError(failed["error"])
        raise SecrecyError("image_audit_failed_closed")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecrecyError("image_audit_output_invalid") from exc
    return _check_audit(value, target_count)


def _ensure_removed(container_name: str) -> None:
    # `--rm` handles normal exit; this exact-name cleanup also covers a Docker
    # client timeout without touching any other task's container.
    if re.fullmatch(r"axrun-sweb-flask-secrecy-[0-9a-f]{16}", container_name) is None:
        raise SecrecyError("image_audit_cleanup_name_invalid")
    try:
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            env=oracle.safe_subprocess_env(),
        )
        remaining = subprocess.run(
            [
                "docker",
                "ps",
                "--all",
                "--filter",
                f"name=^/{container_name}$",
                "--format",
                "{{.Names}}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            env=oracle.safe_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SecrecyError("image_audit_cleanup_unconfirmed") from None
    if remaining.returncode != 0 or remaining.stdout.strip():
        raise SecrecyError("image_audit_cleanup_unconfirmed")


def audit(row_path: Path) -> dict[str, Any]:
    oracle.check_native_linux()
    row = oracle.load_locked_row(row_path)
    image_id = oracle.check_local_image(oracle.IMAGE)
    image_audit = _docker_audit(image_id, row)
    status, reason_code = _status(image_audit)
    return {
        "schema_version": SCHEMA,
        "instance_id": oracle.INSTANCE_ID,
        "row_sha256": oracle.ROW_SHA256,
        "source_image": oracle.IMAGE,
        "image_id": image_id,
        "test_patch_sha256": _sha256(row["test_patch"].encode()),
        "gold_patch_sha256": _sha256(row["patch"].encode()),
        **image_audit,
        "status": status,
        "reason_code": reason_code,
    }


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    if path.is_symlink() or path.exists() or not path.parent.is_dir():
        raise SecrecyError("receipt_path_invalid")
    if path.parent.is_symlink() or not stat.S_ISDIR(path.parent.stat().st_mode):
        raise SecrecyError("receipt_parent_invalid")
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(payload)


def _config_paths(config: Path) -> tuple[Path, Path]:
    if config.is_symlink() or not config.is_file() or config.stat().st_size > 16 << 10:
        raise SecrecyError("config_file_invalid")

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise SecrecyError("config_duplicate_key")
            value[key] = item
        return value

    try:
        raw_data = json.loads(config.read_bytes(), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecrecyError("config_json_invalid") from exc
    if not isinstance(raw_data, dict):
        raise SecrecyError("config_shape_invalid")
    data = cast(dict[str, Any], raw_data)
    if set(data.keys()) != {"row", "receipt"}:
        raise SecrecyError("config_shape_invalid")
    if any(not isinstance(value, str) or not value for value in data.values()):
        raise SecrecyError("config_path_invalid")
    return Path(data["row"]), Path(data["receipt"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--row", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.config is not None:
            if args.row is not None or args.receipt is not None:
                raise SecrecyError("config_and_flags_conflict")
            row_path, receipt_path = _config_paths(args.config)
        elif args.row is not None and args.receipt is not None:
            row_path, receipt_path = args.row, args.receipt
        else:
            raise SecrecyError("input_paths_missing")
        receipt = audit(row_path)
        _write_receipt(receipt_path, receipt)
        summary = {
            "schema_version": SCHEMA,
            "status": receipt["status"],
            "reason_code": receipt["reason_code"],
            "receipt_sha256": _sha256(receipt_path.read_bytes()),
            "source_image": receipt["source_image"],
            "image_id": receipt["image_id"],
            "test_target_count": receipt["test_target_count"],
        }
        print(json.dumps(summary, sort_keys=True))
        return 0 if receipt["status"] == "passed" else 1
    except (SecrecyError, oracle.OracleError, OSError, ValueError) as exc:
        code = str(exc)
        if not code.isidentifier() or not code.islower():
            code = "image_secrecy_error"
        print(f"image_secrecy_failed_closed: {code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
