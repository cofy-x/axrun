"""Narrow public-SDK adapters for Environment preparation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from axrun.errors import InfrastructureError, SdkCapabilityError
from axrun.preparation.models import SeedBuildSpec


@dataclass(frozen=True, slots=True)
class KovaVersion:
    version: str
    api_version: str


@dataclass(frozen=True, slots=True)
class KovaBuild:
    build_id: str
    status: str
    source_uri: str
    source_digest: str
    idempotency_key: str
    created_at: str
    updated_at: str
    failure_code: str = ""
    failure_summary: str = ""


@dataclass(frozen=True, slots=True)
class KovaOutput:
    image: str
    manifest_digest: str
    immutable_ref: str
    platform: str
    format: str


@dataclass(frozen=True, slots=True)
class KovaResults:
    build_id: str
    source_uri: str
    source_digest: str
    idempotency_key: str
    outputs: tuple[KovaOutput, ...]


@dataclass(frozen=True, slots=True)
class EnvironmentFacts:
    environment_id: str
    namespace: str
    requested_image: str
    resolved_manifest_digest: str
    labels: dict[str, str]


class PreparationRemoteError(InfrastructureError):
    def __init__(
        self,
        *,
        operation: str,
        code: str,
        summary: str,
        status: int = 0,
        retryable: bool = False,
        ambiguous: bool = False,
    ) -> None:
        self.operation = operation
        self.code = code
        self.summary = summary[:512]
        self.status = status
        self.retryable = retryable
        self.ambiguous = ambiguous
        super().__init__(f"{operation} failed: {code}")


class KovaPreparationClient(Protocol):
    def version(self) -> KovaVersion: ...

    def create_build(self, spec: SeedBuildSpec) -> KovaBuild: ...

    def get_build(self, build_id: str) -> KovaBuild: ...

    def wait_build(self, build_id: str, *, timeout: float) -> KovaBuild: ...

    def get_results(self, build_id: str) -> KovaResults: ...


class EnvironmentPreparationClient(Protocol):
    def find_by_request_digest(
        self, namespace: str, request_digest: str
    ) -> tuple[EnvironmentFacts, ...]: ...

    def create_environment(
        self, *, namespace: str, image: str, labels: dict[str, str]
    ) -> EnvironmentFacts: ...

    def get_environment(self, environment_id: str) -> EnvironmentFacts: ...


class KovaSdkPreparationClient:
    """Translate the released kova-client package into Axrun-owned facts."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> KovaSdkPreparationClient:
        try:
            from kova_client import ClientConfig, KovaClient
        except ImportError as exc:
            raise SdkCapabilityError(
                "Kova preparation requires the 'kova' extra: uv sync --extra kova"
            ) from exc
        return cls(KovaClient(ClientConfig.from_env()))

    def close(self) -> None:
        self._client.close()

    def version(self) -> KovaVersion:
        try:
            value = self._client.version()
            if value.api_version != "v1":
                raise PreparationRemoteError(
                    operation="kova_version",
                    code="incompatible_api",
                    summary="Kova Service API is not v1",
                )
            self._client.ready()
            return KovaVersion(value.version, value.api_version)
        except PreparationRemoteError:
            raise
        except Exception as exc:
            raise _kova_error("kova_version", exc, ambiguous=False) from exc

    def create_build(self, spec: SeedBuildSpec) -> KovaBuild:
        try:
            from kova_client import BuildFormat, CreateBuildRequest, Platform, TargetSpec

            value = self._client.create_build(
                CreateBuildRequest(
                    source_uri=spec.source_uri,
                    source_digest=spec.source_digest,
                    targets=(TargetSpec(spec.destination, Platform.LINUX_AMD64),),
                    concurrency=1,
                    format=BuildFormat.OCI,
                    idempotency_key=spec.idempotency_key,
                )
            )
            return _build(value)
        except Exception as exc:
            raise _kova_error("create_build", exc, ambiguous=True) from exc

    def get_build(self, build_id: str) -> KovaBuild:
        try:
            return _build(self._client.get_build(build_id))
        except Exception as exc:
            raise _kova_error("get_build", exc, ambiguous=False) from exc

    def wait_build(self, build_id: str, *, timeout: float) -> KovaBuild:
        try:
            return _build(self._client.wait_build(build_id, timeout=timeout))
        except TimeoutError as exc:
            raise PreparationRemoteError(
                operation="wait_build",
                code="timeout",
                summary="timed out waiting for Kova build",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise _kova_error("wait_build", exc, ambiguous=False) from exc

    def get_results(self, build_id: str) -> KovaResults:
        try:
            value = self._client.get_results(build_id)
            return KovaResults(
                build_id=value.id,
                source_uri=value.source_uri,
                source_digest=value.source_digest,
                idempotency_key=value.idempotency_key or "",
                outputs=tuple(
                    KovaOutput(
                        image=item.image,
                        manifest_digest=item.manifest_digest,
                        immutable_ref=item.immutable_ref,
                        platform=item.platform.value,
                        format=item.format.value,
                    )
                    for item in value.outputs
                ),
            )
        except Exception as exc:
            raise _kova_error("get_results", exc, ambiguous=False) from exc


class AxernEnvironmentPreparationClient:
    """Use only Axern's public Environment create/get/list contract."""

    _LABEL = "axrun.preparation-digest"

    def __init__(self, client: Any) -> None:
        self._client = client

    def find_by_request_digest(
        self, namespace: str, request_digest: str
    ) -> tuple[EnvironmentFacts, ...]:
        try:
            response = self._client.list_environments(
                namespace=namespace, labels={self._LABEL: request_digest}
            )
            return tuple(_environment(value) for value in response.environments)
        except Exception as exc:
            raise PreparationRemoteError(
                operation="list_environments",
                code="axern_api_error",
                summary=type(exc).__name__,
            ) from exc

    def create_environment(
        self, *, namespace: str, image: str, labels: dict[str, str]
    ) -> EnvironmentFacts:
        try:
            return _environment(
                self._client.create_environment(
                    namespace=namespace,
                    image_ref=image,
                    labels=labels,
                )
            )
        except Exception as exc:
            raise PreparationRemoteError(
                operation="create_environment",
                code="axern_api_error",
                summary=type(exc).__name__,
                ambiguous=True,
            ) from exc

    def get_environment(self, environment_id: str) -> EnvironmentFacts:
        try:
            return _environment(self._client.get_environment(environment_id))
        except Exception as exc:
            raise PreparationRemoteError(
                operation="get_environment",
                code="axern_api_error",
                summary=type(exc).__name__,
            ) from exc


def _build(value: Any) -> KovaBuild:
    updated = value.finished_at or value.started_at or value.created_at
    return KovaBuild(
        build_id=value.id,
        status=value.status.value,
        source_uri=value.source_uri or "",
        source_digest=value.source_digest or "",
        idempotency_key=value.idempotency_key or "",
        created_at=value.created_at.isoformat(),
        updated_at=updated.isoformat(),
        failure_code=value.failure_code.value if value.failure_code else "",
        failure_summary="Kova build reported terminal failure" if value.error else "",
    )


def _environment(value: Any) -> EnvironmentFacts:
    return EnvironmentFacts(
        environment_id=value.id,
        namespace=value.namespace,
        requested_image=value.spec.image.ref,
        resolved_manifest_digest=value.resolved_spec.image_descriptor.digest,
        labels=dict(value.labels),
    )


def _kova_error(operation: str, exc: Exception, *, ambiguous: bool) -> PreparationRemoteError:
    try:
        from kova_client import KovaAPIError
    except ImportError:
        KovaAPIError = ()  # type: ignore[assignment,misc]
    if isinstance(exc, KovaAPIError):
        return PreparationRemoteError(
            operation=operation,
            code=exc.code,
            summary="Kova Service returned a typed API error",
            status=exc.status_code,
            retryable=exc.retryable,
            ambiguous=ambiguous and exc.retryable,
        )
    return PreparationRemoteError(
        operation=operation,
        code="kova_transport_error",
        summary=type(exc).__name__,
        retryable=True,
        ambiguous=ambiguous,
    )
