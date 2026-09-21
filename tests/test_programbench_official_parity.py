from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axrun.verification.programbench_parity import compare


def test_parity_comparison_uses_last_duplicate_and_not_run(tmp_path: Path) -> None:
    metadata: dict[str, Any] = {
        "branches": {
            "active": {
                "ignored": False,
                "tests": ["pass", "missing", "ignored"],
                "ignored_tests": [{"name": "ignored"}],
            }
        }
    }
    official: dict[str, Any] = {
        "test_branches": ["active"],
        "test_branch_errors": {},
        "executable_hash": "a" * 64,
        "test_results": [
            {"branch": "active", "name": "pass", "status": "failure"},
            {"branch": "active", "name": "pass", "status": "passed"},
            {"branch": "active", "name": "missing", "status": "not_run"},
            {"branch": "active", "name": "ignored", "status": "failure"},
        ],
    }
    details: dict[str, Any] = {
        "active_branch_count": 1,
        "active_test_count": 2,
        "passed": 1,
        "failed": 0,
        "not_run": 1,
        "branch_errors": {},
        "executable_sha256": "a" * 64,
        "score": 0.5,
        "resolved": False,
        "tests": [
            {"branch": "active", "name": "missing", "status": "not_run"},
            {"branch": "active", "name": "pass", "status": "passed"},
        ],
    }
    paths: list[Path] = []
    for name, value in (("official", official), ("details", details), ("metadata", metadata)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value))
        paths.append(path)
    assert compare(paths[0], paths[1], paths[2])["parity"] is True
