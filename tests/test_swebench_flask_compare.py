"""Private Flask oracle parity comparator tests, without Docker or hidden test data."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

PATH = Path(__file__).parents[1] / "tools/validation/swebench_flask_compare.py"
SPEC = importlib.util.spec_from_file_location("swebench_flask_compare", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sections(*, resolved: bool = True) -> dict[str, Any]:
    preserved = [f"private::preserved-{index}" for index in range(59)]
    return {
        "FAIL_TO_PASS": {
            "success": ["private::regression"] if resolved else [],
            "failure": [] if resolved else ["private::regression"],
        },
        "PASS_TO_PASS": {"success": preserved, "failure": []},
        "FAIL_TO_FAIL": {"success": [], "failure": []},
        "PASS_TO_FAIL": {"success": [], "failure": []},
    }


def _scored(*, resolved: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    sections = _sections(resolved=resolved)
    statuses: dict[str, str] = {
        "private::regression": "PASSED" if resolved else "FAILED",
        **{name: "PASSED" for name in sections["PASS_TO_PASS"]["success"]},
        "private::extra-test": "XFAIL",
    }
    official: dict[str, Any] = {
        "status_map": statuses,
        "report": {
            MODULE.INSTANCE_ID: {
                "patch_is_None": False,
                "patch_exists": True,
                "patch_successfully_applied": True,
                "resolved": resolved,
                "tests_status": sections,
            }
        },
    }
    axrun = _verification_result(
        classification="scored",
        resolved=resolved,
        score=1.0 if resolved else 0.0,
        statuses=copy.deepcopy(statuses),
        sections=copy.deepcopy(sections),
    )
    return official, axrun


def _verification_result(
    *,
    classification: str,
    resolved: bool,
    score: float | None,
    statuses: dict[str, str] | None,
    sections: dict[str, Any] | None,
) -> dict[str, Any]:
    diagnostic = (
        ""
        if resolved
        else "SWEBENCH_EMPTY_PATCH"
        if classification == "empty_patch_unscored"
        else "SWEBENCH_TESTS_FAILED"
    )
    return {
        "schema_version": 1,
        "candidate_digest": "a" * 64,
        "verifier": MODULE.VERIFIER,
        "verifier_version": MODULE.VERIFIER_VERSION,
        "verdict": "passed" if resolved else "failed",
        "diagnostic_code": diagnostic,
        "verifier_exit_code": 0,
        "output_digest": "b" * 64,
        "started_at": "2026-09-27T00:00:00Z",
        "completed_at": "2026-09-27T00:00:01Z",
        "score": score,
        "details": {
            "schema_version": MODULE.RESULT_SCHEMA,
            "classification": classification,
            "patch_successfully_applied": True if classification == "scored" else None,
            "eval_exit_code": 0 if classification == "scored" else None,
            "test_output_sha256": "c" * 64,
            "status_map": statuses,
            "tests_status": sections,
            "missing_expected": [] if classification == "scored" else None,
        },
    }


def _write(path: Path, value: dict[str, Any]) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


@pytest.mark.parametrize("resolved", [True, False])
def test_scored_exact_per_test_parity_and_file_digests(tmp_path: Path, resolved: bool) -> None:
    official, axrun = _scored(resolved=resolved)
    official_path = _write(tmp_path / "official.json", official)
    axrun_path = _write(tmp_path / "axrun.json", axrun)
    summary = MODULE.compare_scored(official_path, axrun_path)
    assert summary["parity"] is True
    assert summary["expected_tests"] == 60
    assert summary["official_observed_tests"] == 61
    assert summary["axrun_observed_tests"] == 61
    assert (
        summary["official_sha256"] == MODULE.hashlib.sha256(official_path.read_bytes()).hexdigest()
    )
    assert (
        summary["axrun_verification_sha256"]
        == MODULE.hashlib.sha256(axrun_path.read_bytes()).hexdigest()
    )
    assert "private::" not in json.dumps(summary)


def test_all_parser_keys_and_category_array_order_are_compared(tmp_path: Path) -> None:
    official, axrun = _scored()
    axrun["details"]["status_map"]["private::extra-test"] = "PASSED"
    axrun["details"]["tests_status"]["PASS_TO_PASS"]["success"].reverse()
    summary = MODULE.compare_scored(
        _write(tmp_path / "official.json", official), _write(tmp_path / "axrun.json", axrun)
    )
    assert summary["parity"] is False
    assert summary["checks"]["all_test_statuses"] is False
    assert summary["checks"]["test_category_arrays"] is False


def test_missing_expected_does_not_shrink_denominator(tmp_path: Path) -> None:
    official, axrun = _scored()
    axrun["details"]["missing_expected"] = ["private::regression"]
    summary = MODULE.compare_scored(
        _write(tmp_path / "official.json", official), _write(tmp_path / "axrun.json", axrun)
    )
    assert summary["parity"] is False
    assert summary["checks"]["missing_expected"] is False
    axrun["details"]["tests_status"]["PASS_TO_PASS"]["success"].pop()
    with pytest.raises(MODULE.ParityError, match="test_denominator"):
        MODULE.compare_scored(
            _write(tmp_path / "official.json", official), _write(tmp_path / "axrun.json", axrun)
        )


def _empty_report() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "total_instances": 1,
        "submitted_instances": 1,
        "empty_patch_instances": 1,
        "empty_patch_ids": [MODULE.INSTANCE_ID],
        "submitted_ids": [MODULE.INSTANCE_ID],
        "completed_instances": 0,
        "resolved_instances": 0,
        "unresolved_instances": 0,
        "error_instances": 0,
        "unstopped_instances": 0,
        "completed_ids": [],
        "incomplete_ids": [],
        "resolved_ids": [],
        "unresolved_ids": [],
        "error_ids": [],
        "unstopped_containers": [],
        "unremoved_images": [],
    }


def test_official_empty_remains_unscored_without_fabricated_tests(tmp_path: Path) -> None:
    axrun = _verification_result(
        classification="empty_patch_unscored",
        resolved=False,
        score=None,
        statuses=None,
        sections=None,
    )
    official_path = _write(tmp_path / "official.json", _empty_report())
    axrun_path = _write(tmp_path / "axrun.json", axrun)
    summary = MODULE.compare_empty(official_path, axrun_path)
    assert summary["parity"] is True
    assert summary["expected_tests"] is None
    assert summary["official_observed_tests"] is None
    axrun["score"] = 0.0
    axrun["details"]["status_map"] = {"private::fabricated": "FAILED"}
    summary = MODULE.compare_empty(official_path, _write(axrun_path, axrun))
    assert summary["parity"] is False
    assert summary["checks"]["unscored"] is False
    assert summary["checks"]["no_fabricated_statuses"] is False


def test_official_empty_report_rejects_unknown_or_missing_fields(tmp_path: Path) -> None:
    axrun = _verification_result(
        classification="empty_patch_unscored",
        resolved=False,
        score=None,
        statuses=None,
        sections=None,
    )
    axrun_path = _write(tmp_path / "axrun.json", axrun)
    report = _empty_report()
    report["unexpected"] = "private::secret"
    official_path = _write(tmp_path / "official.json", report)
    with pytest.raises(MODULE.ParityError, match="official_empty_report_schema"):
        MODULE.compare_empty(official_path, axrun_path)
    del report["unexpected"]
    del report["unresolved_ids"]
    with pytest.raises(MODULE.ParityError, match="official_empty_report_schema"):
        MODULE.compare_empty(_write(official_path, report), axrun_path)


def test_duplicate_keys_and_unknown_schema_fail_closed(tmp_path: Path) -> None:
    official, axrun = _scored()
    official_path = _write(tmp_path / "official.json", official)
    axrun_path = _write(tmp_path / "axrun.json", axrun)
    official_path.write_text('{"status_map":{},"status_map":{},"report":{}}', encoding="utf-8")
    with pytest.raises(MODULE.ParityError, match="duplicate_json_key"):
        MODULE.compare_scored(official_path, axrun_path)
    _write(official_path, official)
    axrun["details"]["unexpected"] = "private::secret"
    with pytest.raises(MODULE.ParityError, match="verification_details_schema"):
        MODULE.compare_scored(official_path, _write(axrun_path, axrun))


def test_cli_reports_only_safe_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    official, axrun = _scored()
    axrun["details"]["status_map"]["private::extra-test"] = "ERROR"
    official_path = _write(tmp_path / "official.json", official)
    axrun_path = _write(tmp_path / "axrun.json", axrun)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare",
            "--case",
            "scored",
            "--official",
            str(official_path),
            "--axrun-result",
            str(axrun_path),
        ],
    )
    assert MODULE.main() == 1
    captured = capsys.readouterr()
    assert "private::" not in captured.out + captured.err
    assert "status_map" not in captured.out + captured.err
    axrun_path.write_text("{private::secret}", encoding="utf-8")
    assert MODULE.main() == 2
    captured = capsys.readouterr()
    assert "private::" not in captured.out + captured.err
    assert "source_invalid_json" in captured.err
