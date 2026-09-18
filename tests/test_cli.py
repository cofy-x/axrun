from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pytest import MonkeyPatch

from axrun import cli
from axrun.errors import ContractError
from axrun.models import HarnessSpec


def test_model_credential_is_read_from_selected_caller_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "caller-only-secret")
    args = SimpleNamespace(
        model_upstream_url="https://api.deepseek.com/anthropic",
        model_credential_env="DEEPSEEK_API_KEY",
    )
    episode = SimpleNamespace(
        harness=HarnessSpec(identity="claude-code", version="2.1.205", config={})
    )

    lifecycle = cli._model_lifecycle(  # pyright: ignore[reportPrivateUsage]
        cast(Namespace, args), object(), cast(Any, episode)
    )

    assert lifecycle is not None
    proxy = vars(lifecycle)["_proxy"]
    assert vars(proxy)["_credential"] == "caller-only-secret"


def test_missing_selected_model_credential_names_variable_not_value(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    args = SimpleNamespace(
        model_upstream_url="https://api.deepseek.com/anthropic",
        model_credential_env="DEEPSEEK_API_KEY",
    )
    episode = SimpleNamespace(
        harness=HarnessSpec(identity="claude-code", version="2.1.205", config={})
    )

    with pytest.raises(ContractError, match="credential in DEEPSEEK_API_KEY"):
        cli._model_lifecycle(  # pyright: ignore[reportPrivateUsage]
            cast(Namespace, args), object(), cast(Any, episode)
        )


def test_model_credential_environment_option_defaults_to_axrun_name() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        ["validate", "episode.json"]
    )

    assert args.model_credential_env == "AXRUN_MODEL_CREDENTIAL"
