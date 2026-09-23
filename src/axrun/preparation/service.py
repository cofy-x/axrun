"""Recoverable Kova build to Axern Environment preparation state machine."""

from __future__ import annotations

from datetime import UTC, datetime

from axrun.errors import ContractError, InfrastructureError, RecoveryRequiredError
from axrun.preparation.adapters import (
    EnvironmentFacts,
    EnvironmentPreparationClient,
    KovaBuild,
    KovaPreparationClient,
    KovaResults,
    PreparationRemoteError,
)
from axrun.preparation.models import (
    EnvironmentPreparationReceipt,
    PreparationRecord,
    PreparationState,
    SeedBuildReceipt,
    SeedBuildSpec,
)
from axrun.preparation.store import PreparationStore

_TERMINAL = {"succeeded", "failed", "cancelled"}
_PREPARATION_LABEL = "axrun.preparation-digest"
_PLATFORM_LABEL = "axrun.preparation-platform"


class EnvironmentPreparationService:
    def __init__(
        self,
        *,
        store: PreparationStore,
        kova: KovaPreparationClient,
        axern: EnvironmentPreparationClient,
    ) -> None:
        self.store = store
        self.kova = kova
        self.axern = axern

    def prepare(self, spec: SeedBuildSpec, *, wait_timeout: float) -> EnvironmentPreparationReceipt:
        self.store.initialize(spec, now=_now())
        return self.resume(spec.preparation_id, wait_timeout=wait_timeout)

    def resume(self, preparation_id: str, *, wait_timeout: float) -> EnvironmentPreparationReceipt:
        if wait_timeout <= 0:
            raise ContractError("wait_timeout must be positive")
        spec = self.store.load_spec(preparation_id)
        while True:
            record = self._record(preparation_id)
            if record.request_digest != spec.request_digest:
                raise ContractError("preparation request digest mismatch")
            if record.state == PreparationState.READY:
                return self.store.load_preparation_receipt(record)
            if record.state in {PreparationState.FAILED, PreparationState.CANCELLED}:
                raise InfrastructureError(
                    f"preparation is {record.state}: {record.diagnostic_code}"
                )
            if record.state == PreparationState.NEW:
                self._mark(record, PreparationState.BUILD_SUBMITTING)
                continue
            if record.state == PreparationState.BUILD_SUBMITTING or (
                record.state == PreparationState.AMBIGUOUS
                and record.ambiguous_operation == "create_build"
            ):
                self._submit(spec, record)
                continue
            if record.state == PreparationState.BUILD_SUBMITTED:
                self._finish_build(spec, record, wait_timeout=wait_timeout)
                continue
            if record.state == PreparationState.BUILD_SUCCEEDED:
                self._resolve_environment(spec, record)
                continue
            if record.state == PreparationState.ENVIRONMENT_CREATING or (
                record.state == PreparationState.AMBIGUOUS
                and record.ambiguous_operation == "create_environment"
            ):
                self._resolve_environment(spec, record)
                continue
            if record.state == PreparationState.ENVIRONMENT_CREATED:
                self._finish_environment(spec, record)
                continue
            raise RecoveryRequiredError(f"unsupported preparation state: {record.state}")

    def _submit(self, spec: SeedBuildSpec, record: PreparationRecord) -> None:
        try:
            version = self.kova.version()
            build = self.kova.create_build(spec)
            _validate_build_identity(spec, build)
        except PreparationRemoteError as exc:
            self._remote_failure(record, exc)
            raise
        except ContractError as exc:
            self._contract_failure(record, "build_identity_mismatch", str(exc))
            raise
        with self.store.lock(spec.preparation_id):
            current = self._record(spec.preparation_id)
            if current.state not in {PreparationState.BUILD_SUBMITTING, PreparationState.AMBIGUOUS}:
                raise RecoveryRequiredError("preparation no longer accepts a build identity")
            current.kova_build_id = build.build_id
            current.kova_version = version.version
            current.kova_api_version = version.api_version
            current.state = PreparationState.BUILD_SUBMITTED
            current.ambiguous_operation = ""
            current.diagnostic_code = ""
            current.diagnostic_summary = ""
            current.updated_at = _now()
            self.store.save_record(current)

    def _finish_build(
        self, spec: SeedBuildSpec, record: PreparationRecord, *, wait_timeout: float
    ) -> None:
        if not record.kova_build_id:
            raise RecoveryRequiredError("build_submitted state has no Kova build ID")
        try:
            build = self.kova.get_build(record.kova_build_id)
            _validate_build_identity(spec, build)
            if build.status not in _TERMINAL:
                build = self.kova.wait_build(record.kova_build_id, timeout=wait_timeout)
                _validate_build_identity(spec, build)
        except PreparationRemoteError as exc:
            if exc.code == "timeout":
                self._diagnose(record, exc.code, exc.summary)
            else:
                self._remote_failure(record, exc)
            raise
        except ContractError as exc:
            self._contract_failure(record, "build_identity_mismatch", str(exc))
            raise
        if build.status != "succeeded":
            receipt = _failed_build_receipt(spec, record, build)
            path, digest = self.store.save_seed_receipt(spec.preparation_id, receipt)
            with self.store.lock(spec.preparation_id):
                current = self._record(spec.preparation_id)
                current.seed_build_receipt = str(path)
                current.seed_build_receipt_digest = digest
                current.state = (
                    PreparationState.CANCELLED
                    if build.status == "cancelled"
                    else PreparationState.FAILED
                )
                current.diagnostic_code = build.failure_code or f"kova_build_{build.status}"
                current.diagnostic_summary = build.failure_summary
                current.updated_at = _now()
                self.store.save_record(current)
            raise InfrastructureError(f"Kova build ended with status {build.status}")
        try:
            results = self.kova.get_results(build.build_id)
            output = _validate_results(spec, build, results)
        except PreparationRemoteError as exc:
            self._remote_failure(record, exc)
            raise
        except ContractError as exc:
            self._contract_failure(record, "invalid_kova_results", str(exc))
            raise
        receipt = SeedBuildReceipt(
            schema_version=1,
            request_digest=spec.request_digest,
            source_uri=results.source_uri,
            source_digest=results.source_digest,
            recipe_digest=spec.recipe_digest,
            target_role=spec.target_role,
            destination=spec.destination,
            platform=output.platform,
            format=output.format,
            idempotency_key=results.idempotency_key,
            kova_build_id=build.build_id,
            kova_version=record.kova_version,
            kova_api_version=record.kova_api_version,
            terminal_status=build.status,
            manifest_digest=output.manifest_digest,
            immutable_ref=output.immutable_ref,
            created_at=build.created_at,
            updated_at=build.updated_at,
        )
        path, digest = self.store.save_seed_receipt(spec.preparation_id, receipt)
        with self.store.lock(spec.preparation_id):
            current = self._record(spec.preparation_id)
            current.seed_build_receipt = str(path)
            current.seed_build_receipt_digest = digest
            current.state = PreparationState.BUILD_SUCCEEDED
            current.updated_at = _now()
            current.diagnostic_code = ""
            current.diagnostic_summary = ""
            self.store.save_record(current)

    def _resolve_environment(self, spec: SeedBuildSpec, record: PreparationRecord) -> None:
        receipt = self._seed_receipt(record)
        try:
            matches = self.axern.find_by_request_digest(
                spec.environment_namespace, spec.request_digest
            )
        except PreparationRemoteError as exc:
            self._remote_failure(record, exc)
            raise
        if len(matches) > 1:
            self._diagnose(record, "multiple_environments", "multiple exact label matches")
            self._mark(record, PreparationState.FAILED)
            raise InfrastructureError("multiple Axern Environments match the preparation digest")
        if matches:
            facts = matches[0]
        else:
            self._mark(record, PreparationState.ENVIRONMENT_CREATING)
            labels = {
                **spec.labels,
                _PREPARATION_LABEL: spec.request_digest,
                _PLATFORM_LABEL: "linux-amd64",
                "axrun.managed": "true",
            }
            try:
                facts = self.axern.create_environment(
                    namespace=spec.environment_namespace,
                    image=receipt.immutable_ref,
                    labels=labels,
                )
            except PreparationRemoteError as exc:
                self._remote_failure(record, exc)
                raise
        try:
            _validate_environment(spec, receipt, facts)
        except ContractError as exc:
            self._contract_failure(record, "environment_mismatch", str(exc))
            raise
        with self.store.lock(spec.preparation_id):
            current = self._record(spec.preparation_id)
            current.environment_id = facts.environment_id
            current.state = PreparationState.ENVIRONMENT_CREATED
            current.ambiguous_operation = ""
            current.updated_at = _now()
            current.diagnostic_code = ""
            current.diagnostic_summary = ""
            self.store.save_record(current)

    def _finish_environment(self, spec: SeedBuildSpec, record: PreparationRecord) -> None:
        if not record.environment_id:
            raise RecoveryRequiredError("environment_created state has no Environment ID")
        seed = self._seed_receipt(record)
        try:
            facts = self.axern.get_environment(record.environment_id)
        except PreparationRemoteError as exc:
            self._remote_failure(record, exc)
            raise
        try:
            _validate_environment(spec, seed, facts)
        except ContractError as exc:
            self._contract_failure(record, "environment_mismatch", str(exc))
            raise
        now = _now()
        receipt = EnvironmentPreparationReceipt(
            schema_version=1,
            preparation_id=spec.preparation_id,
            request_digest=spec.request_digest,
            seed_build_receipt_digest=record.seed_build_receipt_digest,
            environment_id=facts.environment_id,
            requested_image=facts.requested_image,
            resolved_manifest_digest=facts.resolved_manifest_digest,
            platform=spec.platform,
            working_directory=spec.working_directory,
            state=PreparationState.READY,
            created_at=record.created_at,
            updated_at=now,
        )
        path, digest = self.store.save_preparation_receipt(receipt)
        with self.store.lock(spec.preparation_id):
            current = self._record(spec.preparation_id)
            current.preparation_receipt = str(path)
            current.preparation_receipt_digest = digest
            current.state = PreparationState.READY
            current.updated_at = now
            current.diagnostic_code = ""
            current.diagnostic_summary = ""
            self.store.save_record(current)

    def _seed_receipt(self, record: PreparationRecord) -> SeedBuildReceipt:
        return self.store.load_seed_receipt(record)

    def _remote_failure(self, record: PreparationRecord, exc: PreparationRemoteError) -> None:
        with self.store.lock(record.preparation_id):
            current = self._record(record.preparation_id)
            if exc.ambiguous:
                current.state = PreparationState.AMBIGUOUS
            elif not exc.retryable:
                current.state = PreparationState.FAILED
            current.ambiguous_operation = exc.operation if exc.ambiguous else ""
            current.diagnostic_code = exc.code
            current.diagnostic_summary = exc.summary
            current.remote_status = exc.status
            current.remote_retryable = exc.retryable
            current.updated_at = _now()
            self.store.save_record(current)

    def _contract_failure(self, record: PreparationRecord, code: str, summary: str) -> None:
        with self.store.lock(record.preparation_id):
            current = self._record(record.preparation_id)
            current.state = PreparationState.FAILED
            current.ambiguous_operation = ""
            current.diagnostic_code = code
            current.diagnostic_summary = summary[:512]
            current.updated_at = _now()
            self.store.save_record(current)

    def _diagnose(self, record: PreparationRecord, code: str, summary: str) -> None:
        with self.store.lock(record.preparation_id):
            current = self._record(record.preparation_id)
            current.diagnostic_code = code
            current.diagnostic_summary = summary[:512]
            current.updated_at = _now()
            self.store.save_record(current)

    def _mark(self, record: PreparationRecord, state: PreparationState) -> None:
        with self.store.lock(record.preparation_id):
            current = self._record(record.preparation_id)
            current.state = state
            current.updated_at = _now()
            self.store.save_record(current)

    def _record(self, preparation_id: str) -> PreparationRecord:
        record = self.store.load_record(preparation_id)
        if record is None:
            raise ContractError(f"preparation does not exist: {preparation_id}")
        return record


