"""ExecutionBackend implemented only with the released Axern Python SDK."""

from __future__ import annotations

import hashlib
import os
import stat
import tarfile
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol, cast

from axrun.errors import (
    ContractError,
    DiagnosedInfrastructureError,
    InfrastructureError,
    SdkCapabilityError,
)
from axrun.lifecycle.base import PreStartLifecycle
from axrun.models import (
    Artifact,
    ExecutionRef,
    InputFile,
    StageNetworkPolicy,
    StagePlan,
    StageResult,
)

# WriteFile is a unary RPC whose JSON transport has a 1 MiB body limit. Base64
# expansion makes even a sub-1 MiB file unsafe there; larger regular inputs use
# the public streaming UploadArchive RPC with exactly one regular tar member.
_INLINE_INPUT_MAX_BYTES = 512 << 10
_ARCHIVE_SPOOL_MAX_BYTES = 1 << 20


class AxernBackend:
    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "default",
        allocation_ready_timeout_seconds: float = 900.0,
    ) -> None:
        if allocation_ready_timeout_seconds <= 0:
            raise ValueError("allocation ready timeout must be positive")
        self.client = client
        self.namespace = namespace
        self.allocation_ready_timeout_seconds = allocation_ready_timeout_seconds

    def execute(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
        lifecycle: PreStartLifecycle | None = None,
    ) -> StageResult:
        return self._execute(
            plan,
            artifact_dir=artifact_dir,
            on_bound=on_bound,
            lifecycle=lifecycle,
            rootfs_snapshot=False,
        )

    def execute_rootfs(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
    ) -> tuple[StageResult, str]:
        result = self._execute(
            plan,
            artifact_dir=artifact_dir,
            on_bound=on_bound,
            lifecycle=None,
            rootfs_snapshot=True,
            download_outputs=False,
        )
        if result.exit_code != 0:
            return result, ""
        try:
            snapshot = self.client.wait_rootfs_snapshot(
                result.execution.run_id,
                timeout=plan.timeout_seconds + 120.0,
            )
        except Exception as exc:
            raise InfrastructureError("rootfs result did not become ready") from exc
        environment_id = str(getattr(snapshot, "environment_id", ""))
        image_ref = str(getattr(snapshot, "image_ref", ""))
        platform_os = str(getattr(snapshot, "platform_os", ""))
        platform_arch = str(getattr(snapshot, "platform_arch", ""))
        if not environment_id or "@sha256:" not in image_ref:
            raise InfrastructureError("rootfs result has an invalid derived Environment identity")
        if (platform_os, platform_arch) != ("linux", "amd64"):
            raise InfrastructureError("rootfs result platform is not linux/amd64")
        try:
            artifacts = self._download_outputs(result.execution.run_id, plan, artifact_dir)
        except (ContractError, InfrastructureError) as exc:
            self.delete_environment(environment_id)
            raise InfrastructureError("rootfs workload output is unavailable or invalid") from exc
        return (replace(result, artifacts=artifacts) if plan.outputs else result), environment_id

    def _execute(
        self,
        plan: StagePlan,
        *,
        artifact_dir: Path,
        on_bound: Callable[[ExecutionRef], None],
        lifecycle: PreStartLifecycle | None,
        rootfs_snapshot: bool,
        download_outputs: bool = True,
    ) -> StageResult:
        sdk = _sdk_types()
        ready_marker = "/run/axrun/inputs-ready"
        # A rootfs result can contain the marker written by its producer Run. Remove any
        # inherited marker before waiting so a derived Environment cannot release a fresh
        # Run before this caller has uploaded its inputs and completed pre-start lifecycle.
        wrapper = 'rm -f "$1"; while [ ! -f "$1" ]; do sleep 0.1; done; shift; exec "$@"'
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
            "rootfs_snapshot": rootfs_snapshot,
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
        if plan.network_policy == StageNetworkPolicy.DENY_ALL:
            kwargs["network_policy"] = sdk.NetworkPolicy.deny_all()
        elif plan.network_policy != StageNetworkPolicy.UNRESTRICTED:
            raise ContractError("unsupported stage network policy")

        run = self.client.create_run(**kwargs)
        execution = ExecutionRef(plan.environment_id, run.id)
        released = False
        try:
            # Binding is part of setup: a rejected local publication must not
            # leave an unowned Run waiting indefinitely for its ready marker.
            on_bound(execution)
            run = _wait_running(
                self.client,
                run.id,
                timeout_seconds=self.allocation_ready_timeout_seconds,
            )
            execution = ExecutionRef(plan.environment_id, run.id, run.allocation_id)
            on_bound(execution)
            allocation = self.client.allocation(run.allocation_id)
            if lifecycle is not None:
                lifecycle.start(execution, allocation)
            for item in plan.inputs:
                source = Path(item.source)
                if item.archive:
                    if item.sha256 and _sha256(source) != item.sha256:
                        raise InfrastructureError(f"input digest mismatch: {source}")
                    allocation.upload_archive(item.target, lambda source=source: _chunks(source))
                else:
                    _upload_regular_input(allocation, item, source)
            allocation.write_file(ready_marker, b"ready\n")
            released = True
        except BaseException:
            try:
                if lifecycle is not None:
                    try:
                        lifecycle.close()
                    except Exception:
                        raise DiagnosedInfrastructureError(
                            "lifecycle_cleanup_failed",
                            {"reason_code": "component_cleanup_failed"},
                        ) from None
            finally:
                # A cleanup error cannot skip cancellation before release. SDK
                # exception text is not safe to expose as a cleanup diagnostic.
                if not released:
                    try:
                        self.client.cancel_run(run.id)
                    except Exception:
                        raise DiagnosedInfrastructureError(
                            "prestart_cleanup_failed",
                            {"reason_code": "unreleased_run_cancel_failed"},
                        ) from None
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
            artifacts = (
                ()
                if exit_code != 0 or not download_outputs
                else self._download_outputs(run.id, plan, artifact_dir)
            )
            diagnostic_details = _lifecycle_failure_diagnostic(lifecycle, exit_code)
            return StageResult(
                execution=execution,
                exit_code=exit_code,
                diagnostic_code=_diagnostic_name(terminal),
                artifacts=artifacts,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                diagnostic_details=diagnostic_details,
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
        download_outputs: bool = True,
    ) -> StageResult | None:
        if plan.environment_id != execution.environment_id:
            raise InfrastructureError("recovery plan differs from the persisted Environment")
        run = self.client.get_run(execution.run_id)
        # Public Run facts are authoritative. A local plan must not relabel a
        # foreign Run, and a saved Allocation must never change on recovery.
        allocation_id = getattr(run, "allocation_id", None)
        if (
            getattr(run, "id", None) != execution.run_id
            or getattr(run, "environment_id", None) != execution.environment_id
            or not isinstance(allocation_id, str)
            or (execution.allocation_id and allocation_id != execution.allocation_id)
        ):
            raise InfrastructureError("recovered Run does not match the persisted Axern execution")
        if _status_name(run) not in {
            "RUN_STATUS_SUCCEEDED",
            "RUN_STATUS_FAILED",
            "RUN_STATUS_CANCELLED",
        }:
            return None
        exit_code = _effective_exit_code(run)
        artifacts = (
            ()
            if exit_code != 0 or not download_outputs
            else self._download_outputs(run.id, plan, artifact_dir)
        )
        stdout_path, stderr_path = self._capture_output(
            run.id, artifact_dir, follow=False, timeout=30.0
        )
        return StageResult(
            execution=ExecutionRef(run.environment_id, run.id, allocation_id),
            exit_code=exit_code,
            diagnostic_code=_diagnostic_name(run),
            artifacts=artifacts,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    def recover_rootfs(
        self,
        execution: ExecutionRef,
        plan: StagePlan,
        *,
        artifact_dir: Path,
    ) -> tuple[StageResult, str] | None:
        result = self.recover(execution, plan, artifact_dir=artifact_dir, download_outputs=False)
        if result is None:
            return None
        if result.exit_code != 0:
            return result, ""
        try:
            snapshot = self.client.wait_rootfs_snapshot(
                execution.run_id,
                timeout=plan.timeout_seconds + 120.0,
            )
        except Exception as exc:
            raise InfrastructureError("rootfs result did not become ready") from exc
        environment_id = str(getattr(snapshot, "environment_id", ""))
        image_ref = str(getattr(snapshot, "image_ref", ""))
        platform_os = str(getattr(snapshot, "platform_os", ""))
        platform_arch = str(getattr(snapshot, "platform_arch", ""))
        if not environment_id or "@sha256:" not in image_ref:
            raise InfrastructureError("rootfs result has an invalid derived Environment identity")
        if (platform_os, platform_arch) != ("linux", "amd64"):
            raise InfrastructureError("rootfs result platform is not linux/amd64")
        try:
            artifacts = self._download_outputs(result.execution.run_id, plan, artifact_dir)
        except (ContractError, InfrastructureError) as exc:
            self.delete_environment(environment_id)
            raise InfrastructureError("rootfs workload output is unavailable or invalid") from exc
        return (replace(result, artifacts=artifacts) if plan.outputs else result), environment_id

    def delete_environment(self, environment_id: str) -> None:
        from axern_sdk import SandboxNotFoundError

        try:
            self.client.delete_environment(environment_id)
        except SandboxNotFoundError:
            return
        except Exception as exc:
            raise InfrastructureError("derived Environment cleanup failed") from exc

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
        if not plan.outputs:
            return ()
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
        paths = [value.path for value in manifest]
        output_ids = [value.output_id for value in manifest]
        if (
            any(not isinstance(value, str) or not value.startswith("/") for value in paths)
            or any(not isinstance(value, str) or not value for value in output_ids)
            or len(paths) != len(set(paths))
            or len(output_ids) != len(set(output_ids))
        ):
            raise InfrastructureError("sealed output manifest identity is ambiguous")
        by_path = {value.path: value for value in manifest}
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[Artifact] = []
        for index, expected in enumerate(plan.outputs):
            sealed = by_path.get(expected.path)
            if sealed is None or sealed.status != "available":
                # SDK diagnostic payloads are not a safe log boundary.
                reason = "missing" if sealed is None else "not_available"
                raise ContractError(f"declared output {expected.path} is unavailable: {reason}")
            if (
                not isinstance(sealed.size_bytes, int)
                or isinstance(sealed.size_bytes, bool)
                or sealed.size_bytes < 0
            ):
                raise InfrastructureError("sealed output manifest size is invalid")
            if sealed.size_bytes > expected.max_bytes:
                raise ContractError(
                    f"declared output {expected.path} exceeds {expected.max_bytes} bytes"
                )
            if (
                not isinstance(sealed.sha256, str)
                or len(sealed.sha256) != 64
                or any(value not in "0123456789abcdef" for value in sealed.sha256)
                or sealed.media_type != expected.media_type
            ):
                raise InfrastructureError("sealed output manifest metadata is invalid")
            destination = artifact_dir / f"{index:02d}-{Path(expected.path).name}"
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".partial", dir=artifact_dir
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    try:
                        verified = self.client.download_sealed_output(
                            run_id, sealed.output_id, stream
                        )
                    except Exception:
                        raise InfrastructureError(
                            f"sealed output download failed: {expected.path}"
                        ) from None
                    stream.flush()
                    os.fsync(stream.fileno())
                if verified.status != "available" or any(
                    getattr(verified, field) != getattr(sealed, field)
                    for field in ("output_id", "path", "size_bytes", "sha256", "media_type")
                ):
                    raise InfrastructureError(
                        f"sealed output metadata changed during download: {expected.path}"
                    )
                if (
                    temporary.stat().st_size != sealed.size_bytes
                    or _sha256(temporary) != sealed.sha256
                ):
                    raise InfrastructureError(
                        f"downloaded output failed integrity check: {expected.path}"
                    )
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
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


def _lifecycle_failure_diagnostic(
    lifecycle: PreStartLifecycle | None, exit_code: int
) -> dict[str, Any]:
    if lifecycle is None or exit_code == 0:
        return {}
    value: object = getattr(lifecycle, "failure_diagnostic", {})
    return dict(cast(dict[str, Any], value)) if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        yield from _stream_chunks(stream)


class _ReadableBytes(Protocol):
    def read(self, size: int, /) -> bytes: ...


def _stream_chunks(stream: _ReadableBytes) -> Iterator[bytes]:
    while chunk := stream.read(1024 * 1024):
        yield chunk


class _DigestingReader:
    def __init__(self, stream: _ReadableBytes) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        value = self.stream.read(size)
        self.digest.update(value)
        self.size += len(value)
        return value


def _regular_input_target(target: str) -> tuple[str, str]:
    if (
        not target.startswith("/")
        or target == "/"
        or len(target.encode("utf-8")) > 4096
        or "\x00" in target
        or "\\" in target
        or any(part in {"", ".", ".."} for part in target[1:].split("/"))
    ):
        raise ContractError("regular input target must be a normalized absolute file path")
    parent, _, basename = target.rpartition("/")
    return parent or "/", basename


def _upload_regular_input(allocation: Any, item: InputFile, source: Path) -> None:
    parent, basename = _regular_input_target(item.target)
    # O_NOFOLLOW and fstat ensure the archive can contain only the opened regular
    # file, never a symlink or a directory substituted for the source path.
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        source_stat = os.fstat(stream.fileno())
        size = source_stat.st_size
        if not stat.S_ISREG(source_stat.st_mode):
            raise ContractError("regular input source must be a regular file")
        if size <= _INLINE_INPUT_MAX_BYTES:
            payload = stream.read(_INLINE_INPUT_MAX_BYTES + 1)
            if len(payload) != size or stream.read(1):
                raise InfrastructureError("input changed while being read")
            if item.sha256 and hashlib.sha256(payload).hexdigest() != item.sha256:
                raise InfrastructureError(f"input digest mismatch: {source}")
            allocation.write_file(item.target, payload)
            return

        # The spool has bounded memory and is closed on both success and RPC
        # failure. The member name is the validated target basename, not a path
        # supplied by a source archive; all tar metadata is deterministic.
        with tempfile.SpooledTemporaryFile(max_size=_ARCHIVE_SPOOL_MAX_BYTES) as archive_stream:
            member = tarfile.TarInfo(basename)
            member.size = size
            member.mode = 0o644
            member.uid = member.gid = member.mtime = 0
            member.type = tarfile.REGTYPE
            reader = _DigestingReader(stream)
            with tarfile.open(fileobj=archive_stream, mode="w", format=tarfile.PAX_FORMAT) as tar:
                tar.addfile(member, reader)
            if reader.size != size or stream.read(1):
                raise InfrastructureError("input changed while being archived")
            if item.sha256 and reader.digest.hexdigest() != item.sha256:
                raise InfrastructureError(f"input digest mismatch: {source}")
            archive_stream.seek(0)
            allocation.upload_archive(parent, lambda: _stream_chunks(archive_stream))
