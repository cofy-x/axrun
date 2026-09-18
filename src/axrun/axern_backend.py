"""ExecutionBackend implemented only with the released Axern Python SDK."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from axrun.errors import ContractError, InfrastructureError, SdkCapabilityError
from axrun.lifecycle.base import PreStartLifecycle
from axrun.models import Artifact, ExecutionRef, StagePlan, StageResult


class AxernBackend:
    def __init__(self, client: Any, *, namespace: str = "default") -> None:
        self.client = client
        self.namespace = namespace

    def execute(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
        lifecycle: PreStartLifecycle | None = None,
    ) -> StageResult:
        sdk = _sdk_types()
        ready_marker = "/run/axrun/inputs-ready"
        wrapper = 'while [ ! -f "$1" ]; do sleep 0.1; done; shift; exec "$@"'
        kwargs: dict[str, Any] = {
            "environment_id": plan.environment_id,
            "namespace": self.namespace,
            "argv": ["/bin/sh", "-c", wrapper, "axrun", ready_marker, *plan.argv],
            "env": plan.env,
            "cwd": plan.cwd,
            "declared_outputs": [
                sdk.DeclaredOutput(
                    path=value.path,
                    format=(
                        sdk.DeclaredOutputFormat.TAR
                        if value.format.value == "tar"
                        else sdk.DeclaredOutputFormat.FILE
                    ),
                    media_type=value.media_type,
                )
                for value in plan.outputs
            ],
            "labels": {"axrun.managed": "true", **plan.labels},
            "request_cpu": plan.resources.request_cpu,
            "request_memory": plan.resources.request_memory,
            "request_ephemeral_storage": plan.resources.request_ephemeral_storage,
            "limit_cpu": plan.resources.limit_cpu,
            "limit_memory": plan.resources.limit_memory,
            "limit_ephemeral_storage": plan.resources.limit_ephemeral_storage,
        }
        if plan.image_mounts:
            kwargs["image_mounts"] = [
                sdk.ImageMount(image=value.image, target=value.target)
                for value in plan.image_mounts
            ]
        if plan.secret_env:
            kwargs["secret_env"] = [
                sdk.SecretEnvVar(name=value.name, secret_id=value.secret_id, key=value.key)
                for value in plan.secret_env
            ]
        if plan.network_policy == "deny_all":
            kwargs["network_policy"] = sdk.NetworkPolicy.deny_all()

        run = self.client.create_run(**kwargs)
        execution = ExecutionRef(plan.environment_id, run.id)
        on_bound(execution)
        run = _wait_running(self.client, run.id, timeout_seconds=180.0)
        execution = ExecutionRef(plan.environment_id, run.id, run.allocation_id)
        on_bound(execution)
        allocation = self.client.allocation(run.allocation_id)
        released = False
        try:
            if lifecycle is not None:
                lifecycle.start(execution, allocation)
            for item in plan.inputs:
                source = Path(item.source)
                if item.sha256 and _sha256(source) != item.sha256:
                    raise InfrastructureError(f"input digest mismatch: {source}")
                if item.archive:
                    allocation.upload_archive(item.target, lambda source=source: _chunks(source))
                else:
                    allocation.write_file(item.target, source.read_bytes())
            allocation.write_file(ready_marker, b"ready\n")
            released = True
        except BaseException:
            if lifecycle is not None:
                lifecycle.close()
            if not released:
                self.client.cancel_run(run.id)
            raise
        try:
            # Once the process is released, an ambiguous transport failure must be
            # recovered by the persisted Run ID. It must not become an implicit
            # cancellation merely because this client lost its connection.
            stdout_path, stderr_path = self._capture_output(
                run.id, artifact_dir, follow=True, timeout=plan.timeout_seconds + 120.0
            )
            terminal = self.client.wait_run(run.id, timeout=plan.timeout_seconds + 120.0)
            exit_code = _effective_exit_code(terminal)
            artifacts = () if exit_code != 0 else self._download_outputs(run.id, plan, artifact_dir)
            return StageResult(
                execution=execution,
                exit_code=exit_code,
                diagnostic_code=_diagnostic_name(terminal),
                artifacts=artifacts,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )
        finally:
            if lifecycle is not None:
                lifecycle.close()

    def recover(
        self,
        execution: ExecutionRef,
        plan: StagePlan,
        *,
        artifact_dir: Path,
    ) -> StageResult | None:
        run = self.client.get_run(execution.run_id)
        if _status_name(run) not in {
            "RUN_STATUS_SUCCEEDED",
            "RUN_STATUS_FAILED",
            "RUN_STATUS_CANCELLED",
        }:
            return None
        exit_code = _effective_exit_code(run)
        artifacts = () if exit_code != 0 else self._download_outputs(run.id, plan, artifact_dir)
        stdout_path, stderr_path = self._capture_output(
            run.id, artifact_dir, follow=False, timeout=30.0
        )
        return StageResult(
            execution=ExecutionRef(plan.environment_id, run.id, run.allocation_id),
            exit_code=exit_code,
            diagnostic_code=_diagnostic_name(run),
            artifacts=artifacts,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    def cancel(self, execution: ExecutionRef) -> None:
        run = self.client.get_run(execution.run_id)
        if _status_name(run) not in _TERMINAL_STATUSES:
            self.client.cancel_run(execution.run_id)

    def wait(self, execution: ExecutionRef, *, timeout: float | None = None) -> None:
        self.client.wait_run(execution.run_id, timeout=timeout)

    def _capture_output(
        self,
        run_id: str,
        artifact_dir: Path,
        *,
        follow: bool,
        timeout: float,
    ) -> tuple[Path, Path]:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = artifact_dir / "stdout.log"
        stderr_path = artifact_dir / "stderr.log"
        sizes = {stdout_path: 0, stderr_path: 0}
        streams = {1: stdout_path, 2: stderr_path}
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            handles = {stdout_path: stdout, stderr_path: stderr}
            for event in self.client.read_run_output(run_id, follow=follow, timeout=timeout):
                destination = streams.get(int(event.stream))
                if destination is None or not event.data:
                    continue
                remaining = (16 << 20) - sizes[destination]
                if remaining > 0:
                    handles[destination].write(bytes(event.data[:remaining]))
                    sizes[destination] += min(len(event.data), remaining)
        return stdout_path, stderr_path

    def _download_outputs(
        self, run_id: str, plan: StagePlan, artifact_dir: Path
    ) -> tuple[Artifact, ...]:
        deadline = time.monotonic() + 60.0
        while True:
            try:
                manifest = self.client.get_sealed_output_manifest(run_id)
                break
            except Exception as exc:
                if not _manifest_retryable(exc) or time.monotonic() >= deadline:
                    raise InfrastructureError(
                        "sealed output manifest did not become available"
                    ) from exc
                time.sleep(0.25)
        by_path = {value.path: value for value in manifest}
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[Artifact] = []
        for index, expected in enumerate(plan.outputs):
            sealed = by_path.get(expected.path)
            if sealed is None or sealed.status != "available":
                reason = "missing" if sealed is None else f"{sealed.status}: {sealed.reason}"
                raise ContractError(f"declared output {expected.path} is unavailable: {reason}")
            if int(sealed.size_bytes) > expected.max_bytes:
                raise ContractError(
                    f"declared output {expected.path} exceeds {expected.max_bytes} bytes"
                )
            destination = artifact_dir / f"{index:02d}-{Path(expected.path).name}"
            with destination.open("wb") as stream:
                verified = self.client.download_sealed_output(run_id, sealed.output_id, stream)
            if (
                destination.stat().st_size != verified.size_bytes
                or _sha256(destination) != verified.sha256
            ):
                destination.unlink(missing_ok=True)
                raise InfrastructureError(
                    f"downloaded output failed integrity check: {expected.path}"
                )
            artifacts.append(
                Artifact(
                    name=expected.path,
                    path=str(destination),
                    size_bytes=verified.size_bytes,
                    sha256=verified.sha256,
                    media_type=verified.media_type,
                )
            )
        return tuple(artifacts)


def _sdk_types() -> Any:
    try:
        import axern_sdk
    except ImportError as exc:
        raise SdkCapabilityError("axern-sdk is not installed") from exc
    return axern_sdk


def _wait_running(client: Any, run_id: str, *, timeout_seconds: float) -> Any:
    deadline = time.monotonic() + timeout_seconds
    run = client.get_run(run_id)
    if run.allocation_id and _status_name(run) == "RUN_STATUS_RUNNING":
        return run
    for update in client.watch_run(run_id, after_version=run.version, timeout=timeout_seconds):
        if update.allocation_id and _status_name(update) == "RUN_STATUS_RUNNING":
            return update
        if _status_name(update) in _TERMINAL_STATUSES:
            raise InfrastructureError("Run became terminal before its Allocation was usable")
        if time.monotonic() >= deadline:
            break
    raise InfrastructureError("Run did not reach running state")


def _status_name(run: Any) -> str:
    status_field = run.DESCRIPTOR.fields_by_name["status"]
    return str(status_field.enum_type.values_by_number[int(run.status)].name)


def _effective_exit_code(run: Any) -> int:
    """Do not interpret an absent proto3 exit code as success on a failed Run."""
    exit_code = int(run.exit_code)
    try:
        status = _status_name(run)
    except AttributeError:
        return exit_code
    return 1 if status != "RUN_STATUS_SUCCEEDED" and exit_code == 0 else exit_code


def _diagnostic_name(run: Any) -> str:
    value = run.diagnostic_code
    if isinstance(value, str):
        return value
    try:
        field = run.DESCRIPTOR.fields_by_name["diagnostic_code"]
        name = str(field.enum_type.values_by_number[int(value)].name)
    except (AttributeError, KeyError):
        return str(value)
    return "" if name.endswith("_UNSPECIFIED") else name


_TERMINAL_STATUSES = {
    "RUN_STATUS_SUCCEEDED",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_CANCELLED",
}


def _manifest_retryable(exc: Exception) -> bool:
    from axern_sdk import SandboxConnectionError, SandboxNotFoundError

    if isinstance(exc, SandboxNotFoundError):
        return True
    return isinstance(exc, SandboxConnectionError) and exc.retryable


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            yield chunk
