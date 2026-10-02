# pyright: basic
"""Synthetic contract tests for the Django native oracle; Docker is never started."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).parents[1] / "tools/validation/swebench_django_native_oracle.py"
sys.path.insert(0, str(PATH.parent))
SPEC = importlib.util.spec_from_file_location("swebench_django_native_oracle", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _row() -> dict:
    return {
        "FAIL_TO_PASS": ["test_new (project_template.test_settings.TestStartProjectSettings)"],
        "PASS_TO_PASS": [],
        "instance_id": MODULE.INSTANCE_ID,
        "base_commit": MODULE.BASE_COMMIT,
        "patch": "gold patch",
        "test_patch": "private test patch",
        "eval_script": "#!/bin/bash\necho test\n",
    }


def _grade(status: str, resolved: bool) -> dict:
    case = _row()["FAIL_TO_PASS"][0]
    return {
        "status_map": {case: status},
        "report": {
            MODULE.INSTANCE_ID: {
                "patch_is_None": False,
                "patch_exists": True,
                "patch_successfully_applied": True,
                "resolved": resolved,
                "tests_status": {
                    "FAIL_TO_PASS": {
                        "success": [case] if status == "PASSED" else [],
                        "failure": [] if status == "PASSED" else [case],
                    },
                    "PASS_TO_PASS": {"success": [], "failure": []},
                    "FAIL_TO_FAIL": {"success": [], "failure": []},
                    "PASS_TO_FAIL": {"success": [], "failure": []},
                },
            }
        },
    }


def _image_info(*, image_id: str, layers: list[str], source: bool = False) -> dict:
    return {
        "Os": "linux",
        "Architecture": "amd64",
        "Id": image_id,
        "RepoDigests": [MODULE.OFFICIAL_SOURCE_IMAGE.removeprefix("docker.io/")] if source else [],
        "RootFS": {"Layers": layers},
        "Config": {"Labels": {} if source else dict(MODULE.SEED_LABELS)},
    }


def test_child_environment_excludes_credentials_and_docker_overrides(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "private")
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.example.invalid")
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    env = MODULE.child_env(source=Path("/pinned/scorer"))
    assert env["PYTHONPATH"] == "/pinned/scorer"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "DOCKER_HOST" not in env and "DOCKER_CONTEXT" not in env


def test_native_gate_rejects_mac_remote_context_and_wrong_daemon(monkeypatch) -> None:
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Darwin")
    with pytest.raises(MODULE.OracleError, match="native linux/amd64"):
        MODULE.check_native_docker()
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Linux")
    monkeypatch.setattr(MODULE.platform, "machine", lambda: "x86_64")

    def remote(args, **_kwargs):
        return subprocess.CompletedProcess(args, 0, json.dumps("ssh://remote"), "")

    monkeypatch.setattr(MODULE, "_run", remote)
    with pytest.raises(MODULE.OracleError, match="local Unix-socket"):
        MODULE.check_native_docker()

    def wrong_arch(args, **_kwargs):
        payload = (
            "unix:///var/run/docker.sock"
            if args[1] == "context"
            else {"OSType": "linux", "Architecture": "aarch64"}
        )
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setattr(MODULE, "_run", wrong_arch)
    with pytest.raises(MODULE.OracleError, match="daemon is not native"):
        MODULE.check_native_docker()


def test_image_contract_requires_exact_source_manifest_and_one_derived_layer(monkeypatch) -> None:
    base = "sha256:" + "a" * 64
    seed = "sha256:" + "b" * 64
    first = "sha256:" + "1" * 64
    second = "sha256:" + "2" * 64
    source_info = _image_info(image_id=base, layers=[first], source=True)
    seed_info = _image_info(image_id=seed, layers=[first, second])

    def fake_run(args, **_kwargs):
        info = source_info if args[3] == MODULE.OFFICIAL_SOURCE_IMAGE else seed_info
        return subprocess.CompletedProcess(args, 0, json.dumps(info), "")

    monkeypatch.setattr(MODULE, "_run", fake_run)
    assert MODULE.check_images(seed) == {"source_image_id": base, "seed_image_id": seed}
    with pytest.raises(MODULE.OracleError, match="immutable local image ID"):
        MODULE.check_images("axrun-django:mutable")
    source_info["RepoDigests"] = ["wrong/repo@sha256:" + "f" * 64]
    with pytest.raises(MODULE.OracleError, match="locked platform manifest"):
        MODULE.check_images(seed)
    source_info["RepoDigests"] = [MODULE.OFFICIAL_SOURCE_IMAGE]
    seed_info["RootFS"]["Layers"] = [second, first]
    with pytest.raises(MODULE.OracleError, match="source layer ancestry"):
        MODULE.check_images(seed)
    seed_info["RootFS"]["Layers"] = [first, second]
    seed_info["Config"]["Labels"]["io.axrun.base-commit"] = "0" * 40
    with pytest.raises(MODULE.OracleError, match="labels differ"):
        MODULE.check_images(seed)
    seed_info["RootFS"] = None
    with pytest.raises(MODULE.OracleError, match="root filesystem identity"):
        MODULE.check_images(seed)


def test_private_output_destination_rejects_tracked_git_path(tmp_path, monkeypatch) -> None:
    path = tmp_path / "evidence"

    def tracked(args, **_kwargs):
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, str(tmp_path), "")
        return subprocess.CompletedProcess(args, 1, "", "")

    monkeypatch.setattr(MODULE, "_run", tracked)
    with pytest.raises(MODULE.OracleError, match="must be ignored"):
        MODULE.check_private_output_destination(path)

    def ignored(args, **_kwargs):
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, str(tmp_path), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(MODULE, "_run", ignored)
    MODULE.check_private_output_destination(path)


def test_audit_is_readonly_offline_bounded_and_requires_clean_base(monkeypatch) -> None:
    seed = "sha256:" + "b" * 64
    payload = {
        "git_head": MODULE.BASE_COMMIT,
        "git_dirty": False,
        "base_commit_present": True,
        "system_python": "3.8.10",
        "test_python": "3.6.13",
        "git_object_count": 1000,
        "git_object_store_kib": 4096,
    }
    calls = []
    cleanup = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        kwargs["stdout"].write(MODULE.canonical_json(payload))
        return subprocess.CompletedProcess(args, 0, None, None)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE, "_container_absent", lambda _name: True)
    monkeypatch.setattr(MODULE, "_ensure_removed", cleanup.append)
    assert MODULE.audit_seed(seed) == payload
    args, kwargs = calls[0]
    assert args[:2] == ["docker", "run"]
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--pull") + 1] == "never"
    assert args[args.index("--platform") + 1] == "linux/amd64"
    assert args[args.index("--cpus") + 1] == "2"
    assert args[args.index("--memory") + 1] == "4g"
    assert args[args.index("--pids-limit") + 1] == "256"
    assert "--read-only" in args and "--mount" not in args
    assert args[-3:-1] == [seed, "-c"]
    assert kwargs["timeout"] == 60
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert cleanup == [args[args.index("--name") + 1]]
    payload["git_dirty"] = True
    with pytest.raises(MODULE.OracleError, match="clean base"):
        MODULE.audit_seed(seed)
    payload["git_dirty"] = False
    payload["system_python"] = "3.7.17"
    with pytest.raises(MODULE.OracleError, match="Python"):
        MODULE.audit_seed(seed)


def test_each_case_is_fresh_offline_bounded_and_mounted_readonly(tmp_path, monkeypatch) -> None:
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"synthetic nonempty")
    eval_script = tmp_path / "eval.sh"
    eval_script.write_bytes(b"script")
    monkeypatch.setattr(MODULE, "_container_absent", lambda _name: True)
    cleanup = []
    monkeypatch.setattr(MODULE, "_ensure_removed", cleanup.append)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        kwargs["stdout"].write(b">>>>> Start Test Output\ncase ... FAIL\n>>>>> End Test Output\n")
        return subprocess.CompletedProcess(args, 1, None, None)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    seed = "sha256:" + "b" * 64
    first = MODULE.run_case("gold", patch, eval_script, tmp_path, seed, 100)
    second = MODULE.run_case("known_bad", patch, eval_script, tmp_path, seed, 100)
    assert first["classification"] == "test_completed_nonzero_exit"
    assert second["container_removed"] is True
    names = [args[args.index("--name") + 1] for args, _ in calls]
    assert len(names) == len(set(names)) == 2
    assert cleanup == names
    for args, kwargs in calls:
        assert args[args.index("--network") + 1] == "none"
        assert args[args.index("--pull") + 1] == "never"
        assert args[args.index("--platform") + 1] == "linux/amd64"
        assert args[args.index("--cpus") + 1] == "2"
        assert args[args.index("--memory") + 1] == "4g"
        assert args[args.index("--pids-limit") + 1] == "256"
        assert args[args.index("--log-driver") + 1] == "none"
        mounts = [args[i + 1] for i, item in enumerate(args[:-1]) if item == "--mount"]
        assert len(mounts) == 3 and all(mount.endswith(",readonly") for mount in mounts)
        env_values = [args[i + 1] for i, item in enumerate(args[:-1]) if item == "--env"]
        assert env_values == ["PIP_NO_INDEX=1", "PIP_DISABLE_PIP_VERSION_CHECK=1"]
        assert args[-2:] == [seed, "/tmp/axrun-oracle-runner.sh"]
        assert kwargs["timeout"] == 100
        assert "ANTHROPIC_AUTH_TOKEN" not in kwargs["env"]


def test_timeout_and_cleanup_failure_never_yield_a_case_verdict(tmp_path, monkeypatch) -> None:
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"nonempty")
    eval_script = tmp_path / "eval.sh"
    eval_script.write_bytes(b"script")
    monkeypatch.setattr(MODULE, "_container_absent", lambda _name: True)
    cleaned = []
    monkeypatch.setattr(MODULE, "_ensure_removed", cleaned.append)

    def timeout(args, **_kwargs):
        raise subprocess.TimeoutExpired(args, 60)

    monkeypatch.setattr(MODULE.subprocess, "run", timeout)
    with pytest.raises(MODULE.OracleError, match="timed out"):
        MODULE.run_case("gold", patch, eval_script, tmp_path, "sha256:" + "b" * 64, 60)
    assert len(cleaned) == 1

    def complete(args, **kwargs):
        kwargs["stdout"].write(b">>>>> Start Test Output\n>>>>> End Test Output\n")
        return subprocess.CompletedProcess(args, 0, None, None)

    monkeypatch.setattr(MODULE.subprocess, "run", complete)
    monkeypatch.setattr(
        MODULE,
        "_ensure_removed",
        lambda _name: (_ for _ in ()).throw(MODULE.OracleError("cleanup")),
    )
    with pytest.raises(MODULE.OracleError, match="cleanup"):
        MODULE.run_case("known_bad", patch, eval_script, tmp_path, "sha256:" + "b" * 64, 60)


def test_cleanup_must_confirm_exact_container_absence(monkeypatch) -> None:
    name = "axrun-django-oracle-synthetic"
    calls = []

    def never_removed(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, name + "\n", "")

    monkeypatch.setattr(MODULE, "_run", never_removed)
    with pytest.raises(MODULE.OracleError, match="cleanup is incomplete"):
        MODULE._ensure_removed(name)
    assert any(args[1:3] == ["rm", "--force"] for args in calls)


def test_official_scorer_grades_expected_statuses_and_negative_control() -> None:
    assert MODULE.validate_grade(_row(), _grade("PASSED", True), "gold") == {
        "expected_tests": 1,
        "observed_tests": 1,
        "resolved": True,
        "fail_to_pass_success": 1,
        "fail_to_pass_failure": 0,
        "pass_to_pass_success": 0,
        "pass_to_pass_failure": 0,
    }
    negative = MODULE.validate_grade(_row(), _grade("FAILED", False), "known_bad")
    assert negative["resolved"] is False and negative["fail_to_pass_failure"] == 1
    module_report = _grade("PASSED", True)
    module_report["status_map"]["other test in same selected module"] = "PASSED"
    assert MODULE.validate_grade(_row(), module_report, "gold")["observed_tests"] == 2
    with pytest.raises(MODULE.OracleError, match="positive control"):
        MODULE.validate_grade(_row(), _grade("FAILED", False), "gold")
    with pytest.raises(MODULE.OracleError, match="negative control"):
        MODULE.validate_grade(_row(), _grade("PASSED", True), "known_bad")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda grade: grade["status_map"].clear(), "expected status is missing"),
        (lambda grade: grade["status_map"].update({"bad": "UNKNOWN"}), "unknown test status"),
        (lambda grade: grade["status_map"].update({"bad": ["PASSED"]}), "unknown test status"),
        (
            lambda grade: grade["status_map"].update({next(iter(grade["status_map"])): "SKIPPED"}),
            "inconclusive",
        ),
        (lambda grade: grade["report"][MODULE.INSTANCE_ID].pop("tests_status"), "per-test status"),
        (
            lambda grade: grade["report"][MODULE.INSTANCE_ID]["tests_status"]["FAIL_TO_PASS"][
                "success"
            ].clear(),
            "denominator",
        ),
    ],
)
def test_official_scorer_fails_closed_on_missing_or_malformed_status(mutation, reason) -> None:
    grade = _grade("PASSED", True)
    mutation(grade)
    with pytest.raises(MODULE.OracleError, match=reason):
        MODULE.validate_grade(_row(), grade, "gold")


def test_empty_requires_upstream_unscored_report_and_no_test_verdict() -> None:
    report = {
        "schema_version": 2,
        "submitted_instances": 1,
        "empty_patch_instances": 1,
        "empty_patch_ids": [MODULE.INSTANCE_ID],
        "completed_instances": 0,
        "resolved_instances": 0,
        "error_instances": 0,
    }
    assert MODULE.validate_empty(report) == {
        "classification": "official_empty_patch_unscored",
        "test_statuses": None,
        "resolved": None,
        "official_report_schema": 2,
    }
    with pytest.raises(MODULE.OracleError, match="unscored"):
        MODULE.validate_empty({**report, "completed_instances": 1})
    with pytest.raises(MODULE.OracleError, match="unscored"):
        MODULE.validate_empty({**report, "empty_patch_ids": []})


def test_scorer_process_uses_code_not_hidden_body_in_argv(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    row = tmp_path / "row.json"
    row.write_text("private row marker")
    patch = tmp_path / "gold.patch"
    patch.write_text("private gold patch marker")
    log = tmp_path / "test.log"
    log.write_text("private test log marker")
    output = tmp_path / "grade.json"
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        output.write_text("{}")
        return subprocess.CompletedProcess(args, 0, None, None)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    assert (
        MODULE.official_scorer("grade", Path("/venv/bin/python"), source, row, patch, log, output)
        == {}
    )
    args, kwargs = calls[0]
    assert args[1:3] == ["-c", MODULE.SCORER_BRIDGE]
    assert "private gold patch marker" not in str(args)
    assert "private test log marker" not in str(args)
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["timeout"] == 180


def test_run_oracle_executes_all_three_and_keeps_empty_unscored(tmp_path, monkeypatch) -> None:
    paths = {}
    for key in ("row", "gold", "known_bad", "empty", "eval"):
        paths[key] = tmp_path / f"{key}.data"
        paths[key].write_bytes(b"" if key == "empty" else key.encode())
    monkeypatch.setattr(MODULE, "check_native_docker", lambda: None)
    monkeypatch.setattr(MODULE, "check_assets", lambda _dir: (_row(), paths, "a" * 64))
    monkeypatch.setattr(MODULE, "check_source", lambda _path: None)
    monkeypatch.setattr(MODULE, "check_scorer", lambda *_args: "b" * 64)
    monkeypatch.setattr(
        MODULE,
        "check_images",
        lambda image: {"source_image_id": "sha256:" + "c" * 64, "seed_image_id": image},
    )
    monkeypatch.setattr(MODULE, "audit_seed", lambda _image: {"git_head": MODULE.BASE_COMMIT})
    calls = []

    def run_case(name, *_args):
        calls.append(name)
        return {"container_removed": True}

    monkeypatch.setattr(MODULE, "run_case", run_case)
    monkeypatch.setattr(
        MODULE,
        "official_scorer",
        lambda action, *_args: (
            {
                "schema_version": 2,
                "submitted_instances": 1,
                "empty_patch_instances": 1,
                "empty_patch_ids": [MODULE.INSTANCE_ID],
                "completed_instances": 0,
                "resolved_instances": 0,
                "error_instances": 0,
            }
            if action == "empty"
            else _grade("PASSED" if len(calls) == 1 else "FAILED", len(calls) == 1)
        ),
    )
    output = tmp_path / "receipt"
    result = MODULE.run_oracle(
        assets_dir=tmp_path / "assets",
        scorer_source=tmp_path / "scorer",
        scorer_python=tmp_path / "venv/bin/python",
        scorer_freeze=tmp_path / "freeze.txt",
        seed_image_id="sha256:" + "d" * 64,
        output_dir=output,
        timeout_seconds=60,
    )
    assert calls == ["gold", "known_bad", "empty"]
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["status"] == "completed"
    assert receipt["cases"]["gold"]["official_summary"]["resolved"] is True
    assert receipt["cases"]["known_bad"]["official_summary"]["resolved"] is False
    assert receipt["cases"]["empty"]["official_summary"]["resolved"] is None
    assert result["empty"] == "official_empty_patch_unscored"
