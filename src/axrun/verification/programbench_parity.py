#!/usr/bin/env python3
"""Compare one Axrun tty-clock details artifact with ProgramBench 1.2.4 eval.json."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return cast(dict[str, Any], value)


def _official_map(evaluation: dict[str, Any], metadata: dict[str, Any]) -> dict[str, str]:
    branches = cast(dict[str, dict[str, Any]], metadata["branches"])
    active = {name for name, value in branches.items() if not value["ignored"]}
    ignored = {
        f"{branch}/{item['name']}"
        for branch, value in branches.items()
        for item in value["ignored_tests"]
    }
    results: dict[str, str] = {}
    for item in cast(list[dict[str, str]], evaluation["test_results"]):
        key = f"{item['branch']}/{item['name']}"
        if item["branch"] in active and key not in ignored:
            results[key] = item["status"]
    return results


def _axrun_map(details: dict[str, Any]) -> dict[str, str]:
    return {
        f"{item['branch']}/{item['name']}": item["status"]
        for item in cast(list[dict[str, str]], details["tests"])
    }


def _counts(results: dict[str, str]) -> dict[str, int]:
    passed = sum(value == "passed" for value in results.values())
    not_run = sum(value == "not_run" for value in results.values())
    return {"passed": passed, "failed": len(results) - passed - not_run, "not_run": not_run}


def compare(official: Path, details_path: Path, metadata_path: Path) -> dict[str, Any]:
    evaluation = _read(official)
    details = _read(details_path)
    metadata = _read(metadata_path)
    expected = sum(
        len(value["tests"]) - len(value["ignored_tests"])
        for value in cast(dict[str, dict[str, Any]], metadata["branches"]).values()
        if not value["ignored"]
    )
    official_results = _official_map(evaluation, metadata)
    axrun_results = _axrun_map(details)
    official_counts = _counts(official_results)
    score = official_counts["passed"] / len(official_results) if official_results else 0.0
    count_comparisons = {key: details[key] == value for key, value in official_counts.items()}
    comparisons: dict[str, object] = {
        "active_branch_count": details["active_branch_count"]
        == len(cast(list[object], evaluation["test_branches"])),
        "active_test_count": details["active_test_count"] == expected,
        "test_level": axrun_results == official_results,
        "counts": count_comparisons,
        "branch_errors": set(cast(dict[str, object], details["branch_errors"]))
        == set(cast(dict[str, object], evaluation["test_branch_errors"])),
        "executable_sha256": (details["executable_sha256"] or None)
        == evaluation["executable_hash"],
        "score": abs(float(details["score"]) - score) < 1e-15,
        "resolved": details["resolved"] is (score == 1.0),
    }
    passed = all(
        cast(bool, value) for key, value in comparisons.items() if key != "counts"
    ) and all(count_comparisons.values())
    return {
        "schema_version": 1,
        "parity": passed,
        "official_eval_sha256": hashlib.sha256(official.read_bytes()).hexdigest(),
        "axrun_details_sha256": hashlib.sha256(details_path.read_bytes()).hexdigest(),
        "active_test_count": expected,
        "official": {**official_counts, "score": score, "resolved": score == 1.0},
        "axrun": {
            "passed": details["passed"],
            "failed": details["failed"],
            "not_run": details["not_run"],
            "score": details["score"],
            "resolved": details["resolved"],
        },
        "comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-eval", type=Path, required=True)
    parser.add_argument("--axrun-details", type=Path, required=True)
    parser.add_argument("--tests-metadata", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.official_eval, args.axrun_details, args.tests_metadata)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
