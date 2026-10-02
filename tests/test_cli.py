from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pytest import MonkeyPatch

from axrun import cli, cli_resolve
from axrun.errors import ContractError, DiagnosedInfrastructureError, SdkCapabilityError
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


@pytest.mark.parametrize(
    "error", [ContractError, OSError, SdkCapabilityError, ValueError, RuntimeError]
)
def test_cli_does_not_print_untrusted_exception_text(
    error: type[Exception], monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "sentinel-secret-in-exception"

    def fail(_path: Path) -> Any:
        raise error(secret)

    monkeypatch.setattr(cli, "_episode", fail)
    assert cli.main(["validate", "episode.json"]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "axrun: AXRUN_" in captured.err


def test_cli_preserves_explicit_safe_diagnosis_code(
    monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_path: Path) -> Any:
        raise DiagnosedInfrastructureError("tunnel_model_preflight_failed", {"status": 401})

    monkeypatch.setattr(cli, "_episode", fail)
    assert cli.main(["validate", "episode.json"]) == 1
    assert capsys.readouterr().err.strip() == "axrun: tunnel_model_preflight_failed"


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


def test_programbench_official_resolver_requires_explicit_test_assets() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        [
            "resolve-programbench-official",
            "row.json",
            "--episode-id",
            "pb-official",
            "--test-assets-dir",
            "locked-assets",
            "--runtime-image",
            f"registry.invalid/programbench@sha256:{'a' * 64}",
            "--verification-image",
            f"registry.invalid/evaluator@sha256:{'b' * 64}",
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
    assert args.test_assets_dir == Path("locked-assets")
    assert args.runtime_image.endswith(f"@sha256:{'a' * 64}")


def test_claude_model_option_does_not_conflict_with_caller_model_options() -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        [
            "resolve-programbench-official",
            "row.json",
            "--episode-id",
            "pb-claude",
            "--model",
            "opaque-model",
            "--test-assets-dir",
            "locked-assets",
            "--runtime-image",
            f"registry.invalid/programbench@sha256:{'a' * 64}",
            "--verification-image",
            f"registry.invalid/evaluator@sha256:{'b' * 64}",
            "--inference-environment",
            "env-i",
            "--verification-environment",
            "env-v",
            "--output",
            "episode.json",
        ]
    )

    assert args.model == "opaque-model"
    assert args.model_upstream_url == ""


def _flask_resolve_arguments(tmp_path: Path) -> list[str]:
    return [
        "resolve-swebench-flask-official",
        str(tmp_path / "row.json"),
        "--episode-id",
        "flask-cli",
        "--assets-dir",
        str(tmp_path / "assets"),
        "--wheelhouse-dir",
        str(tmp_path / "wheels"),
        "--task-image",
        f"index.docker.io/swebench/flask@sha256:{'a' * 64}",
        "--image-import-receipt",
        str(tmp_path / "import.json"),
        "--admission-receipt",
        str(tmp_path / "admission.json"),
        "--inference-environment",
        "env-inference",
        "--verification-environment",
        "env-verification",
        "--output",
        str(tmp_path / "episode.json"),
    ]


def _flask_import_file(tmp_path: Path, **extra: object) -> Path:
    path = tmp_path / "import.json"
    path.write_text(
        json.dumps(
            {
                "source_ref": f"docker.io/swebench/flask@sha256:{'b' * 64}",
                "canonical_ref": f"index.docker.io/swebench/flask@sha256:{'b' * 64}",
                "immutable_ref": f"index.docker.io/swebench/flask@sha256:{'a' * 64}",
                "content_digest": f"sha256:{'a' * 64}",
                "platform": "linux/amd64",
                **extra,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_flask_resolver_requires_explicit_admission_and_fixed_platform(tmp_path: Path) -> None:
    args = cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
        _flask_resolve_arguments(tmp_path)
    )
    assert args.harness == "static-candidate"
    assert args.admission_receipt == tmp_path / "admission.json"
    assert args.image_import_receipt == tmp_path / "import.json"
    assert not hasattr(args, "task_platform")

    without_admission = _flask_resolve_arguments(tmp_path)
    index = without_admission.index("--admission-receipt")
    del without_admission[index : index + 2]
    with pytest.raises(SystemExit):
        cli._parser().parse_args(without_admission)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(SystemExit):
        cli._parser().parse_args(  # pyright: ignore[reportPrivateUsage]
            [*_flask_resolve_arguments(tmp_path), "--task-platform", "linux/arm64"]
        )


@pytest.mark.parametrize("harness", ["static-candidate", "claude-code"])
def test_flask_resolver_cli_delegates_only_to_closed_resolver(
    harness: str, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    private_row = {"problem_statement": "public prompt", "patch": "private-reference-marker"}
    (tmp_path / "row.json").write_text(json.dumps(private_row), encoding="utf-8")
    _flask_import_file(tmp_path)
    calls: list[dict[str, Any]] = []

    class Resolver:
        def resolve(self, row: dict[str, Any], **kwargs: Any) -> object:
            calls.append({"row": row, **kwargs})
            return object()

    monkeypatch.setattr(cli_resolve, "SweBenchFlaskOfficialResolver", Resolver)
    monkeypatch.setattr(cli_resolve, "_write_episode", lambda _episode, _output: None)
    monkeypatch.setattr(cli, "_client", lambda _args: pytest.fail("resolve must be caller-local"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "caller-secret-must-not-be-read-for-resolve")
    arguments = [*_flask_resolve_arguments(tmp_path), "--harness", harness]
    if harness == "static-candidate":
        arguments += ["--candidate-file", str(tmp_path / "candidate.patch")]
    else:
        arguments += [
            "--claude-mount-image",
            f"index.docker.io/axrun/claude@sha256:{'c' * 64}",
            "--model",
            "opaque-model[1m]",
            "--claude-effort-level",
            "max",
            "--claude-auto-compact-window",
            "786432",
        ]
    assert cli.main(arguments) == 0
    assert len(calls) == 1
    assert calls[0]["row"] == private_row
    assert calls[0]["admission_receipt_file"] == tmp_path / "admission.json"
    assert calls[0]["image_import_receipt"]["platform"] == "linux/amd64"
    assert calls[0]["inference_environment_id"] != calls[0]["verification_environment_id"]
    resolved_harness = calls[0]["harness"]
    assert resolved_harness.identity == harness
    if harness == "static-candidate":
        assert resolved_harness.config == {}
        assert calls[0]["static_candidate_file"] == tmp_path / "candidate.patch"
    else:
        assert resolved_harness.config["working_directory"] == "/testbed"
        assert resolved_harness.config["model"] == "opaque-model[1m]"
        assert resolved_harness.config["effort_level"] == "max"
        assert resolved_harness.config["auto_compact_window"] == 786432
        assert calls[0]["static_candidate_file"] is None
    assert "caller-secret" not in repr(calls)
    assert "private-reference-marker" not in capsys.readouterr().out


@pytest.mark.parametrize("value", [{"unknown": "value"}, {"platform": 1}])
def test_flask_import_receipt_shape_is_closed(value: dict[str, object], tmp_path: Path) -> None:
    path = _flask_import_file(tmp_path, **value)
    with pytest.raises(ContractError, match="invalid shape"):
        cli._flask_import_receipt(path)  # pyright: ignore[reportPrivateUsage]


def test_flask_admission_cli_is_model_free_and_closes_client(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import_path = _flask_import_file(tmp_path)
    calls: list[dict[str, Any]] = []
    events: list[str] = []
    client = SimpleNamespace(close=lambda: events.append("client_closed"))
    monkeypatch.setattr(cli, "_client", lambda _args: client)
    monkeypatch.setattr(cli, "_runner", lambda *_args: pytest.fail("admission is not inference"))
    monkeypatch.setattr(
        cli, "_model_lifecycle", lambda *_args: pytest.fail("admission never accesses a model")
    )

    def admit(row_path: Path, **kwargs: Any) -> dict[str, Any]:
        calls.append({"row_path": row_path, **kwargs})
        return {"schema_version": "safe-admission", "audit_run_id": "run-audit"}

    monkeypatch.setattr(cli, "admit_flask_image", admit)
    monkeypatch.chdir(tmp_path)
    assert (
        cli.main(
            [
                "--state-dir",
                "private-state",
                "admit-swebench-flask-image",
                str(tmp_path / "row.json"),
                "--environment",
                "env-audit",
                "--task-image",
                f"index.docker.io/swebench/flask@sha256:{'a' * 64}",
                "--image-import-receipt",
                str(import_path),
                "--output",
                str(tmp_path / "admission.json"),
            ]
        )
        == 0
    )
    assert calls[0]["row_path"] == tmp_path / "row.json"
    assert calls[0]["state_root"] == tmp_path / "private-state"
    assert calls[0]["environment_id"] == "env-audit"
    assert calls[0]["client"] is client
    assert calls[0]["output"] == tmp_path / "admission.json"
    assert json.loads(capsys.readouterr().out)["audit_run_id"] == "run-audit"
    assert events == ["client_closed"]


@pytest.mark.parametrize("command", ["resume", "wait"])
def test_cli_recovery_checks_admission_before_waiting_original_run(
    command: str, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[str] = []
    episode = SimpleNamespace(episode_id="flask-resume")
    client = SimpleNamespace(close=lambda: events.append("client_closed"))
    monkeypatch.setattr(cli, "_client", lambda _args: client)
    monkeypatch.setattr(EpisodeStore, "load_spec", lambda *_args: episode)
    monkeypatch.setattr(
        cli,
        "resolve_adapters",
        lambda _episode: SimpleNamespace(
            inference=object(), candidate=object(), verifier=object(), trajectory=None
        ),
    )

    def reject(_store: EpisodeStore, actual: Any) -> None:
        assert actual is episode
        events.append("admission_checked")
        raise ContractError("admission evidence is damaged")

    monkeypatch.setattr(cli, "require_admission", reject)
    monkeypatch.setattr(
        cli,
        "_runner",
        lambda *_args: SimpleNamespace(wait=lambda *_args, **_kwargs: pytest.fail("not admitted")),
    )
    assert cli.main(["--state-dir", str(tmp_path), command, "flask-resume"]) == 1
    assert events == ["admission_checked", "client_closed"]
    assert "AXRUN_CONTRACT_ERROR" in capsys.readouterr().err


def test_cli_run_checks_admission_after_qualification_before_model_start(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    events: list[str] = []
    episode = SimpleNamespace(episode_id="flask-run")
    client = SimpleNamespace(close=lambda: events.append("client_closed"))
    monkeypatch.setattr(cli, "_client", lambda _args: client)
    monkeypatch.setattr(cli, "_episode", lambda _path: episode)
    monkeypatch.setattr(
        cli,
        "resolve_adapters",
        lambda _episode: SimpleNamespace(
            inference=SimpleNamespace(plan=lambda *_args: None),
            candidate=SimpleNamespace(capture_plan=lambda *_args: None),
            verifier=object(),
            trajectory=None,
            runtime=HarnessRuntimeRequirements(),
        ),
    )
    monkeypatch.setattr(
        cli,
        "_runner",
        lambda *_args: SimpleNamespace(
            backend=object(), run=lambda *_args, **_kwargs: pytest.fail("not admitted")
        ),
    )
    monkeypatch.setattr(
        cli, "qualify_episode", lambda *_args, **_kwargs: events.append("qualified")
    )

    def reject(*_args: Any) -> None:
        events.append("admission_checked")
        raise ContractError("admission evidence is missing")

    monkeypatch.setattr(cli, "require_admission", reject)
    monkeypatch.setattr(cli, "_model_lifecycle", lambda *_args: pytest.fail("model must not start"))
    assert cli.main(["--state-dir", str(tmp_path), "run", "episode.json"]) == 1
    assert events == ["qualified", "admission_checked", "client_closed"]


@pytest.mark.parametrize("command", ["verify-record", "report"])
def test_cli_record_verification_is_local_and_uses_canonical_state_root(
    command: str, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[Path] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_client", lambda _args: pytest.fail("report must remain offline"))

    def verify(store: EpisodeStore, episode_id: str) -> dict[str, Any]:
        seen.append(store.root)
        assert episode_id == "flask-complete"
        return {"integrity_verified": True, "episode_id": episode_id}

    monkeypatch.setattr(cli, "verify_record", verify)
    assert cli.main(["--state-dir", "private-state", command, "flask-complete"]) == 0
    assert seen == [tmp_path / "private-state"]
    assert json.loads(capsys.readouterr().out)["integrity_verified"] is True


def test_cli_cancel_does_not_require_damaged_admission_to_cancel_original_run(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[str] = []
    verifier = object()
    episode = SimpleNamespace(episode_id="flask-damaged")
    client = SimpleNamespace(close=lambda: events.append("client_closed"))
    monkeypatch.setattr(cli, "_client", lambda _args: client)
    monkeypatch.setattr(EpisodeStore, "load_spec", lambda *_args: episode)
    monkeypatch.setattr(
        cli,
        "resolve_adapters",
        lambda *_args: pytest.fail("damaged admission cannot authorize run"),
    )
    monkeypatch.setattr(
        cli, "require_admission", lambda *_args: pytest.fail("cancellation needs no new admission")
    )

    def select(actual: Any) -> object:
        assert actual is episode
        events.append("verifier_selected")
        return verifier

    def cancel(episode_id: str, **kwargs: Any) -> SimpleNamespace:
        assert episode_id == "flask-damaged"
        assert kwargs["verifier"] is verifier
        events.append("original_run_cancelled")
        return SimpleNamespace(
            as_dict=lambda: {
                "episode_id": episode_id,
                "phase": "cancelled",
                "inference": {"run_id": "run-original"},
            }
        )

    monkeypatch.setattr(cli, "resolve_verifier", select)
    monkeypatch.setattr(cli, "_runner", lambda *_args: SimpleNamespace(cancel=cancel))
    assert cli.main(["--state-dir", str(tmp_path), "cancel", "flask-damaged"]) == 0
    assert events == ["verifier_selected", "original_run_cancelled", "client_closed"]
    assert json.loads(capsys.readouterr().out)["inference"]["run_id"] == "run-original"