def _validate_build_identity(spec: SeedBuildSpec, build: KovaBuild) -> None:
    if build.source_uri and build.source_uri != spec.source_uri:
        raise ContractError("Kova build source_uri differs from the request")
    if build.source_digest and build.source_digest != spec.source_digest:
        raise ContractError("Kova build source_digest differs from the request")
    if build.idempotency_key and build.idempotency_key != spec.idempotency_key:
        raise ContractError("Kova build idempotency key differs from the request")


def _validate_results(spec: SeedBuildSpec, build: KovaBuild, results: KovaResults):
    if results.build_id != build.build_id:
        raise ContractError("Kova results build ID mismatch")
    if results.source_uri != spec.source_uri or results.source_digest != spec.source_digest:
        raise ContractError("Kova results source identity mismatch")
    if results.idempotency_key != spec.idempotency_key:
        raise ContractError("Kova results idempotency key mismatch")
    if len(results.outputs) != 1:
        raise ContractError("Kova result must contain exactly one output")
    output = results.outputs[0]
    if output.platform != spec.platform or output.format != spec.format:
        raise ContractError("Kova output platform or format mismatch")
    if output.image != spec.destination:
        raise ContractError("Kova output target mismatch")
    SeedBuildReceipt(
        schema_version=1,
        request_digest=spec.request_digest,
        source_uri=spec.source_uri,
        source_digest=spec.source_digest,
        recipe_digest=spec.recipe_digest,
        target_role=spec.target_role,
        destination=spec.destination,
        platform=output.platform,
        format=output.format,
        idempotency_key=spec.idempotency_key,
        kova_build_id=build.build_id,
        kova_version="validation",
        kova_api_version="v1",
        terminal_status="succeeded",
        manifest_digest=output.manifest_digest,
        immutable_ref=output.immutable_ref,
        created_at=build.created_at,
        updated_at=build.updated_at,
    )
    return output


