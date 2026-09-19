from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pytest import MonkeyPatch

from axrun import cli
from axrun.errors import ContractError
from axrun.models import HarnessRuntimeRequirements, HarnessSpec
from axrun.store import EpisodeStore


def test_model_credential_is_read_from_selected_caller_environment(
    monkeypatch: MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "caller-only-secret")
    args = SimpleNamespace(
        model_upstream_url="https://api.deepseek.com/anthropic",
        model_credential_env="DEEPSEEK_API_KEY",
        model_connect_timeout_seconds=10.0,
        model_response_timeout_seconds=300.0,
    )
    episode = SimpleNamespace(
        episode_id="episode",
        harness=HarnessSpec(
            identity="claude-code", version="2.1.205", config={"model": "opaque-model"}
        ),
    )

    lifecycle = cli._model_lifecycle(  # pyright: ignore[reportPrivateUsage]
        cast(Namespace, args),
        object(),
        cast(Any, episode),
        EpisodeStore(tmp_path),
        HarnessRuntimeRequirements(
            model_protocol="anthropic-compatible", requires_model_tunnel=True
        ),
    )

    assert lifecycle is not None
    tunnel = vars(lifecycle)["_lifecycles"][0]
    proxy = vars(tunnel)["_proxy"]
    assert vars(proxy)["_credential"] == "caller-only-secret"


def test_missing_selected_model_credential_names_variable_not_value(
    monkeypatch: MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    args = SimpleNamespace(
        model_upstream_url="https://api.deepseek.com/anthropic",
        model_credential_env="DEEPSEEK_API_KEY",
        model_connect_timeout_seconds=10.0,
        model_response_timeout_seconds=300.0,
    )
    episode = SimpleNamespace(
        episode_id="episode",
        harness=HarnessSpec(
            identity="claude-code", version="2.1.205", config={"model": "opaque-model"}
        ),
    )

    with pytest.raises(ContractError, match="credential in DEEPSEEK_API_KEY"):
        cli._model_lifecycle(  # pyright: ignore[reportPrivateUsage]
            cast(Namespace, args),
            object(),
            cast(Any, episode),
            EpisodeStore(tmp_path),
            HarnessRuntimeRequirements(
                model_protocol="anthropic-compatible", requires_model_tunnel=True
            ),
        )


def test_model_credential_environment_option_defaults_to_axrun_name() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        ["validate", "episode.json"]
    )

    assert args.model_credential_env == "AXRUN_MODEL_CREDENTIAL"
    assert args.model_connect_timeout_seconds == 10.0
    assert args.model_response_timeout_seconds == 300.0


def test_resume_is_an_explicit_recovery_command() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        ["resume", "episode-id", "--timeout", "12"]
    )

    assert args.command == "resume"
    assert args.episode_id == "episode-id"
    assert args.timeout == 12.0


def test_report_commands_are_local_and_explicit() -> None:
    verify = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        ["verify-record", "episode-id"]
    )
    report = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        ["report", "episode-id", "--format", "markdown", "--output", "report.md"]
    )

    assert verify.command == "verify-record"
    assert report.command == "report"
    assert report.format == "markdown"


def test_qualification_accepts_a_resolved_episode_file() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        ["qualify", "episode.json"]
    )

    assert args.command == "qualify"
    assert str(args.episode) == "episode.json"


def test_programbench_compatibility_resolver_is_explicit() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        [
            "resolve-programbench-compatibility",
            "row.json",
            "--episode-id",
            "pb",
            "--candidate-variant",
            "known-bad",
            "--inference-image",
            f"example.invalid/inference@sha256:{'a' * 64}",
            "--verification-image",
            f"example.invalid/verification@sha256:{'b' * 64}",
            "--task-platform",
            "linux/amd64",
            "--inference-environment",
            "env-i",
            "--verification-environment",
            "env-v",
            "--output",
            "episode.json",
        ]
    )

    assert args.command == "resolve-programbench-compatibility"
    assert args.candidate_variant == "known-bad"


def test_programbench_official_stage_zero_resolver_is_explicit() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        [
            "resolve-programbench-official",
            "row.json",
            "--episode-id",
            "pb-official",
            "--inference-environment",
            "env-i",
            "--verification-environment",
            "env-v",
            "--output",
            "episode.json",
        ]
    )

    assert args.command == "resolve-programbench-official"
    assert args.harness == "static-candidate"
