"""Language-neutral contracts for explicit Kova-backed Environment preparation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit

from axrun.errors import ContractError
from axrun.models import EnvironmentBinding, canonical_digest

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMMUTABLE_SOURCE = re.compile(r"^oci://[^@]+@sha256:[0-9a-f]{64}$")
_MUTABLE_TARGET = re.compile(
    r"^[a-zA-Z0-9.-]+(?::[0-9]+)?/[a-z0-9]+(?:[._/-][a-z0-9]+)*(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?$"
)
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
_ROLE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SENSITIVE = ("auth", "credential", "password", "secret", "token")


class PreparationState(StrEnum):
    NEW = "new"
    BUILD_SUBMITTING = "build_submitting"
    BUILD_SUBMITTED = "build_submitted"
    BUILD_SUCCEEDED = "build_succeeded"
    ENVIRONMENT_CREATING = "environment_creating"
    ENVIRONMENT_CREATED = "environment_created"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SeedBuildSpec:
    schema_version: int
    preparation_id: str
    source_uri: str
    source_digest: str
    recipe_digest: str
    destination: str
    target_role: str
    platform: str
    format: str
    idempotency_key: str
    environment_namespace: str
    working_directory: str
    labels: dict[str, str] = field(default_factory=dict[str, str])

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ContractError("SeedBuildSpec schema_version must be 1")
        if not _ID.fullmatch(self.preparation_id):
            raise ContractError("preparation_id is invalid")
        if not _IMMUTABLE_SOURCE.fullmatch(self.source_uri):
            raise ContractError("source_uri must be a digest-pinned OCI URI")
        parsed = urlsplit(self.source_uri)
        if parsed.username or parsed.password or not parsed.hostname:
            raise ContractError("source_uri must not contain credentials")
        _require_digest(self.source_digest, "source_digest")
        if not self.source_uri.endswith("@" + self.source_digest):
            raise ContractError("source_uri digest must equal source_digest")
        _require_digest(self.recipe_digest, "recipe_digest")
        if not _MUTABLE_TARGET.fullmatch(self.destination):
            raise ContractError("destination must be one credential-free mutable OCI target")
        if not _ROLE.fullmatch(self.target_role):
            raise ContractError("target_role is invalid")
        if self.platform != "linux/amd64":
            raise ContractError("SeedBuildSpec v1 supports only linux/amd64")
        if self.format != "oci":
            raise ContractError("SeedBuildSpec v1 supports only OCI output")
        if not _ID.fullmatch(self.idempotency_key):
            raise ContractError("idempotency_key is invalid")
        if not _ID.fullmatch(self.environment_namespace):
            raise ContractError("environment_namespace is invalid")
        if not self.working_directory.startswith("/"):
            raise ContractError("working_directory must be absolute")
        if len(self.labels) > 16:
            raise ContractError("at most 16 preparation labels are allowed")
        for key, value in self.labels.items():
            if not _ROLE.fullmatch(key) or not value or len(value) > 128:
                raise ContractError("preparation labels must be bounded non-empty strings")
            if any(part in key.lower() for part in _SENSITIVE):
                raise ContractError("preparation labels must not name sensitive values")

    @property
    def request_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class SeedBuildReceipt:
    schema_version: int
    request_digest: str
    source_uri: str
    source_digest: str
    recipe_digest: str
    target_role: str
    destination: str
    platform: str
    format: str
    idempotency_key: str
    kova_build_id: str
    kova_version: str
    kova_api_version: str
    terminal_status: str
    manifest_digest: str
    immutable_ref: str
    created_at: str
    updated_at: str
    failure_code: str = ""
    failure_summary: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ContractError("SeedBuildReceipt schema_version must be 1")
        _require_digest(self.request_digest, "request_digest", prefix=False)
        if self.terminal_status == "succeeded":
            _require_digest(self.manifest_digest, "manifest_digest")
            _require_immutable_ref(self.immutable_ref, self.manifest_digest)
        elif self.manifest_digest or self.immutable_ref:
            raise ContractError("non-successful build receipt cannot publish an image")

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class EnvironmentPreparationReceipt:
    schema_version: int
    preparation_id: str
    request_digest: str
    seed_build_receipt_digest: str
    environment_id: str
    requested_image: str
    resolved_manifest_digest: str
    platform: str
    working_directory: str
    state: str
    created_at: str
    updated_at: str
    diagnosis_code: str = ""
    diagnosis_summary: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ContractError("EnvironmentPreparationReceipt schema_version must be 1")
        for name, value in (
            ("request_digest", self.request_digest),
            ("seed_build_receipt_digest", self.seed_build_receipt_digest),
        ):
            _require_digest(value, name, prefix=False)
        _require_digest(self.resolved_manifest_digest, "resolved_manifest_digest")
        _require_immutable_ref(self.requested_image, self.resolved_manifest_digest)
        if self.state != PreparationState.READY:
            raise ContractError("EnvironmentPreparationReceipt must be ready")

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))

    def environment_binding(self) -> EnvironmentBinding:
        return EnvironmentBinding(
            environment_id=self.environment_id,
            image=self.requested_image,
            platform=self.platform,
            working_directory=self.working_directory,
        )


@dataclass(slots=True)
class PreparationRecord:
    schema_version: int
    preparation_id: str
    request_digest: str
    state: PreparationState
    created_at: str
    updated_at: str
    kova_build_id: str = ""
    kova_version: str = ""
    kova_api_version: str = ""
    seed_build_receipt: str = ""
    seed_build_receipt_digest: str = ""
    environment_id: str = ""
    preparation_receipt: str = ""
    preparation_receipt_digest: str = ""
    ambiguous_operation: str = ""
    diagnostic_code: str = ""
    diagnostic_summary: str = ""
    remote_status: int = 0
    remote_retryable: bool = False


def _require_digest(value: str, name: str, *, prefix: bool = True) -> None:
    valid = bool(_DIGEST.fullmatch(value)) if prefix else bool(re.fullmatch(r"[0-9a-f]{64}", value))
    if not valid:
        kind = "sha256:<hex>" if prefix else "lowercase SHA-256 hexadecimal"
        raise ContractError(f"{name} must be {kind}")


def _require_immutable_ref(value: str, digest: str) -> None:
    if value.count("@") != 1 or "://" in value or not value.endswith("@" + digest):
        raise ContractError("immutable image reference must contain the returned manifest digest")
    name, _separator, _digest = value.rpartition("@")
    if not _MUTABLE_TARGET.fullmatch(name):
        raise ContractError("immutable image reference must be a credential-free OCI reference")
