"""Synthetic checks for the locked Django wrapper around the shared scanner."""

from __future__ import annotations

import hashlib
import json
from typing import cast

import pytest

from axrun.tasks import django_image_audit as django
from axrun.tasks import flask_image_audit as shared


def _audit() -> dict[str, object]:
    audit_fields = cast(frozenset[str], shared.__dict__["_AUDIT_FIELDS"])
    bool_fields = cast(frozenset[str], shared.__dict__["_BOOL_FIELDS"])
    result: dict[str, object] = {key: 0 for key in audit_fields}
    for key in bool_fields:
        result[key] = False
    result.update(
        image_head=django.IMAGE_HEAD,
        image_clean=True,
        row_base_present=True,
        test_patch_forward_applies=True,
        gold_patch_forward_applies=True,
        filesystem_scan_complete=True,
        git_all_object_scan_complete=True,
        test_target_count=1,
        gold_target_count=1,
        added_target_count=1,
    )
    return result


def test_django_runtime_script_changes_only_locked_scanner_identity() -> None:
    script = django.runtime_scan_script()
    compile(script, "<django-image-audit-test>", "exec")
    assert script.count(django.IMAGE_HEAD.encode()) == 1
    assert b"7ee9ceb71e868944a46e1ff00b506772a53a4f1d" not in script
    assert shared.REQUEST_PATH.encode() not in script
    assert shared.OUTPUT_PATH.encode() not in script
    assert django.REQUEST_PATH.encode() in script
    assert django.OUTPUT_PATH.encode() in script
    assert b"<axrun-django-image-audit>" in script
    assert b"MAX_GIT_OBJECTS = 400000" in script
    assert b"MAX_GIT_OBJECTS = 250000" not in script
    assert len(django.scanner_implementation_sha256()) == 64


def test_django_head_and_complete_shared_audit_are_required() -> None:
    result = _audit()
    checked = django.check_audit_result(result, 1)
    assert checked is result
    assert django.audit_status(checked) == (
        "passed",
        "no_locked_patch_signatures_reachable",
    )
    result["image_head"] = shared.IMAGE_HEAD
    with pytest.raises(django.SecrecyError, match="image_head_invalid"):
        django.check_audit_result(result, 1)
    with pytest.raises(django.SecrecyError, match="image_head_invalid"):
        django.audit_status(result)
    result["image_head"] = django.IMAGE_HEAD
    result["git_all_object_scan_complete"] = False
    assert django.audit_status(django.check_audit_result(result, 1))[0] == "blocked"
    result["git_all_object_scan_complete"] = True
    result["test_all_git_object_match_count"] = 1
    assert django.audit_status(django.check_audit_result(result, 1)) == (
        "blocked",
        "test_added_content_reachable",
    )


def test_signature_request_is_bounded_and_has_no_receipt_projection() -> None:
    patch = (
        "diff --git a/axrun-synthetic.txt b/axrun-synthetic.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/axrun-synthetic.txt\n"
        "@@ -0,0 +1 @@\n"
        "+Synthetic candidate marker with enough meaningful content.\n"
    )
    request = django.build_request({"patch": patch, "test_patch": patch})
    value = json.loads(request)
    assert set(value) == {"gold_patch", "test_patch", "gold_targets", "test_targets"}
    assert len(value["gold_targets"]) == len(value["test_targets"]) == 1
    assert hashlib.sha256(request).hexdigest() != django.scanner_implementation_sha256()
