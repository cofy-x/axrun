"""Closed, offline SWE-bench Flask oracle boundary tests (no Docker required)."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
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


def test_scorer_venv_python_keeps_interpreter_symlink_identity(tmp_path: Path) -> None:
    venv = tmp_path / "scorer-venv"
    binary = venv / "bin"
    binary.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    python = binary / "python"
    python.symlink_to(sys.executable)
    assert MODULE.scorer_venv_python(python) == python.absolute()
    assert MODULE.scorer_venv_python(python) != python.resolve()
    with pytest.raises(MODULE.OracleError, match="virtual environment"):
        MODULE.scorer_venv_python(Path("/bin/sh"))


def test_offline_build_wheels_pin_public_artifacts() -> None:
    assert [
        (artifact.filename, artifact.size, artifact.sha256)
        for artifact in MODULE.locked_build_wheels()
    ] == [
        (
            "setuptools-70.0.0-py3-none-any.whl",
            863_432,
            "54faa7f2e8d2d11bcd2c07bed282eef1046b5c080d1c32add737d7b5817b1ad4",
        ),
        (
            "wheel-0.45.1-py3-none-any.whl",
            72_494,
            "708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248",
        ),
    ]
    assert all(
        artifact.url.startswith("https://files.pythonhosted.org/packages/")
        for artifact in MODULE.locked_build_wheels()
    )


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


def test_image_contract_audit_is_readonly_bounded_and_reports_head_without_gating(
    monkeypatch,
) -> None:
    image_head = "b" * 40
    assert image_head != MODULE.BASE_COMMIT
    payload = {
        "git_head": image_head,
        "git_dirty": True,
        "base_commit_present": True,
    }
    calls = []
    cleanup = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write(MODULE.canonical_json(payload))
        return subprocess.CompletedProcess(command, 0, None, None)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE, "_ensure_removed", cleanup.append)
    assert MODULE.audit_official_image_contract() == payload
    command, kwargs = calls[0]
    assert command[:2] == ["docker", "run"]
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--pull") + 1] == "never"
    assert command[command.index("--platform") + 1] == "linux/amd64"
    assert command[command.index("--cpus") + 1] == "2"
    assert command[command.index("--memory") + 1] == "4g"
    assert command[command.index("--pids-limit") + 1] == "256"
    assert command[command.index("--log-driver") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert "--mount" not in command
    assert command[-3:-1] == [MODULE.IMAGE, "-c"]
    assert "status --porcelain=v1 --untracked-files=all" in command[-1]
    assert "GIT_OPTIONAL_LOCKS=0" in command[-1]
    assert kwargs["timeout"] == MODULE.IMAGE_CONTRACT_TIMEOUT_SECONDS
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["preexec_fn"] == MODULE._limit_image_contract_output
    assert "DEEPSEEK_API_KEY" not in kwargs["env"]
    assert cleanup == [command[command.index("--name") + 1]]


@pytest.mark.parametrize(
    "payload",
    [
        {"git_head": "not-a-commit", "git_dirty": False, "base_commit_present": True},
        {"git_head": "a" * 40, "git_dirty": "false", "base_commit_present": True},
        {"git_head": "a" * 40, "git_dirty": False, "base_commit_present": True, "files": []},
    ],
)
def test_image_contract_audit_rejects_malformed_fields(monkeypatch, payload) -> None:
    def fake_run(command, **kwargs):
        kwargs["stdout"].write(MODULE.canonical_json(payload))
        return subprocess.CompletedProcess(command, 0, None, None)

    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        fake_run,
    )
    monkeypatch.setattr(MODULE, "_ensure_removed", lambda _name: None)
    with pytest.raises(MODULE.OracleError, match="fields are invalid"):
        MODULE.audit_official_image_contract()


def test_image_contract_audit_rejects_nonzero_exit_without_exposing_stderr(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, None, b"private"),
    )
    monkeypatch.setattr(MODULE, "_ensure_removed", lambda _name: None)
    with pytest.raises(MODULE.OracleError, match="contract audit failed") as exc:
        MODULE.audit_official_image_contract()
    assert "private" not in str(exc.value)


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
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / MODULE.SETUPTOOLS_WHEEL_NAME).write_bytes(b"safe")
    (wheelhouse / MODULE.WHEEL_DIST_NAME).write_bytes(b"wheel")
    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_BYTES", 4)
    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_SHA256", MODULE.sha256(b"safe"))
    monkeypatch.setattr(MODULE, "WHEEL_DIST_BYTES", 5)
    monkeypatch.setattr(MODULE, "WHEEL_DIST_SHA256", MODULE.sha256(b"wheel"))
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
        wheelhouse=wheelhouse,
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
    mounts = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "--mount"]
    assert any(
        mount == f"type=bind,source={wheelhouse},target={MODULE.WHEELHOUSE_MOUNT},readonly"
        for mount in mounts
    )
    env_values = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "--env"]
    assert env_values == ["PIP_NO_INDEX=1", f"PIP_FIND_LINKS={MODULE.WHEELHOUSE_MOUNT}"]
    assert command[-2] == MODULE.IMAGE
    assert kwargs["timeout"] == 100
    assert "DEEPSEEK_API_KEY" not in kwargs["env"]
    assert result["container_removed"] is True
    assert result["test_output_sha256"] == MODULE.sha256(b"")


def test_pinned_build_wheel_downloads_and_closed_wheelhouse(tmp_path: Path, monkeypatch) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    bodies = {
        MODULE.SETUPTOOLS_WHEEL_URL: b"fixed-setuptools",
        MODULE.WHEEL_DIST_URL: b"fixed-wheel",
    }
    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_BYTES", len(bodies[MODULE.SETUPTOOLS_WHEEL_URL]))
    monkeypatch.setattr(
        MODULE, "SETUPTOOLS_WHEEL_SHA256", MODULE.sha256(bodies[MODULE.SETUPTOOLS_WHEEL_URL])
    )
    monkeypatch.setattr(MODULE, "WHEEL_DIST_BYTES", len(bodies[MODULE.WHEEL_DIST_URL]))
    monkeypatch.setattr(MODULE, "WHEEL_DIST_SHA256", MODULE.sha256(bodies[MODULE.WHEEL_DIST_URL]))

    class Response(io.BytesIO):
        def __init__(self, body: bytes):
            super().__init__(body)
            self.headers = {"Content-Length": str(len(body))}

    monkeypatch.setattr(
        MODULE.urllib.request,
        "urlopen",
        lambda request, **_kwargs: Response(bodies[request.full_url]),
    )
    for artifact in MODULE.locked_build_wheels():
        wheel = MODULE._download_locked_wheel(wheelhouse, artifact)
        assert wheel.read_bytes() == bodies[artifact.url]
    assert set(MODULE.check_locked_wheelhouse(wheelhouse)) == {
        MODULE.SETUPTOOLS_WHEEL_NAME,
        MODULE.WHEEL_DIST_NAME,
    }
    (wheelhouse / "unexpected.whl").write_bytes(b"unlocked")
    with pytest.raises(MODULE.OracleError, match="unknown artifacts"):
        MODULE.check_locked_wheelhouse(wheelhouse)
    (wheelhouse / "unexpected.whl").unlink()
    (wheelhouse / MODULE.WHEEL_DIST_NAME).write_bytes(b"tampered")
    with pytest.raises(MODULE.OracleError, match="size or SHA-256"):
        MODULE.check_locked_wheelhouse(wheelhouse)


def test_build_wheel_download_digest_mismatch_fails_closed(tmp_path: Path, monkeypatch) -> None:
    class Response(io.BytesIO):
        def __init__(self, body: bytes):
            super().__init__(body)
            self.headers = {"Content-Length": "4"}

    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_BYTES", 4)
    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_SHA256", MODULE.sha256(b"good"))
    monkeypatch.setattr(
        MODULE.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(b"evil")
    )
    wheelhouse = tmp_path / "wheelhouse"
    with pytest.raises(MODULE.OracleError, match=r"downloaded setuptools-70\.0\.0"):
        MODULE._download_locked_wheel(wheelhouse, MODULE.locked_build_wheels()[0])
    assert list(wheelhouse.iterdir()) == []


def test_wheelhouse_requires_both_locked_artifacts(tmp_path: Path, monkeypatch) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / MODULE.SETUPTOOLS_WHEEL_NAME).write_bytes(b"safe")
    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_BYTES", 4)
    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_SHA256", MODULE.sha256(b"safe"))
    with pytest.raises(MODULE.OracleError, match="missing or unknown"):
        MODULE.check_locked_wheelhouse(wheelhouse)
    (wheelhouse / MODULE.WHEEL_DIST_NAME).symlink_to(wheelhouse / MODULE.SETUPTOOLS_WHEEL_NAME)
    with pytest.raises(MODULE.OracleError, match="not a regular file"):
        MODULE.check_locked_wheelhouse(wheelhouse)


def test_offline_install_preflight_uses_same_readonly_wheelhouse(
    tmp_path: Path, monkeypatch
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / MODULE.SETUPTOOLS_WHEEL_NAME).write_bytes(b"safe")
    (wheelhouse / MODULE.WHEEL_DIST_NAME).write_bytes(b"wheel")
    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_BYTES", 4)
    monkeypatch.setattr(MODULE, "SETUPTOOLS_WHEEL_SHA256", MODULE.sha256(b"safe"))
    monkeypatch.setattr(MODULE, "WHEEL_DIST_BYTES", 5)
    monkeypatch.setattr(MODULE, "WHEEL_DIST_SHA256", MODULE.sha256(b"wheel"))
    seen = []

    def fake_run(command, **_kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE, "_container_absent", lambda _name: True)
    receipt = MODULE.check_offline_install(tmp_path, 120, wheelhouse)
    command = seen[0]
    assert command[:2] == ["docker", "run"]
    assert command[command.index("--network") + 1] == "none"
    assert f"type=bind,source={wheelhouse},target={MODULE.WHEELHOUSE_MOUNT},readonly" in command
    assert "PIP_NO_INDEX=1" in command
    assert f"PIP_FIND_LINKS={MODULE.WHEELHOUSE_MOUNT}" in command
    assert command[-1] == MODULE.OFFLINE_INSTALL
    assert receipt["container_removed"] is True


def test_known_bad_patch_is_a_real_nonempty_patch(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    patch = tmp_path / "known-bad.diff"
    patch.write_bytes(MODULE.KNOWN_BAD_PATCH)
    subprocess.run(["git", "-C", str(tmp_path), "apply", "--check", str(patch)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "apply", str(patch)], check=True)
    assert (tmp_path / "axrun-oracle-known-bad.txt").is_file()
