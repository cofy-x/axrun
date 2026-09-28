#!/usr/bin/env python3
"""Fail-closed, test-level comparison of the locked Flask official oracle and Axrun.

This consumes private evidence files, but prints only counts, digests and comparison
booleans. A scored oracle uses ``official_grade.json``; the empty-patch oracle uses
``official_empty_report.json`` and must remain unscored on both sides.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any, cast

INSTANCE_ID = "pallets__flask-5014"
VERIFIER = "swebench-flask-official"
VERIFIER_VERSION = "1"
RESULT_SCHEMA = "axrun.swebench-flask-official-result@1"
STATUS_CATEGORIES = frozenset({"FAIL_TO_PASS", "PASS_TO_PASS", "FAIL_TO_FAIL", "PASS_TO_FAIL"})
TEST_STATUSES = frozenset({"PASSED", "FAILED", "SKIPPED", "ERROR", "XFAIL"})
RESULT_KEYS = frozenset(
    {
        "schema_version",
        "candidate_digest",
        "verifier",
        "verifier_version",
        "verdict",
        "diagnostic_code",
        "verifier_exit_code",
        "output_digest",
        "started_at",
        "completed_at",
        "score",
        "details",
    }
)
DETAIL_KEYS = frozenset(
    {
        "schema_version",
        "classification",
        "patch_successfully_applied",
        "eval_exit_code",
        "test_output_sha256",
        "status_map",
        "tests_status",
        "missing_expected",
    }
)
EMPTY_REPORT_KEYS = frozenset(
    {
        "total_instances",
        "submitted_instances",
        "completed_instances",
        "resolved_instances",
        "unresolved_instances",
        "empty_patch_instances",
        "error_instances",
        "completed_ids",
        "incomplete_ids",
        "empty_patch_ids",
        "submitted_ids",
        "resolved_ids",
        "unresolved_ids",
        "error_ids",
        "schema_version",
        "unstopped_instances",
        "unstopped_containers",
        "unremoved_images",
    }
)
MAX_INPUT_BYTES = 16 << 20


class ParityError(ValueError):
    """A stable, non-sensitive input-integrity failure."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ParityError("duplicate_json_key")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ParityError("invalid_json_constant")


