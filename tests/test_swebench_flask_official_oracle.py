"""Closed, offline SWE-bench Flask oracle boundary tests (no Docker required)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

PATH = Path(__file__).parents[1] / "tools/validation/swebench_flask_official_oracle.py"
SPEC = importlib.util.spec_from_file_location("swebench_flask_official_oracle", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _row() -> dict:
    row = {field: "value" for field in MODULE.ROW_FIELDS}
    row.update(
        instance_id=MODULE.INSTANCE_ID,
        repo="pallets/flask",
        base_commit=MODULE.BASE_COMMIT,
        version="2.3",
        image="swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest",
        log_parser="parse_log_flask",
        eval_type="pass_and_fail",
        patch="diff --git a/a b/a\n",
        eval_script="#!/bin/bash\n",
        FAIL_TO_PASS=["tests::new"],
        PASS_TO_PASS=["tests::old"],
    )
    return row


def _grade(*, status_map: dict | None = None, resolved: bool = True) -> dict:
    return {
        "status_map": status_map or {"tests::new": "PASSED", "tests::old": "PASSED"},
        "report": {
            MODULE.INSTANCE_ID: {
                "patch_is_None": False,
                "patch_exists": True,
                "patch_successfully_applied": True,
                "resolved": resolved,
                "tests_status": {
                    "FAIL_TO_PASS": {"success": ["tests::new"], "failure": []},
                    "PASS_TO_PASS": {"success": ["tests::old"], "failure": []},
                },
            }
        },
    }


def test_row_requires_exact_digest_shape_and_instance(tmp_path: Path, monkeypatch) -> None:
    row = _row()
    path = tmp_path / "row.json"
    path.write_bytes(MODULE.canonical_json(row))
    monkeypatch.setattr(MODULE, "ROW_SHA256", MODULE.sha256(MODULE.canonical_json(row)))
    assert MODULE.load_locked_row(path)["instance_id"] == MODULE.INSTANCE_ID
    row["unexpected"] = "field"
    path.write_bytes(MODULE.canonical_json(row))
    with pytest.raises(MODULE.OracleError, match="unknown or missing"):
        MODULE.load_locked_row(path)
    del row["unexpected"]
    row["repo"] = "wrong/repo"
    path.write_bytes(MODULE.canonical_json(row))
    with pytest.raises(MODULE.OracleError, match="digest mismatch"):
        MODULE.load_locked_row(path)


def test_native_platform_and_safe_child_environment(monkeypatch) -> None:
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Darwin")
    with pytest.raises(MODULE.OracleError, match="native linux/amd64"):
        MODULE.check_native_linux()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-marker")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret-marker")
    monkeypatch.setenv("UV_CACHE_DIR", "/private/uv-cache")
    env = MODULE.safe_subprocess_env(pythonpath="/pinned/source")
    assert env["PYTHONPATH"] == "/pinned/source"
    assert env["UV_CACHE_DIR"] == "/private/uv-cache"
    assert "DEEPSEEK_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_image_requires_locked_platform_digest_and_accepts_docker_hub_normalization(
    monkeypatch,
) -> None:
    info = {
        "Os": "linux",
        "Architecture": "amd64",
        "RepoDigests": [MODULE.IMAGE.removeprefix("docker.io/")],
        "Id": "sha256:" + "a" * 64,
    }
    seen = []

    def fake_run(command, **_kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(info), "")

    monkeypatch.setattr(MODULE, "_run", fake_run)
    assert MODULE.check_local_image(MODULE.IMAGE) == info["Id"]
    assert seen[0][:3] == ["docker", "image", "inspect"]
    with pytest.raises(MODULE.OracleError, match="locked"):
        MODULE.check_local_image("swebench/flask:latest")
    info["RepoDigests"] = ["swebench/flask@sha256:" + "b" * 64]
    with pytest.raises(MODULE.OracleError, match="platform digest"):
        MODULE.check_local_image(MODULE.IMAGE)


def test_gold_grade_needs_every_expected_official_status() -> None:
    summary = MODULE.validate_official_grade(_row(), _grade())
    assert summary == {
        "expected_tests": 2,
        "observed_tests": 2,
        "fail_to_pass_success": 1,
        "fail_to_pass_failure": 0,
        "pass_to_pass_success": 1,
        "pass_to_pass_failure": 0,
        "resolved": True,
    }
    for status_map, reason in (
        ({"tests::new": "PASSED"}, "incomplete"),
        ({"tests::new": "UNKNOWN", "tests::old": "PASSED"}, "unknown"),
        ({"tests::new": "SKIPPED", "tests::old": "PASSED"}, "inconclusive"),
    ):
        with pytest.raises(MODULE.OracleError, match=reason):
            MODULE.validate_official_grade(_row(), _grade(status_map=status_map))
    mismatched = _grade()
    mismatched["report"][MODULE.INSTANCE_ID]["tests_status"]["FAIL_TO_PASS"] = {
        "success": [],
        "failure": [],
    }
    with pytest.raises(MODULE.OracleError, match="denominator"):
        MODULE.validate_official_grade(_row(), mismatched)


def test_empty_is_official_unscored_classification() -> None:
    report = {
        "empty_patch_ids": [MODULE.INSTANCE_ID],
        "submitted_instances": 1,
        "empty_patch_instances": 1,
        "completed_instances": 0,
        "resolved_instances": 0,
        "error_instances": 0,
        "schema_version": 2,
    }
    assert MODULE._validate_empty(report) == {
        "classification": "official_empty_patch_unscored",
        "official_report_schema": 2,
        "test_statuses": None,
        "resolved": None,
    }
    with pytest.raises(MODULE.OracleError, match="invalid empty-patch"):
        MODULE._validate_empty({**report, "resolved_instances": 1})


def test_offline_docker_invocation_is_fresh_and_bounded(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE, "_container_absent", lambda _name: True)
    result = MODULE.run_case(
        name="gold",
        patch=b"candidate",
        eval_script=b"official eval script",
        output_dir=tmp_path,
        timeout_seconds=100,
    )
    command, kwargs = calls[0]
    assert command[:2] == ["docker", "run"]
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--pull") + 1] == "never"
    assert command[command.index("--platform") + 1] == "linux/amd64"
    assert command[command.index("--cpus") + 1] == "2"
    assert command[command.index("--memory") + 1] == "4g"
    assert command[command.index("--pids-limit") + 1] == "256"
    assert command[command.index("--log-driver") + 1] == "none"
    assert command[-2] == MODULE.IMAGE
    assert kwargs["timeout"] == 100
    assert "DEEPSEEK_API_KEY" not in kwargs["env"]
    assert result["container_removed"] is True
    assert result["test_output_sha256"] == MODULE.sha256(b"")


def test_known_bad_patch_is_a_real_nonempty_patch(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    patch = tmp_path / "known-bad.diff"
    patch.write_bytes(MODULE.KNOWN_BAD_PATCH)
    subprocess.run(["git", "-C", str(tmp_path), "apply", "--check", str(patch)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "apply", str(patch)], check=True)
    assert (tmp_path / "axrun-oracle-known-bad.txt").is_file()