def _validate_environment(
    spec: SeedBuildSpec, receipt: SeedBuildReceipt, facts: EnvironmentFacts
) -> None:
    if facts.namespace != spec.environment_namespace:
        raise ContractError("Axern Environment namespace mismatch")
    if facts.requested_image != receipt.immutable_ref:
        raise ContractError("Axern Environment requested image mismatch")
    if facts.resolved_manifest_digest != receipt.manifest_digest:
        raise ContractError("Axern Environment resolved manifest digest mismatch")
    if facts.labels.get(_PREPARATION_LABEL) != spec.request_digest:
        raise ContractError("Axern Environment preparation label mismatch")
    if facts.labels.get(_PLATFORM_LABEL) != "linux-amd64":
        raise ContractError("Axern Environment platform label mismatch")


def _failed_build_receipt(
    spec: SeedBuildSpec, record: PreparationRecord, build: KovaBuild
) -> SeedBuildReceipt:
    return SeedBuildReceipt(
        schema_version=1,
        request_digest=spec.request_digest,
        source_uri=spec.source_uri,
        source_digest=spec.source_digest,
        recipe_digest=spec.recipe_digest,
        target_role=spec.target_role,
        destination=spec.destination,
        platform=spec.platform,
        format=spec.format,
        idempotency_key=spec.idempotency_key,
        kova_build_id=build.build_id,
        kova_version=record.kova_version,
        kova_api_version=record.kova_api_version,
        terminal_status=build.status,
        manifest_digest="",
        immutable_ref="",
        created_at=build.created_at,
        updated_at=build.updated_at,
        failure_code=build.failure_code,
        failure_summary="Kova build reported terminal failure" if build.failure_summary else "",
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