def _read(path: Path) -> tuple[dict[str, Any], str]:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            raise ParityError("source_not_regular_file")
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ParityError("source_too_large")
        data = path.read_bytes()
    except OSError as exc:
        raise ParityError("source_unavailable") from exc
    if len(data) > MAX_INPUT_BYTES:
        raise ParityError("source_too_large")
    digest = hashlib.sha256(data).hexdigest()
    try:
        raw: Any = json.loads(
            data,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParityError("source_invalid_json") from exc
    if not isinstance(raw, dict):
        raise ParityError("source_not_object")
    return cast(dict[str, Any], raw), digest


def _keys(value: object, expected: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(cast(dict[object, object], value)) != set(expected):
        raise ParityError(code)
    return cast(dict[str, Any], value)


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _verification(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = _keys(raw, RESULT_KEYS, "verification_schema")
    details = _keys(result["details"], DETAIL_KEYS, "verification_details_schema")
    if (
        type(result["schema_version"]) is not int
        or result["schema_version"] != 1
        or result["verifier"] != VERIFIER
        or result["verifier_version"] != VERIFIER_VERSION
        or result["verdict"] not in {"passed", "failed"}
        or type(result["verifier_exit_code"]) is not int
        or result["verifier_exit_code"] != 0
        or not _digest(result["candidate_digest"])
        or not _digest(result["output_digest"])
        or not _digest(details["test_output_sha256"])
        or not isinstance(result["started_at"], str)
        or not result["started_at"]
        or not isinstance(result["completed_at"], str)
        or not result["completed_at"]
        or details["schema_version"] != RESULT_SCHEMA
    ):
        raise ParityError("verification_identity")
    return result, details


def _status_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ParityError("status_map_schema")
    statuses = cast(dict[object, object], value)
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(status, str)
        or status not in TEST_STATUSES
        for key, status in statuses.items()
    ):
        raise ParityError("status_map_schema")
    return cast(dict[str, str], value)


def _test_sections(value: object) -> dict[str, dict[str, list[str]]]:
    sections = _keys(value, STATUS_CATEGORIES, "test_sections_schema")
    for category, count in (
        ("FAIL_TO_PASS", 1),
        ("PASS_TO_PASS", 59),
        ("FAIL_TO_FAIL", 0),
        ("PASS_TO_FAIL", 0),
    ):
        section = _keys(
            sections[category], frozenset({"success", "failure"}), "test_section_schema"
        )
        success, failure = section["success"], section["failure"]
        if not isinstance(success, list) or not isinstance(failure, list):
            raise ParityError("test_denominator")
        success_items = cast(list[object], success)
        failure_items = cast(list[object], failure)
        members = [*success_items, *failure_items]
        if (
            any(not isinstance(item, str) or not item for item in members)
            or len(members) != count
            or len(set(members)) != count
        ):
            raise ParityError("test_denominator")
    return cast(dict[str, dict[str, list[str]]], sections)


def _official_scored(
    raw: dict[str, Any],
) -> tuple[dict[str, str], dict[str, dict[str, list[str]]], bool]:
    grade = _keys(raw, frozenset({"status_map", "report"}), "official_grade_schema")
    statuses = _status_map(grade["status_map"])
    report = _keys(grade["report"], frozenset({INSTANCE_ID}), "official_report_schema")
    instance = _keys(
        report[INSTANCE_ID],
        frozenset(
            {
                "patch_is_None",
                "patch_exists",
                "patch_successfully_applied",
                "resolved",
                "tests_status",
            }
        ),
        "official_instance_schema",
    )
    if (
        instance["patch_is_None"] is not False
        or instance["patch_exists"] is not True
        or instance["patch_successfully_applied"] is not True
        or not isinstance(instance["resolved"], bool)
    ):
        raise ParityError("official_patch_classification")
    sections = _test_sections(instance["tests_status"])
    expected = set(
        sections["FAIL_TO_PASS"]["success"]
        + sections["FAIL_TO_PASS"]["failure"]
        + sections["PASS_TO_PASS"]["success"]
        + sections["PASS_TO_PASS"]["failure"]
    )
    if len(expected) != 60 or any(statuses.get(test) in {None, "SKIPPED"} for test in expected):
        raise ParityError("official_expected_tests_incomplete")
    resolved = not (sections["FAIL_TO_PASS"]["failure"] or sections["PASS_TO_PASS"]["failure"])
    if instance["resolved"] is not resolved:
        raise ParityError("official_resolution_conflict")
    return statuses, sections, resolved


def _summary(
    *,
    case: str,
    official_digest: str,
    result_digest: str,
    checks: dict[str, bool],
    official_observed: int | None,
    axrun_observed: int | None,
) -> dict[str, Any]:
    return {
        "schema_version": "axrun.swebench-flask-parity@1",
        "case": case,
        "parity": all(checks.values()),
        "official_sha256": official_digest,
        "axrun_verification_sha256": result_digest,
        "expected_tests": 60 if case == "scored" else None,
        "official_observed_tests": official_observed,
        "axrun_observed_tests": axrun_observed,
        "checks": checks,
    }


def compare_scored(official_path: Path, result_path: Path) -> dict[str, Any]:
    official, official_digest = _read(official_path)
    verification, result_digest = _read(result_path)
    result, details = _verification(verification)
    official_statuses, official_sections, resolved = _official_scored(official)
    axrun_statuses = _status_map(details["status_map"])
    axrun_sections = _test_sections(details["tests_status"])
    missing = details["missing_expected"]
    if not isinstance(missing, list):
        raise ParityError("missing_expected_schema")
    missing_items = cast(list[object], missing)
    if any(not isinstance(item, str) or not item for item in missing_items) or len(
        set(missing_items)
    ) != len(missing_items):
        raise ParityError("missing_expected_schema")
    score = 1.0 if resolved else 0.0
    if type(result["score"]) not in (float, int):
        raise ParityError("scored_score_schema")
    checks = {
        "classification": details["classification"] == "scored"
        and details["patch_successfully_applied"] is True,
        "all_test_statuses": axrun_statuses == official_statuses,
        "test_category_arrays": axrun_sections == official_sections,
        "missing_expected": missing == [],
        "resolution": result["verdict"] == ("passed" if resolved else "failed"),
        "score": result["score"] == score,
        "diagnostic": result["diagnostic_code"] == ("" if resolved else "SWEBENCH_TESTS_FAILED"),
        "eval_exit_code": type(details["eval_exit_code"]) is int,
    }
    return _summary(
        case="scored",
        official_digest=official_digest,
        result_digest=result_digest,
        checks=checks,
        official_observed=len(official_statuses),
        axrun_observed=len(axrun_statuses),
    )


def compare_empty(official_path: Path, result_path: Path) -> dict[str, Any]:
    raw_report, official_digest = _read(official_path)
    verification, result_digest = _read(result_path)
    result, details = _verification(verification)
    report = _keys(raw_report, EMPTY_REPORT_KEYS, "official_empty_report_schema")
    if (
        type(report.get("schema_version")) is not int
        or report["schema_version"] != 2
        or type(report.get("total_instances")) is not int
        or report["total_instances"] != 1
        or type(report.get("submitted_instances")) is not int
        or report["submitted_instances"] != 1
        or report.get("empty_patch_ids") != [INSTANCE_ID]
        or report.get("submitted_ids") != [INSTANCE_ID]
        or type(report.get("empty_patch_instances")) is not int
        or report["empty_patch_instances"] != 1
        or any(
            type(report.get(field)) is not int or report[field] != 0
            for field in (
                "completed_instances",
                "resolved_instances",
                "unresolved_instances",
                "error_instances",
                "unstopped_instances",
            )
        )
        or any(
            report.get(field) != []
            for field in (
                "completed_ids",
                "incomplete_ids",
                "resolved_ids",
                "unresolved_ids",
                "error_ids",
                "unstopped_containers",
                "unremoved_images",
            )
        )
    ):
        raise ParityError("official_empty_report_schema")
    checks = {
        "classification": details["classification"] == "empty_patch_unscored"
        and details["patch_successfully_applied"] is None,
        "no_fabricated_statuses": details["status_map"] is None
        and details["tests_status"] is None
        and details["missing_expected"] is None,
        "unscored": result["score"] is None,
        "verdict": result["verdict"] == "failed",
        "diagnostic": result["diagnostic_code"] == "SWEBENCH_EMPTY_PATCH",
        "no_test_execution": details["eval_exit_code"] is None,
    }
    return _summary(
        case="empty",
        official_digest=official_digest,
        result_digest=result_digest,
        checks=checks,
        official_observed=None,
        axrun_observed=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("scored", "empty"), required=True)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--axrun-result", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = (
            compare_scored(args.official, args.axrun_result)
            if args.case == "scored"
            else compare_empty(args.official, args.axrun_result)
        )
    except ParityError as exc:
        print(f"Flask parity failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
