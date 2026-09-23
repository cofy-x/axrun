from __future__ import annotations

import builtins
import json
from dataclasses import asdict, fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from axrun import cli
from axrun.errors import ContractError, InfrastructureError, SdkCapabilityError
from axrun.models import EnvironmentBinding, ResolvedEpisode
from axrun.preparation.adapters import (
    EnvironmentFacts,
    KovaBuild,
    KovaOutput,
    KovaPreparationClient,
    KovaResults,
    KovaSdkPreparationClient,
    KovaVersion,
    PreparationRemoteError,
)
from axrun.preparation.models import PreparationState, SeedBuildSpec
from axrun.preparation.service import EnvironmentPreparationService
from axrun.preparation.store import PreparationStore, seed_build_spec_from_dict

SOURCE_DIGEST = f"sha256:{'a' * 64}"
SOURCE_MANIFEST_DIGEST = f"sha256:{'d' * 64}"
RECIPE_DIGEST = f"sha256:{'b' * 64}"
MANIFEST_DIGEST = f"sha256:{'c' * 64}"
SOURCE_URI = f"oci://registry.invalid/seed-source@{SOURCE_MANIFEST_DIGEST}"
DESTINATION = "registry.invalid/axrun/seed:qualification"
IMMUTABLE_REF = f"registry.invalid/axrun/seed@{MANIFEST_DIGEST}"


def spec(**changes: Any) -> SeedBuildSpec:
    value: dict[str, Any] = {
        "schema_version": 1,
        "preparation_id": "prep-1",
        "source_uri": SOURCE_URI,
        "source_digest": SOURCE_DIGEST,
        "recipe_digest": RECIPE_DIGEST,
        "destination": DESTINATION,
        "target_role": "task",
        "platform": "linux/amd64",
        "format": "oci",
        "idempotency_key": "axrun-prep-1",
        "environment_namespace": "default",
        "working_directory": "/workspace",
        "labels": {},
    }
    value.update(changes)
    return SeedBuildSpec(**value)


def build(*, status: str = "succeeded") -> KovaBuild:
    return KovaBuild(
        build_id="build-1",
        status=status,
        source_uri=SOURCE_URI,
        source_digest=SOURCE_DIGEST,
        idempotency_key="axrun-prep-1",
        created_at="2026-09-21T00:00:00+00:00",
        updated_at="2026-09-21T00:01:00+00:00",
        failure_code="build_failed" if status == "failed" else "",
        failure_summary="build failed safely" if status == "failed" else "",
    )


def results(*, outputs: tuple[KovaOutput, ...] | None = None) -> KovaResults:
    return KovaResults(
        build_id="build-1",
        source_uri=SOURCE_URI,
        source_digest=SOURCE_DIGEST,
        idempotency_key="axrun-prep-1",
        outputs=(
            KovaOutput(
                image=DESTINATION,
                manifest_digest=MANIFEST_DIGEST,
                immutable_ref=IMMUTABLE_REF,
                platform="linux/amd64",
                format="oci",
            ),
        )
        if outputs is None
        else outputs,
    )


def environment(
    request_digest: str,
    *,
    environment_id: str = "env-1",
    requested_image: str = IMMUTABLE_REF,
    resolved_manifest_digest: str = MANIFEST_DIGEST,
    platform: str = "linux-amd64",
) -> EnvironmentFacts:
    return EnvironmentFacts(
        environment_id=environment_id,
        namespace="default",
        requested_image=requested_image,
        resolved_manifest_digest=resolved_manifest_digest,
        labels={
            "axrun.preparation-digest": request_digest,
            "axrun.preparation-platform": platform,
            "axrun.managed": "true",
        },
    )


