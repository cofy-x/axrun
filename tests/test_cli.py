from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pytest import MonkeyPatch

from axrun import cli
from axrun.errors import ContractError
from axrun.models import HarnessSpec
from axrun.store import EpisodeStore


def test_model_credential_is_read_from_selected_caller_environment(
    monkeypatch: MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "caller-only-secret")
    args = SimpleNamespace(
        model_upstream_url="https://api.deepseek.com/anthropic",
        model_credential_env="DEEPSEEK_API_KEY",
    )
    episode = SimpleNamespace(
        episode_id="episode",
        harness=HarnessSpec(
            identity="claude-code", version="2.1.205", config={"model": "opaque-model"}
        ),
    )

    lifecycle = cli._model_lifecycle(  # pyright: ignore[reportPrivateUsage]
        cast(Namespace, args), object(), cast(Any, episode), EpisodeStore(tmp_path)
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
        )


def test_model_credential_environment_option_defaults_to_axrun_name() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        ["validate", "episode.json"]
    )

    assert args.model_credential_env == "AXRUN_MODEL_CREDENTIAL"


def test_resume_is_an_explicit_recovery_command() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        ["resume", "episode-id", "--timeout", "12"]
    )

    assert args.command == "resume"
    assert args.episode_id == "episode-id"
    assert args.timeout == 12.0
