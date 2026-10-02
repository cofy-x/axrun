"""Locked Django image scanner using the reviewed Flask signature algorithm.

The benchmark inputs and accepted Git HEAD differ, but the bounded filesystem,
all-object Git, and patch-history scan must have the same fail-closed behavior.
Keep the Flask scanner bytes unchanged so historical Flask receipts remain valid.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from axrun.tasks import flask_image_audit as shared

SCHEMA = "axrun.swebench-django-image-secrecy@1"
IMAGE_HEAD = "7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
# The shared scanner embeds Flask's row base only for its `cat-file` presence
# check. Its image HEAD is read from Git at runtime, not embedded in the script.
_SHARED_ROW_BASE_COMMIT = "7ee9ceb71e868944a46e1ff00b506772a53a4f1d"
REQUEST_PATH = "/run/axrun/django-audit-request.json"
OUTPUT_PATH = "/outputs/django-image-audit.json"
MAX_AUDIT_OUTPUT = shared.MAX_AUDIT_OUTPUT
MAX_REQUEST_BYTES = shared.MAX_REQUEST_BYTES
AUDIT_TIMEOUT_SECONDS = shared.AUDIT_TIMEOUT_SECONDS
# The pinned Django seed contains 339,152 Git objects. Keep the full-object
# scan mandatory while bounding this task's larger, measured history.
MAX_GIT_OBJECTS = 400_000
SecrecyError = shared.SecrecyError


def build_request(checked_row: dict[str, Any]) -> bytes:
    """Derive signatures from a separately locked official Django row."""
    return shared.build_request(checked_row)


def check_audit_result(value: object, target_count: int) -> dict[str, Any]:
    """Validate the shared closed shape against Django's exact base HEAD."""
    if not isinstance(value, dict):
        raise SecrecyError("image_head_invalid")
    checked = cast(dict[str, Any], value)
    if checked.get("image_head") != IMAGE_HEAD:
        raise SecrecyError("image_head_invalid")
    # Only normalize the already-validated benchmark HEAD for the shared shape
    # checker. The returned audit remains the original, exact Django evidence.
    normalized = {**checked, "image_head": shared.IMAGE_HEAD}
    shared.check_audit_result(normalized, target_count)
    return checked


def audit_status(audit: dict[str, Any]) -> tuple[str, str]:
    if audit.get("image_head") != IMAGE_HEAD:
        raise SecrecyError("image_head_invalid")
    return shared.audit_status(audit)


def runtime_scan_script() -> bytes:
    """Emit the same bounded scanner, with only locked Django identities changed."""
    script = shared.runtime_scan_script()
    replacements = (
        (_SHARED_ROW_BASE_COMMIT.encode(), IMAGE_HEAD.encode()),
        (shared.REQUEST_PATH.encode(), REQUEST_PATH.encode()),
        (shared.OUTPUT_PATH.encode(), OUTPUT_PATH.encode()),
        (b"<axrun-flask-image-audit>", b"<axrun-django-image-audit>"),
        (b"MAX_GIT_OBJECTS = 250000", f"MAX_GIT_OBJECTS = {MAX_GIT_OBJECTS}".encode()),
    )
    for previous, current in replacements:
        if previous == current or script.count(previous) != 1:
            raise SecrecyError("django_scanner_contract_invalid")
        script = script.replace(previous, current)
    return script


def scanner_implementation_sha256() -> str:
    """Bind both the shared signature parser and the exact Django Run script."""
    return hashlib.sha256(
        Path(shared.__file__).read_bytes()
        + b"\x00"
        + Path(__file__).read_bytes()
        + b"\x00"
        + runtime_scan_script()
    ).hexdigest()