class FakeKova(KovaPreparationClient):
    def __init__(self, store: PreparationStore, request: SeedBuildSpec) -> None:
        self.store = store
        self.request = request
        self.create_calls = 0
        self.get_calls = 0
        self.wait_calls = 0
        self.result = results()
        self.terminal = build()
        self.create_error: PreparationRemoteError | None = None
        self.get_error: PreparationRemoteError | None = None

    def version(self) -> KovaVersion:
        return KovaVersion("0.1.0-rc.9", "v1")

    def create_build(self, spec: SeedBuildSpec) -> KovaBuild:
        self.create_calls += 1
        assert spec == self.request
        persisted = self.store.load_record(spec.preparation_id)
        assert persisted is not None
        assert persisted.state in {
            PreparationState.BUILD_SUBMITTING,
            PreparationState.AMBIGUOUS,
        }
        assert self.store.spec_path(spec.preparation_id).exists()
        if self.create_error is not None:
            error, self.create_error = self.create_error, None
            raise error
        return replace(build(), status="queued")

    def get_build(self, build_id: str) -> KovaBuild:
        self.get_calls += 1
        assert build_id == "build-1"
        if self.get_error is not None:
            error, self.get_error = self.get_error, None
            raise error
        return self.terminal

    def wait_build(self, build_id: str, *, timeout: float) -> KovaBuild:
        self.wait_calls += 1
        assert build_id == "build-1"
        assert timeout > 0
        return self.terminal

    def get_results(self, build_id: str) -> KovaResults:
        assert build_id == "build-1"
        return self.result


class FakeAxern:
    def __init__(self, request: SeedBuildSpec) -> None:
        self.request = request
        self.matches: list[EnvironmentFacts] = []
        self.create_calls = 0
        self.create_error: PreparationRemoteError | None = None

    def find_by_request_digest(
        self, namespace: str, request_digest: str
    ) -> tuple[EnvironmentFacts, ...]:
        assert namespace == "default"
        assert request_digest == self.request.request_digest
        return tuple(self.matches)

    def create_environment(
        self, *, namespace: str, image: str, labels: dict[str, str]
    ) -> EnvironmentFacts:
        self.create_calls += 1
        assert namespace == "default"
        assert image == IMMUTABLE_REF
        value = EnvironmentFacts("env-1", namespace, image, MANIFEST_DIGEST, dict(labels))
        if self.create_error is not None:
            self.matches.append(value)
            error, self.create_error = self.create_error, None
            raise error
        self.matches.append(value)
        return value

    def get_environment(self, environment_id: str) -> EnvironmentFacts:
        return next(item for item in self.matches if item.environment_id == environment_id)


def service(
    tmp_path: Path,
) -> tuple[EnvironmentPreparationService, PreparationStore, FakeKova, FakeAxern, SeedBuildSpec]:
    request = spec()
    store = PreparationStore(tmp_path)
    kova = FakeKova(store, request)
    axern = FakeAxern(request)
    return (
        EnvironmentPreparationService(store=store, kova=kova, axern=axern),
        store,
        kova,
        axern,
        request,
    )


def test_request_digest_is_canonical_and_commits_the_complete_spec() -> None:
    first = spec(labels={"z": "last", "a": "first"})
    second = spec(labels={"a": "first", "z": "last"})
    changed = spec(labels={"a": "different", "z": "last"})

    assert first.request_digest == second.request_digest
    assert first.request_digest != changed.request_digest


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"source_uri": "oci://registry.invalid/source:mutable"}, "digest-pinned OCI URI"),
        ({"platform": "linux/arm64"}, "only linux/amd64"),
        ({"format": "nydus"}, "only OCI"),
        ({"destination": "https://registry.invalid/image:tag"}, "mutable OCI target"),
        ({"destination": f"registry.invalid/image@{MANIFEST_DIGEST}"}, "mutable OCI target"),
    ],
)
def test_spec_validation_fails_closed(change: dict[str, str], message: str) -> None:
    with pytest.raises(ContractError, match=message):
        spec(**change)


def test_strict_json_shape_rejects_unknown_fields() -> None:
    raw = asdict(spec())
    raw["endpoint"] = "https://must-not-persist.invalid"
    with pytest.raises(ContractError, match="invalid shape"):
        seed_build_spec_from_dict(raw)


