"""Private helper contract; actual benchmark execution remains in normal CLI."""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PATH = Path(__file__).parents[1] / "tools/validation/swebench_flask_cli.py"
SPEC = importlib.util.spec_from_file_location("swebench_flask_cli_helper", PATH)
assert SPEC and SPEC.loader
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def _invoke(tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    return helper.run_cli(
        state_dir=tmp_path / "state",
        context_config=tmp_path / "private-context.json",
        command=["resume", "episode"],
        log_dir=tmp_path / "private-logs",
        label="resume",
        **kwargs,
    )


def test_helper_invokes_installed_formal_cli_without_key_in_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "never-log-actual-credential")

    def run(arguments: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(arguments)
        assert "never-log-actual-credential" not in " ".join(arguments)
        assert kwargs["check"] is False and kwargs["timeout"] == 7200.0
        kwargs["stdout"].write(b'{"schema_version":1,"verdict":"failed"}\n')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", run)
    result = _invoke(
        tmp_path,
        model_options=(
            "--model-upstream-url",
            "https://model.invalid/anthropic",
            "--model-credential-env",
            "DEEPSEEK_API_KEY",
        ),
    )
    assert result == {"schema_version": 1, "verdict": "failed"}
    assert calls[0][:3] == [sys.executable, "-m", "axrun.cli"]
    assert calls[0][-2:] == ["resume", "episode"]
    assert os.environ["DEEPSEEK_API_KEY"] == "never-log-actual-credential"
    assert not capsys.readouterr().out
    for path in (tmp_path / "private-logs").iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_helper_failure_is_safe_and_does_not_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    calls: list[list[str]] = []

    def run(arguments: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(arguments)
        kwargs["stderr"].write(b"private-provider-response-must-not-echo")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(arguments, 1, output=b"private-error")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(helper.subprocess, "run", run)
    with pytest.raises(helper.CliValidationError) as raised:
        _invoke(tmp_path)
    assert str(raised.value) == (
        "formal_cli_command_failed" if failure == "exit" else "formal_cli_process_failed"
    )
    assert len(calls) == 1
    assert "private" not in str(raised.value)
    assert not capsys.readouterr().out


@pytest.mark.parametrize("payload", [b"[]", b'{"key":1,"key":2}', b'{"key":NaN}', b"invalid"])
def test_helper_success_requires_one_valid_bounded_json_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    def run(_arguments: list[str], **kwargs: Any) -> SimpleNamespace:
        kwargs["stdout"].write(payload)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", run)
    with pytest.raises(helper.CliValidationError, match="formal_cli_output"):
        _invoke(tmp_path)


def test_helper_never_overwrites_existing_private_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(_arguments: list[str], **kwargs: Any) -> SimpleNamespace:
        kwargs["stdout"].write(b'{"accepted":true}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", run)
    _invoke(tmp_path)
    original = (tmp_path / "private-logs/resume.stdout.json").read_bytes()
    with pytest.raises(helper.CliValidationError, match="formal_cli_process_failed"):
        _invoke(tmp_path)
    assert (tmp_path / "private-logs/resume.stdout.json").read_bytes() == original
