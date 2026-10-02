"""Closed Django verifier contracts; all tests are local and model-free."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from axrun.adapters import swebench_django_official as adapter_module
from axrun.adapters.swebench_django_official import SweBenchDjangoOfficialVerifierAdapter
from axrun.errors import ContractError, InfrastructureError
from axrun.fixtures.swebench_django_official import run_verifier as runner
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
    canonical_digest,
)

_F2P = "test_fixed (demo.Case)"
_EXTRA = "test_other (demo.Case)"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _log(*lines: str) -> str:
    return "\n".join((runner.START_MARKER, *lines, runner.END_MARKER))


def _lock_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = canonical_digest({"fail_to_pass": [_F2P], "pass_to_pass": []})
    monkeypatch.setattr(runner, "SELECTION_SHA256", digest)
    monkeypatch.setattr(adapter_module, "_SELECTION_SHA256", digest)


def test_django_parser_tracks_upstream_multiline_and_extra_statuses() -> None:
    assert runner.parse_log_django(
        "\n".join(
            (
                f"{_F2P} ... FAIL",
                f"{_EXTRA} ... processing",
                "interleaved output",
                "ok",
                "--version is equivalent to version",
            )
        )
    ) == {
        _F2P: "FAILED",
        _EXTRA: "PASSED",
        "--version is equivalent to version": "PASSED",
    }


def test_official_one_test_denominator_preserves_extra_observed_status() -> None:
    gold = runner.score_log(_log(f"{_F2P} ... ok"), [_F2P], [])
    assert gold["resolved"] is True
    assert gold["tests_status"]["FAIL_TO_PASS"] == {"success": [_F2P], "failure": []}
    known_bad = runner.score_log(_log(f"{_F2P} ... FAIL", f"{_EXTRA} ... ok"), [_F2P], [])
    assert known_bad["resolved"] is False
    assert known_bad["status_map"] == {_F2P: "FAILED", _EXTRA: "PASSED"}
    assert known_bad["tests_status"]["FAIL_TO_PASS"] == {"success": [], "failure": [_F2P]}
    assert known_bad["tests_status"]["PASS_TO_PASS"] == {"success": [], "failure": []}


@pytest.mark.parametrize(
    ("log", "code"),
    [
        (_log(f"{_EXTRA} ... ok"), "DJANGO_EXPECTED_TEST_MISSING"),
        (_log(f"{_F2P} ... skipped"), "DJANGO_EXPECTED_TEST_INCONCLUSIVE"),
        (_log(f"{_F2P} ... ok") + "\n>>>>> Tests Errored", "DJANGO_EVALUATION_ERROR_MARKER"),
        (f"{_F2P} ... ok", "DJANGO_TEST_MARKERS_INCOMPLETE"),
    ],
)
def test_missing_skipped_or_incomplete_expected_status_fails_closed(log: str, code: str) -> None:
    with pytest.raises(runner.VerifierError, match=code):
        runner.score_log(log, [_F2P], [])


def test_locked_scorer_finds_expected_by_digest_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _lock_selection(monkeypatch)
    assert runner.score_locked_log(_log(f"{_F2P} ... ok"))["resolved"] is True
    with pytest.raises(runner.VerifierError, match="DJANGO_EXPECTED_TEST_MISSING"):
        runner.score_locked_log(_log(f"{_EXTRA} ... ok"))


def test_evaluation_log_is_stream_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "MAX_LOG_BYTES", 64)
    script = tmp_path / "eval.sh"
    script.write_text("#!/bin/bash\nhead -c 4096 /dev/zero\n", encoding="utf-8")
    log = tmp_path / "verifier.log"
    with pytest.raises(runner.VerifierError, match="DJANGO_TEST_LOG_OVERSIZED"):
        runner._evaluate(script, tmp_path, log, 5)
    assert log.stat().st_size <= 64


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
    ("kind", "classification", "score"),
    [
        ("gold", "scored", 1.0),
        ("known_bad", "scored", 0.0),
        ("empty", "empty_patch_unscored", None),
        ("invalid", "patch_apply_failed_unscored", None),
    ],
)
def test_runner_gold_known_bad_and_unscored_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    classification: str,
    score: float | None,
) -> None:
    workspace = tmp_path / "workspace"
    head = _git_workspace(workspace)
    monkeypatch.setattr(runner, "IMAGE_HEAD", head)
    _lock_selection(monkeypatch)
    candidate = tmp_path / "candidate.patch"
    if kind == "gold":
        (workspace / "setting.txt").write_text("safe\n", encoding="utf-8")
        candidate.write_bytes(subprocess.check_output(["git", "diff", "--binary"], cwd=workspace))
        subprocess.run(["git", "restore", "setting.txt"], cwd=workspace, check=True)
    elif kind == "known_bad":
        (workspace / "unrelated.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "unrelated.txt"], cwd=workspace, check=True)
        candidate.write_bytes(
            subprocess.check_output(["git", "diff", "--cached", "--binary"], cwd=workspace)
        )
        subprocess.run(["git", "reset", "-q"], cwd=workspace, check=True)
        (workspace / "unrelated.txt").unlink()
    elif kind == "empty":
        candidate.write_bytes(b"")
    else:
        candidate.write_bytes(b"not a patch\n")
    eval_script = tmp_path / "eval.sh"
    eval_script.write_text(
        "#!/bin/bash\n"
        "echo '>>>>> Start Test Output'\n"
        "if grep -qx safe setting.txt; then\n"
        f"  echo '{_F2P} ... ok'\n"
        "else\n"
        f"  echo '{_F2P} ... FAIL'\n"
        f"  echo '{_EXTRA} ... ok'\n"
        "fi\n"
        "echo '>>>>> End Test Output'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "EVAL_SCRIPT_SHA256", _sha(eval_script.read_bytes()))
    result_path, log_path = tmp_path / "verification.json", tmp_path / "verifier.log"
    assert (
        runner.main(
            [
                "--workspace",
                str(workspace),
                "--candidate",
                str(candidate),
                "--candidate-sha256",
                _sha(candidate.read_bytes()),
                "--candidate-digest",
                "b" * 64,
                "--eval-script",
                str(eval_script),
                "--eval-timeout-seconds",
                "1800",
                "--result",
                str(result_path),
                "--log",
                str(log_path),
            ]
        )
        == 0
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["classification"] == classification
    assert payload["score"] == score
    assert payload["resolved"] is (score == 1.0)
    assert payload["test_output_sha256"] == _sha(log_path.read_bytes())
    if score is None:
        assert payload["status_map"] is None
        assert payload["tests_status"] is None
        assert log_path.read_bytes() == b""
    elif kind == "known_bad":
        assert len(payload["status_map"]) == 2
        assert payload["tests_status"]["FAIL_TO_PASS"]["failure"] == [_F2P]


def _episode_candidate(tmp_path: Path) -> tuple[ResolvedEpisode, CandidateBundle]:
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"")
    eval_script = tmp_path / "eval.sh"
    eval_script.write_text("#!/bin/bash\n", encoding="utf-8")
    binding_inference = EnvironmentBinding(
        "env-inference", adapter_module._RUNTIME_IMAGE, "linux/amd64", "/testbed"
    )
    binding_verification = EnvironmentBinding(
        "env-verification", adapter_module._RUNTIME_IMAGE, "linux/amd64", "/testbed"
    )
    episode = ResolvedEpisode(
        schema_version=2,
        episode_id="django-test",
        task_id=adapter_module._INSTANCE_ID,
        seed_digest="a" * 64,
        prompt_file=str(tmp_path / "prompt.txt"),
        task=TaskSpec("swebench-django-official", "1", {"base_commit": adapter_module._IMAGE_HEAD}),
        inference_environment=binding_inference,
        verification_environment=binding_verification,
        harness=HarnessSpec("static-candidate", "1"),
        candidate=CandidateSpec("git-patch", "1"),
        verifier=VerifierSpec(
            "swebench-django-official",
            "1",
            timeout_seconds=1860,
            config={
                "verifier_file": str(adapter_module._RUNNER),
                "eval_script_file": str(eval_script),
                "eval_script_sha256": adapter_module._EVAL_SCRIPT_SHA256,
                "test_selection_digest": adapter_module._SELECTION_SHA256,
                "log_parser": "parse_log_django",
                "harness_commit": adapter_module._HARNESS_COMMIT,
                "instance_id": adapter_module._INSTANCE_ID,
                "eval_timeout_seconds": 1800,
            },
        ),
        metadata={
            "official_source_image": adapter_module._TASK_IMAGE,
            "task_image": adapter_module._RUNTIME_IMAGE,
        },
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
                "patch", "/outputs/candidate.patch", "candidate.patch", 0, _sha(b""), "text/x-diff"
            ),
        ),
        digest="b" * 64,
        root=str(tmp_path),
    )
    return episode, candidate


def test_plan_uses_fresh_offline_environment_and_only_verifier_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _lock_selection(monkeypatch)
    episode, candidate = _episode_candidate(tmp_path)
    assert "fail_to_pass" not in episode.verifier.config
    assert "pass_to_pass" not in episode.verifier.config
    original = adapter_module._digest

    def allow_fake_eval(path: Path, *, size: int | None = None, expected_sha256: str = "") -> str:
        if path.name == "eval.sh":
            assert expected_sha256 == adapter_module._EVAL_SCRIPT_SHA256
            return expected_sha256
        return original(path, size=size, expected_sha256=expected_sha256)

    monkeypatch.setattr(adapter_module, "_digest", allow_fake_eval)
    plan = SweBenchDjangoOfficialVerifierAdapter().plan(episode, candidate)
    assert plan.environment_id == "env-verification"
    assert plan.cwd == "/testbed" and plan.network_policy == StageNetworkPolicy.DENY_ALL
    assert plan.secret_env == () and plan.image_mounts == ()
    assert plan.env == {"PIP_NO_INDEX": "1"}
    assert {item.target for item in plan.inputs} == {
        "/inputs/candidate.patch",
        "/opt/axrun-django/run_verifier.py",
        "/opt/axrun-django/eval.sh",
    }
    assert all(item.sha256 for item in plan.inputs)
    assert candidate.digest in plan.argv
    assert _F2P not in " ".join(plan.argv)
    assert plan.timeout_seconds == 1860


def test_plan_rejects_drifted_eval_or_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _lock_selection(monkeypatch)
    episode, candidate = _episode_candidate(tmp_path)
    with pytest.raises(ContractError, match="SHA-256 differs"):
        SweBenchDjangoOfficialVerifierAdapter().plan(episode, candidate)
    episode.verifier.config["test_selection_digest"] = "0" * 64
    with pytest.raises(ContractError, match="official lock"):
        SweBenchDjangoOfficialVerifierAdapter().plan(episode, candidate)
    episode.verifier.config["test_selection_digest"] = adapter_module._SELECTION_SHA256
    episode.verifier.config["fail_to_pass"] = [_F2P]
    with pytest.raises(ContractError, match="incomplete or unknown"):
        SweBenchDjangoOfficialVerifierAdapter().plan(episode, candidate)


def test_packaged_runner_bytes_are_pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    episode, _ = _episode_candidate(tmp_path)
    assert _sha(adapter_module._RUNNER.read_bytes()) == adapter_module._RUNNER_SHA256
    monkeypatch.setattr(adapter_module, "_RUNNER_SHA256", "0" * 64)
    with pytest.raises(ContractError, match="SHA-256 differs"):
        adapter_module.validated_django_verifier_inputs(episode)


def _stage_result(tmp_path: Path, payload: dict[str, object], log: bytes = b"") -> StageResult:
    result_file, log_file = tmp_path / "verification.json", tmp_path / "verifier.log"
    result_bytes = json.dumps(payload, sort_keys=True).encode()
    result_file.write_bytes(result_bytes)
    log_file.write_bytes(log)
    return StageResult(
        ExecutionRef("env-verification", "run-verification", "alloc-verification"),
        0,
        "",
        (
            Artifact(
                "/outputs/verification.json",
                str(result_file),
                len(result_bytes),
                _sha(result_bytes),
                "application/json",
            ),
            Artifact("/outputs/verifier.log", str(log_file), len(log), _sha(log), "text/plain"),
        ),
    )


def _unscored(classification: str) -> dict[str, object]:
    empty = classification == "empty_patch_unscored"
    return {
        "schema_version": runner.RESULT_SCHEMA,
        "candidate_digest": "b" * 64,
        "classification": classification,
        "patch_successfully_applied": None if empty else False,
        "resolved": False,
        "score": None,
        "diagnostic_code": "SWEBENCH_EMPTY_PATCH" if empty else "SWEBENCH_PATCH_APPLY_FAILED",
        "started_at": "2026-10-02T00:00:00+00:00",
        "completed_at": "2026-10-02T00:00:01+00:00",
        "eval_exit_code": None,
        "test_output_sha256": _sha(b""),
        "status_map": None,
        "tests_status": None,
        "missing_expected": None,
    }


def test_parse_result_keeps_empty_unscored_and_checks_sealed_integrity(tmp_path: Path) -> None:
    parsed = SweBenchDjangoOfficialVerifierAdapter().parse_result(
        _stage_result(tmp_path, _unscored("empty_patch_unscored"))
    )
    assert parsed.verdict == "failed" and parsed.score is None
    assert parsed.details["status_map"] is None
    bad = _unscored("empty_patch_unscored")
    bad["test_output_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="sealed test log"):
        SweBenchDjangoOfficialVerifierAdapter().parse_result(_stage_result(tmp_path, bad))
    stage = _stage_result(tmp_path, _unscored("empty_patch_unscored"))
    failed = StageResult(stage.execution, 2, "DJANGO_ASSET_DIGEST_MISMATCH", stage.artifacts)
    with pytest.raises(InfrastructureError, match="exit code 2"):
        SweBenchDjangoOfficialVerifierAdapter().parse_result(failed)


def test_parse_result_regrades_sealed_log_and_keeps_extra_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _lock_selection(monkeypatch)
    log = _log(f"{_F2P} ... FAIL", f"{_EXTRA} ... ok").encode()
    grade = runner.score_log(log.decode(), [_F2P], [])
    payload = {
        **_unscored("empty_patch_unscored"),
        "classification": "scored",
        "patch_successfully_applied": True,
        "resolved": False,
        "score": 0.0,
        "diagnostic_code": "SWEBENCH_TESTS_FAILED",
        "eval_exit_code": 1,
        "test_output_sha256": _sha(log),
        **grade,
    }
    parsed = SweBenchDjangoOfficialVerifierAdapter().parse_result(
        _stage_result(tmp_path, payload, log)
    )
    assert parsed.verdict == "failed" and parsed.score == 0.0
    assert parsed.details["status_map"] == {_F2P: "FAILED", _EXTRA: "PASSED"}
    forged_report = json.loads(json.dumps(payload))
    forged_report["tests_status"]["FAIL_TO_PASS"]["failure"] = [_EXTRA]
    with pytest.raises(ContractError, match="report differs from locked test selection"):
        SweBenchDjangoOfficialVerifierAdapter().parse_result(
            _stage_result(tmp_path, forged_report, log)
        )
    missing_status = json.loads(json.dumps(payload))
    missing_status["status_map"].pop(_F2P)
    with pytest.raises(ContractError, match="lacks the locked test selection"):
        SweBenchDjangoOfficialVerifierAdapter().parse_result(
            _stage_result(tmp_path, missing_status, log)
        )
    payload["resolved"] = True
    payload["score"] = 1.0
    payload["diagnostic_code"] = ""
    with pytest.raises(ContractError, match=r"sealed test log|differs from its sealed test log"):
        SweBenchDjangoOfficialVerifierAdapter().parse_result(_stage_result(tmp_path, payload, log))