def test_full_flow_persists_before_mutation_and_returns_existing_binding(tmp_path: Path) -> None:
    runner, store, kova, axern, request = service(tmp_path)

    receipt = runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)

    assert record is not None and record.state == PreparationState.READY
    assert kova.create_calls == 1
    assert axern.create_calls == 1
    assert receipt.requested_image == IMMUTABLE_REF
    assert receipt.resolved_manifest_digest == MANIFEST_DIGEST
    assert receipt.environment_binding() == EnvironmentBinding(
        "env-1", IMMUTABLE_REF, "linux/amd64", "/workspace"
    )
    assert Path(record.seed_build_receipt).parent.parent.name == request.preparation_id
    assert runner.prepare(request, wait_timeout=1) == receipt
    assert kova.create_calls == 1
    assert axern.create_calls == 1


def test_ambiguous_build_submission_reuses_identical_request_and_key(tmp_path: Path) -> None:
    runner, store, kova, _axern, request = service(tmp_path)
    kova.create_error = PreparationRemoteError(
        operation="create_build",
        code="kova_transport_error",
        summary="transport ended without a response",
        retryable=True,
        ambiguous=True,
    )

    with pytest.raises(PreparationRemoteError):
        runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)
    assert record is not None
    assert record.state == PreparationState.AMBIGUOUS
    assert record.ambiguous_operation == "create_build"

    receipt = runner.resume(request.preparation_id, wait_timeout=1)
    assert receipt.state == PreparationState.READY
    assert kova.create_calls == 2
    assert store.load_spec(request.preparation_id).idempotency_key == request.idempotency_key


def test_build_id_is_persisted_and_observation_resume_does_not_resubmit(tmp_path: Path) -> None:
    runner, store, kova, _axern, request = service(tmp_path)
    kova.get_error = PreparationRemoteError(
        operation="get_build",
        code="kova_transport_error",
        summary="safe transport failure",
        retryable=True,
    )

    with pytest.raises(PreparationRemoteError):
        runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)
    assert record is not None
    assert record.state == PreparationState.BUILD_SUBMITTED
    assert record.kova_build_id == "build-1"

    runner.resume(request.preparation_id, wait_timeout=1)
    assert kova.create_calls == 1


def test_partial_kova_results_fail_closed(tmp_path: Path) -> None:
    runner, store, kova, _axern, request = service(tmp_path)
    kova.result = results(outputs=())

    with pytest.raises(ContractError, match="exactly one output"):
        runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)
    assert record is not None
    assert record.state == PreparationState.FAILED
    assert record.diagnostic_code == "invalid_kova_results"


def test_credential_bearing_immutable_reference_fails_closed(tmp_path: Path) -> None:
    runner, store, kova, _axern, request = service(tmp_path)
    kova.result = results(
        outputs=(
            KovaOutput(
                image=DESTINATION,
                manifest_digest=MANIFEST_DIGEST,
                immutable_ref=f"user:password@registry.invalid/axrun/seed@{MANIFEST_DIGEST}",
                platform="linux/amd64",
                format="oci",
            ),
        )
    )

    with pytest.raises(ContractError, match="immutable image reference"):
        runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)
    assert record is not None and record.state == PreparationState.FAILED


def test_terminal_kova_failure_is_durable_and_never_creates_environment(tmp_path: Path) -> None:
    runner, store, kova, axern, request = service(tmp_path)
    kova.terminal = build(status="failed")

    with pytest.raises(InfrastructureError, match="status failed"):
        runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)
    assert record is not None and record.state == PreparationState.FAILED
    assert record.seed_build_receipt_digest
    assert axern.create_calls == 0


def test_exact_environment_is_reused(tmp_path: Path) -> None:
    runner, _store, _kova, axern, request = service(tmp_path)
    axern.matches.append(environment(request.request_digest))

    receipt = runner.prepare(request, wait_timeout=1)

    assert receipt.environment_id == "env-1"
    assert axern.create_calls == 0


def test_ambiguous_environment_creation_recovers_by_exact_label(tmp_path: Path) -> None:
    runner, store, _kova, axern, request = service(tmp_path)
    axern.create_error = PreparationRemoteError(
        operation="create_environment",
        code="axern_api_error",
        summary="request outcome unknown",
        retryable=True,
        ambiguous=True,
    )

    with pytest.raises(PreparationRemoteError):
        runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)
    assert record is not None and record.state == PreparationState.AMBIGUOUS

    receipt = runner.resume(request.preparation_id, wait_timeout=1)
    assert receipt.environment_id == "env-1"
    assert axern.create_calls == 1


