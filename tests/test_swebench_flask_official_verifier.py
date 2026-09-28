"""Stage-zero contract tests; these do not assert native/Axern parity."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from axrun.adapters import swebench_flask_official as adapter_module
from axrun.adapters.swebench_flask_official import SweBenchFlaskOfficialVerifierAdapter
from axrun.errors import ContractError, InfrastructureError
from axrun.fixtures.swebench_flask_official import run_verifier as runner
from axrun.models import (
    Artifact,
    CandidateBundle,
    CandidateFile,
    CandidateSpec,
    EnvironmentBinding,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageNetworkPolicy,
    StageResult,
    TaskSpec,
    VerifierSpec,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _test_log(*lines: str) -> str:
    return "\n".join((runner.START_MARKER, *lines, runner.END_MARKER))


def test_pinned_flask_parser_and_official_pass_and_fail_semantics() -> None:
    grade = runner.score_log(
        _test_log(
            "PASSED tests/test_flask.py::test_fixed",
            "XFAIL tests/test_flask.py::test_maintained",
            "FAILED tests/test_flask.py::test_regressed - AssertionError",
        ),
        ["tests/test_flask.py::test_fixed"],
        ["tests/test_flask.py::test_maintained", "tests/test_flask.py::test_regressed"],
    )
    assert grade["resolved"] is False
    assert grade["status_map"] == {
        "tests/test_flask.py::test_fixed": "PASSED",
        "tests/test_flask.py::test_maintained": "XFAIL",
        "tests/test_flask.py::test_regressed": "FAILED",
    }
    assert grade["tests_status"] == {
        "FAIL_TO_PASS": {"success": ["tests/test_flask.py::test_fixed"], "failure": []},
        "PASS_TO_PASS": {
            "success": ["tests/test_flask.py::test_maintained"],
            "failure": ["tests/test_flask.py::test_regressed"],
        },
        "FAIL_TO_FAIL": {"success": [], "failure": []},
        "PASS_TO_FAIL": {"success": [], "failure": []},
    }


def test_missing_expected_test_is_explicit_failure_without_fabricated_raw_status() -> None:
    grade = runner.score_log(
        _test_log("PASSED tests/test_flask.py::test_maintained"),
        ["tests/test_flask.py::test_fixed"],
        ["tests/test_flask.py::test_maintained"],
    )
    assert grade["status_map"] == {"tests/test_flask.py::test_maintained": "PASSED"}
    assert grade["missing_expected"] == ["tests/test_flask.py::test_fixed"]
    assert grade["tests_status"]["FAIL_TO_PASS"]["failure"] == ["tests/test_flask.py::test_fixed"]
    assert grade["resolved"] is False


@pytest.mark.parametrize(
    ("log", "reason"),
    [
        ("PASSED tests/test_flask.py::test_fixed", "FLASK_TEST_MARKERS_INCOMPLETE"),
        (
            _test_log("SKIPPED tests/test_flask.py::test_fixed"),
            "FLASK_EXPECTED_TEST_SKIPPED",
        ),
        (
            _test_log("PASSED tests/test_flask.py::test_fixed") + "\n>>>>> Tests Errored",
            "FLASK_EVALUATION_ERROR_MARKER",
        ),
    ],
)
def test_incomplete_or_ambiguous_official_log_fails_closed(log: str, reason: str) -> None:
    with pytest.raises(runner.VerifierError, match=reason):
        runner.score_log(log, ["tests/test_flask.py::test_fixed"], ["test_maintained"])


def _git_workspace(path: Path) -> str:
    path.mkdir()
    (path / "setting.txt").write_text("unsafe\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "add", "setting.txt"], cwd=path, check=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Axrun",
        "GIT_AUTHOR_EMAIL": "axrun@example.invalid",
        "GIT_COMMITTER_NAME": "Axrun",
        "GIT_COMMITTER_EMAIL": "axrun@example.invalid",
    }
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=path, env=env, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()


@pytest.mark.parametrize(
    ("candidate_kind", "classification", "score", "resolved"),
    [
        ("gold", "scored", 1.0, True),
        ("known_bad", "scored", 0.0, False),
        ("empty", "empty_patch_unscored", None, False),
        ("invalid", "patch_apply_failed_unscored", None, False),
    ],
)
def test_runner_preserves_scored_and_unscored_candidate_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_kind: str,
    classification: str,
    score: float | None,
    resolved: bool,
) -> None:
    workspace = tmp_path / "workspace"
    head = _git_workspace(workspace)
    monkeypatch.setattr(runner, "IMAGE_HEAD", head)
    monkeypatch.setattr(runner, "WHEELS", {})
    candidate = tmp_path / "candidate.patch"
    if candidate_kind == "gold":
        (workspace / "setting.txt").write_text("safe\n", encoding="utf-8")
        candidate.write_bytes(subprocess.check_output(["git", "diff", "--binary"], cwd=workspace))
        subprocess.run(["git", "restore", "setting.txt"], cwd=workspace, check=True)
    elif candidate_kind == "known_bad":
        (workspace / "unrelated.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "unrelated.txt"], cwd=workspace, check=True)
        candidate.write_bytes(
            subprocess.check_output(["git", "diff", "--cached", "--binary"], cwd=workspace)
        )
        subprocess.run(["git", "reset", "-q"], cwd=workspace, check=True)
        (workspace / "unrelated.txt").unlink()
    elif candidate_kind == "empty":
        candidate.write_bytes(b"")
    else:
        candidate.write_bytes(b"not a patch\n")
    eval_script = tmp_path / "eval.sh"
    eval_script.write_text(
        "#!/bin/bash\n"
        "echo '>>>>> Start Test Output'\n"
        "if grep -qx safe setting.txt; then\n"
        "  echo 'PASSED tests/test_flask.py::test_fixed'\n"
        "else\n"
        "  echo 'FAILED tests/test_flask.py::test_fixed - AssertionError'\n"
        "fi\n"
        "echo 'PASSED tests/test_flask.py::test_maintained'\n"
        "echo '>>>>> End Test Output'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "EVAL_SCRIPT_SHA256", _digest(eval_script.read_bytes()))
    result_file = tmp_path / "verification.json"
    log_file = tmp_path / "verifier.log"
    exit_code = runner.main(
        [
            "--workspace",
            str(workspace),
            "--candidate",
            str(candidate),
            "--candidate-sha256",
            _digest(candidate.read_bytes()),
            "--candidate-digest",
            "e" * 64,
            "--eval-script",
            str(eval_script),
            "--fail-to-pass",
            '["tests/test_flask.py::test_fixed"]',
            "--pass-to-pass",
            '["tests/test_flask.py::test_maintained"]',
            "--eval-timeout-seconds",
            "1800",
            "--result",
            str(result_file),
            "--log",
            str(log_file),
        ]
    )
    assert exit_code == 0
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert payload["classification"] == classification
    assert payload["resolved"] is resolved
    assert payload["score"] == score
    assert payload["test_output_sha256"] == _digest(log_file.read_bytes())
    if score is None:
        assert payload["status_map"] is None
        assert payload["tests_status"] is None
        assert log_file.read_bytes() == b""
    else:
        assert payload["tests_status"]["FAIL_TO_PASS"]["failure"] == (
            [] if resolved else ["tests/test_flask.py::test_fixed"]
        )


def _episode_and_candidate(tmp_path: Path) -> tuple[ResolvedEpisode, CandidateBundle]:
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"")
    eval_script = tmp_path / "eval.sh"
    eval_script.write_text("#!/bin/bash\n", encoding="utf-8")
    setuptools = tmp_path / "setuptools-70.0.0-py3-none-any.whl"
    wheel = tmp_path / "wheel-0.45.1-py3-none-any.whl"
    setuptools.write_bytes(b"fake")
    wheel.write_bytes(b"fake")
    task_image = (
        "index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:" + "9" * 64
    )
    binding = EnvironmentBinding("env-inference", task_image, "linux/amd64", "/testbed")
    verifier_binding = EnvironmentBinding("env-verification", task_image, "linux/amd64", "/testbed")
    episode = ResolvedEpisode(
        schema_version=2,
        episode_id="flask-test",
        task_id="pallets__flask-5014",
        seed_digest="a" * 64,
        prompt_file=str(tmp_path / "prompt.txt"),
        task=TaskSpec("swebench-flask-official", "1", {"base_commit": adapter_module._IMAGE_HEAD}),
        inference_environment=binding,
        verification_environment=verifier_binding,
        harness=HarnessSpec("static-candidate", "1"),
        candidate=CandidateSpec("git-patch", "1"),
        verifier=VerifierSpec(
            "swebench-flask-official",
            "1",
            timeout_seconds=1860,
            config={
                "verifier_file": str(adapter_module._RUNNER),
                "eval_script_file": str(eval_script),
                "eval_script_sha256": adapter_module._EVAL_SCRIPT_SHA256,
                "fail_to_pass": ["test_f2p"],
                "pass_to_pass": [f"test_p2p_{index}" for index in range(59)],
                "log_parser": "parse_log_flask",
                "setuptools_wheel_file": str(setuptools),
                "wheel_wheel_file": str(wheel),
                "harness_commit": adapter_module._HARNESS_COMMIT,
                "instance_id": "pallets__flask-5014",
                "eval_timeout_seconds": 1800,
            },
        ),
        metadata={"official_source_image": adapter_module._TASK_IMAGE, "task_image": task_image},
        inference_network_policy=StageNetworkPolicy.DENY_ALL,
        verification_network_policy=StageNetworkPolicy.DENY_ALL,
    )
    candidate = CandidateBundle(
        schema_version=1,
        episode_id=episode.episode_id,
        task_id=episode.task_id,
        seed_digest=episode.seed_digest,
        inference_run_id="run-inference",
        harness="static-candidate",
        harness_version="1",
        candidate="git-patch",
        candidate_version="1",
        files=(
            CandidateFile(
                role="patch",
                declared_path="/outputs/candidate.patch",
                bundle_path="candidate.patch",
                size_bytes=0,
                sha256=_digest(b""),
                media_type="text/x-diff",
            ),
        ),
        digest="b" * 64,
        root=str(tmp_path),
    )
    return episode, candidate


def test_adapter_plan_is_fresh_offline_and_content_addressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode, candidate = _episode_and_candidate(tmp_path)
    original_digest = adapter_module._digest

    def locked_test_assets(
        path: Path, *, size: int | None = None, expected_sha256: str = ""
    ) -> str:
        if path.name in {"eval.sh", *[name for name, _, _ in adapter_module._WHEELS.values()]}:
            assert expected_sha256
            return expected_sha256
        return original_digest(path, size=size, expected_sha256=expected_sha256)

    monkeypatch.setattr(adapter_module, "_digest", locked_test_assets)
    plan = SweBenchFlaskOfficialVerifierAdapter().plan(episode, candidate)
    assert plan.environment_id == "env-verification"
    assert plan.cwd == "/testbed" and plan.network_policy == StageNetworkPolicy.DENY_ALL
    assert plan.secret_env == () and plan.image_mounts == ()
    assert plan.env == {"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": "/opt/axrun-wheelhouse"}
    assert {item.target for item in plan.inputs} == {
        "/inputs/candidate.patch",
        "/opt/axrun-flask/run_verifier.py",
        "/opt/axrun-flask/eval.sh",
        "/opt/axrun-wheelhouse/setuptools-70.0.0-py3-none-any.whl",
        "/opt/axrun-wheelhouse/wheel-0.45.1-py3-none-any.whl",
    }
    assert all(item.sha256 for item in plan.inputs)
    assert candidate.digest in plan.argv
    assert plan.timeout_seconds == 1860


def test_adapter_rejects_runtime_or_asset_contract_drift(tmp_path: Path) -> None:
    episode, candidate = _episode_and_candidate(tmp_path)
    # The local test files are intentionally not the locked official wheel/eval bytes.
    with pytest.raises(ContractError, match="SHA-256 differs"):
        SweBenchFlaskOfficialVerifierAdapter().plan(episode, candidate)
    episode.metadata["official_source_image"] = "not the official source image"
    with pytest.raises(ContractError, match="locked offline amd64 image"):
        SweBenchFlaskOfficialVerifierAdapter().plan(episode, candidate)
    episode.metadata["official_source_image"] = adapter_module._TASK_IMAGE
    episode.metadata["task_image"] = "index.docker.io/other@sha256:" + "a" * 64
    with pytest.raises(ContractError, match="locked offline amd64 image"):
        SweBenchFlaskOfficialVerifierAdapter().plan(episode, candidate)


def _stage_result(
    tmp_path: Path, payload: dict[str, object], log_bytes: bytes = b""
) -> StageResult:
    result_path = tmp_path / "verification.json"
    log_path = tmp_path / "verifier.log"
    result_bytes = json.dumps(payload, sort_keys=True).encode()
    result_path.write_bytes(result_bytes)
    log_path.write_bytes(log_bytes)
    return StageResult(
        ExecutionRef("env-verification", "run-verification", "alloc-verification"),
        0,
        "",
        (
            Artifact(
                "/outputs/verification.json",
                str(result_path),
                len(result_bytes),
                _digest(result_bytes),
                "application/json",
            ),
            Artifact(
                "/outputs/verifier.log",
                str(log_path),
                len(log_bytes),
                _digest(log_bytes),
                "text/plain",
            ),
        ),
    )


def _unscored_result(classification: str, diagnostic_code: str) -> dict[str, object]:
    return {
        "schema_version": "axrun.swebench-flask-official-result@1",
        "candidate_digest": "b" * 64,
        "classification": classification,
        "patch_successfully_applied": None if classification == "empty_patch_unscored" else False,
        "resolved": False,
        "score": None,
        "diagnostic_code": diagnostic_code,
        "started_at": "2026-09-27T00:00:00+00:00",
        "completed_at": "2026-09-27T00:00:01+00:00",
        "eval_exit_code": None,
        "test_output_sha256": _digest(b""),
        "status_map": None,
        "tests_status": None,
        "missing_expected": None,
    }


@pytest.mark.parametrize(
    ("classification", "code"),
    [
        ("empty_patch_unscored", "SWEBENCH_EMPTY_PATCH"),
        ("patch_apply_failed_unscored", "SWEBENCH_PATCH_APPLY_FAILED"),
    ],
)
def test_unscored_result_remains_failed_without_fabricated_score(
    tmp_path: Path, classification: str, code: str
) -> None:
    result = SweBenchFlaskOfficialVerifierAdapter().parse_result(
        _stage_result(tmp_path, _unscored_result(classification, code))
    )
    assert result.verdict == "failed" and result.score is None
    assert result.details["status_map"] is None
    assert result.diagnostic_code == code


def test_result_mismatch_or_run_failure_is_infrastructure(tmp_path: Path) -> None:
    payload = _unscored_result("empty_patch_unscored", "SWEBENCH_EMPTY_PATCH")
    payload["test_output_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="sealed test log"):
        SweBenchFlaskOfficialVerifierAdapter().parse_result(_stage_result(tmp_path, payload))
    payload["test_output_sha256"] = _digest(b"")
    stage = _stage_result(tmp_path, payload)
    failed = StageResult(stage.execution, 2, "FLASK_ASSET_DIGEST_MISMATCH", stage.artifacts)
    with pytest.raises(InfrastructureError, match="exit code 2"):
        SweBenchFlaskOfficialVerifierAdapter().parse_result(failed)


def test_scored_result_requires_full_denom_and_status_consistency(tmp_path: Path) -> None:
    log = _test_log("PASSED test_f2p", *(f"PASSED test_p2p_{index}" for index in range(59)))
    expected_p2p = [f"test_p2p_{index}" for index in range(59)]
    payload = {
        **_unscored_result("empty_patch_unscored", "SWEBENCH_EMPTY_PATCH"),
        "classification": "scored",
        "patch_successfully_applied": True,
        "resolved": True,
        "score": 1.0,
        "diagnostic_code": "",
        "eval_exit_code": 0,
        "test_output_sha256": _digest(log.encode()),
        "status_map": {"test_f2p": "PASSED", **dict.fromkeys(expected_p2p, "PASSED")},
        "tests_status": {
            "FAIL_TO_PASS": {"success": ["test_f2p"], "failure": []},
            "PASS_TO_PASS": {"success": expected_p2p, "failure": []},
            "FAIL_TO_FAIL": {"success": [], "failure": []},
            "PASS_TO_FAIL": {"success": [], "failure": []},
        },
        "missing_expected": [],
    }
    parsed = SweBenchFlaskOfficialVerifierAdapter().parse_result(
        _stage_result(tmp_path, payload, log.encode())
    )
    assert parsed.verdict == "passed" and parsed.score == 1.0
    assert parsed.details["status_map"]["test_f2p"] == "PASSED"
    failed_log = log.replace("PASSED test_f2p", "FAILED test_f2p - AssertionError")
    payload["test_output_sha256"] = _digest(failed_log.encode())
    with pytest.raises(ContractError, match="differs from its sealed test log"):
        SweBenchFlaskOfficialVerifierAdapter().parse_result(
            _stage_result(tmp_path, payload, failed_log.encode())
        )
    payload["test_output_sha256"] = _digest(log.encode())
    payload["status_map"]["test_f2p"] = "FAILED"
    with pytest.raises(ContractError, match="success contradicts"):
        SweBenchFlaskOfficialVerifierAdapter().parse_result(
            _stage_result(tmp_path, payload, log.encode())
        )
    payload["status_map"]["test_f2p"] = "PASSED"
    payload["eval_exit_code"] = -9
    with pytest.raises(ContractError, match="scored result fields"):
        SweBenchFlaskOfficialVerifierAdapter().parse_result(
            _stage_result(tmp_path, payload, log.encode())
        )
