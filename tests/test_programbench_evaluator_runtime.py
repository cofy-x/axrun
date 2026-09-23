from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parents[1] / "fixtures/programbench/tty-clock-1.2.4-official"


def _module(name):
    spec = importlib.util.spec_from_file_location(name, FIXTURE / "verifier" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_script_only_moves_exact_setup_commands():
    module = _module("run_branch")
    source = (
        "#!/bin/bash\nset -euo pipefail\n"
        "python3 -m pip install -q --upgrade pip\n"
        "python3 -m pip install -q pytest pytest-timeout pytest-xdist pytest-dependency\n"
        "pytest --junitxml=eval/results.xml --timeout=5 --timeout-method=thread -n auto -v\n"
    )
    transformed = module._offline_script(source)
    assert "pip install" not in transformed
    assert (
        "pytest --junitxml=eval/results.xml --timeout=5 --timeout-method=signal -n auto -v"
        in transformed
    )
    with pytest.raises(module.EvaluatorError, match="setup_contract_changed"):
        module._offline_script(source.replace("--upgrade pip", "--upgrade pip wheel"))
    with pytest.raises(module.EvaluatorError):
        module._offline_script(transformed)


@pytest.mark.parametrize(
    ("preflight", "exit_code", "xml", "reason"),
    [
        (1, 0, None, "evaluator_environment_invalid"),
        (0, 1, None, "evaluator_results_missing"),
        (0, 4, "<testsuite/>", "evaluator_process_failed"),
        (0, 0, "bad XML", "evaluator_results_invalid"),
        (0, 0, "<testsuite/>", "evaluator_results_empty"),
        (0, 1, '<testsuite><testcase name="failed"><failure/></testcase></testsuite>', ""),
        (0, 0, '<testsuite><testcase name="passed"/></testsuite>', ""),
    ],
)
def test_branch_diagnostics_are_not_candidate_scores(
    tmp_path, monkeypatch, preflight, exit_code, xml, reason
):
    module = _module("run_branch")
    workspace = tmp_path / "workspace"
    (workspace / "eval").mkdir(parents=True)
    (workspace / "eval/run.sh").write_text("unused")
    stash = tmp_path / "executable"
    stash.write_bytes(b"binary")
    result = tmp_path / "result.json"
    monkeypatch.setattr(module, "_extract", lambda *args: None)
    monkeypatch.setattr(module, "_offline_script", lambda source, branch: source)

    def run(argv, **kwargs):
        if argv[0] == "python3":
            return subprocess.CompletedProcess(argv, preflight)
        if xml is not None:
            (workspace / "eval/results.xml").write_text(xml)
        return subprocess.CompletedProcess(argv, exit_code)

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_branch",
            "--dependency-lock-sha256",
            "a" * 64,
            "--branch",
            "test",
            "--asset",
            str(tmp_path / "asset"),
            "--workspace",
            str(workspace),
            "--stash",
            str(stash),
            "--executable-sha256",
            hashlib.sha256(b"binary").hexdigest(),
            "--result",
            str(result),
        ],
    )
    # The command succeeds only to seal a structured diagnostic. The adapter
    # must reject infrastructure_error instead of publishing a score.
    assert module.main() == 0
    value = json.loads(result.read_text())
    assert value["reason_code"] == reason
    assert value["status"] == ("infrastructure_error" if reason else "completed")
    if reason:
        assert value["tests"] == []


def test_dependency_check_rejects_missing_or_wrong_distribution(monkeypatch):
    module = _module("check_environment")
    monkeypatch.setattr(module.importlib.metadata, "version", lambda name: "wrong")
    with pytest.raises(ValueError, match="version mismatch"):
        module.check()