def test_multiple_environment_matches_are_rejected(tmp_path: Path) -> None:
    runner, store, _kova, axern, request = service(tmp_path)
    axern.matches.extend(
        [
            environment(request.request_digest, environment_id="env-1"),
            environment(request.request_digest, environment_id="env-2"),
        ]
    )

    with pytest.raises(InfrastructureError, match="multiple Axern Environments"):
        runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)
    assert record is not None and record.state == PreparationState.FAILED


@pytest.mark.parametrize(
    "facts",
    [
        environment("placeholder", requested_image=f"registry.invalid/other@{MANIFEST_DIGEST}"),
        environment("placeholder", resolved_manifest_digest=f"sha256:{'d' * 64}"),
        environment("placeholder", platform="linux-arm64"),
    ],
)
def test_environment_identity_mismatches_fail_closed(
    tmp_path: Path, facts: EnvironmentFacts
) -> None:
    runner, store, _kova, axern, request = service(tmp_path)
    axern.matches.append(
        replace(
            facts,
            labels={
                **facts.labels,
                "axrun.preparation-digest": request.request_digest,
            },
        )
    )

    with pytest.raises(ContractError):
        runner.prepare(request, wait_timeout=1)
    record = store.load_record(request.preparation_id)
    assert record is not None
    assert record.state == PreparationState.FAILED
    assert record.diagnostic_code == "environment_mismatch"


def test_typed_kova_error_message_is_not_persistable() -> None:
    from kova_client import KovaAPIError

    canary = "super-secret-canary"

    class RawClient:
        def version(self):
            raise KovaAPIError(
                status_code=401,
                code="unauthorized",
                message=canary,
                retryable=False,
            )

    with pytest.raises(PreparationRemoteError) as raised:
        KovaSdkPreparationClient(RawClient()).version()
    assert canary not in raised.value.summary
    assert canary not in str(raised.value)
    assert raised.value.status == 401


def test_preparation_fields_do_not_enter_resolved_episode_contract() -> None:
    names = {item.name for item in fields(ResolvedEpisode)}
    assert "preparation" not in names
    assert "kova_build_id" not in names
    assert "source_uri" not in names


def test_cli_commands_are_explicit_and_status_is_local() -> None:
    parser = cli._parser()  # pyright: ignore[reportPrivateUsage]
    prepare = parser.parse_args(
        ["prepare-kova-environment", "spec.json", "--output", "preparation.json"]
    )
    resume = parser.parse_args(["preparation-resume", "prep-1"])
    status = parser.parse_args(["preparation-status", "prep-1"])
    binding = parser.parse_args(["preparation-binding", "prep-1"])

    assert prepare.command == "prepare-kova-environment"
    assert resume.command == "preparation-resume"
    assert status.command == "preparation-status"
    assert binding.command == "preparation-binding"


def test_missing_kova_extra_has_clean_cli_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "spec.json"
    request_path.write_text(json.dumps(asdict(spec())), encoding="utf-8")
    real_import = builtins.__import__

    def missing_kova(name: str, *args: Any, **kwargs: Any):
        if name == "kova_client":
            raise ImportError("missing optional dependency")
        return real_import(name, *args, **kwargs)

    fake_axern = SimpleNamespace(close=lambda: None)

    def client(_args: Any) -> Any:
        return fake_axern

    monkeypatch.setattr(cli, "_client", client)
    monkeypatch.setattr(builtins, "__import__", missing_kova)

    code = cli.main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "prepare-kova-environment",
            str(request_path),
            "--output",
            str(tmp_path / "receipt.json"),
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "requires the 'kova' extra" in captured.err
    assert "Traceback" not in captured.err


def test_optional_kova_import_error_is_an_axrun_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def missing_kova(name: str, *args: Any, **kwargs: Any):
        if name == "kova_client":
            raise ImportError
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_kova)
    with pytest.raises(SdkCapabilityError, match="uv sync --extra kova"):
        KovaSdkPreparationClient.from_env()
