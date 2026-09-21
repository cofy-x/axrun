from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from axern_sdk import AxernClient

import axrun.axern_backend as backend_module
from axrun.axern_backend import AxernBackend
from axrun.errors import ContractError
from axrun.models import ExecutionRef, OutputSpec, ResourceSpec, StagePlan


def test_released_sdk_has_required_public_run_contract() -> None:
    parameters = inspect.signature(AxernClient.create_run).parameters
    assert {"image_mounts", "secret_env", "secret_files", "declared_outputs"} <= set(parameters)


def test_backend_creates_run_without_private_execution_identity(
    tmp_path: Path, monkeypatch
) -> None:
    class Allocation:
        def write_file(self, path, value):
            assert path == "/run/axrun/inputs-ready" and value == b"ready\n"

    class Client:
        def __init__(self):
            self.kwargs = None

        def create_run(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(id="run-1")

        def allocation(self, allocation_id):
            assert allocation_id == "alloc-1"
            return Allocation()

        def wait_run(self, run_id, timeout):
            return SimpleNamespace(exit_code=0, diagnostic_code="")

        def cancel_run(self, run_id):
            raise AssertionError("successful Run must not be cancelled")

    client = Client()
    backend = AxernBackend(client)
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: SimpleNamespace(id="run-1", allocation_id="alloc-1"),
    )
    monkeypatch.setattr(
        backend, "_capture_output", lambda *_args, **_kwargs: (tmp_path / "out", tmp_path / "err")
    )
    monkeypatch.setattr(backend, "_download_outputs", lambda *_args, **_kwargs: ())
    bound = []
    backend.execute(
        StagePlan(
            "env",
            ("true",),
            "/workspace",
            (OutputSpec("/outputs/result"),),
            resources=ResourceSpec(request_cpu="500m", limit_memory="2Gi"),
        ),
        artifact_dir=tmp_path,
        on_bound=bound.append,
    )
    assert client.kwargs is not None
    assert "node_id" not in client.kwargs and "runtime_id" not in client.kwargs
    assert client.kwargs["request_cpu"] == "500m"
    assert client.kwargs["limit_memory"] == "2Gi"
    assert [value.run_id for value in bound] == ["run-1", "run-1"]
    assert bound[-1].allocation_id == "alloc-1"
    assert client.kwargs["rootfs_snapshot"] is False


def test_backend_waits_for_public_rootfs_result_after_success(tmp_path: Path, monkeypatch) -> None:
    execution = ExecutionRef("base-env", "run-compile", "alloc-compile")
    stage = SimpleNamespace(execution=execution, exit_code=0)

    class Client:
        def wait_rootfs_snapshot(self, run_id, timeout):
            assert run_id == "run-compile" and timeout > 120
            return SimpleNamespace(
                environment_id="derived-env",
                image_ref=f"registry.invalid/rootfs@sha256:{'a' * 64}",
                platform_os="linux",
                platform_arch="amd64",
            )

    backend = AxernBackend(Client())
    monkeypatch.setattr(backend, "_execute", lambda *_args, **_kwargs: stage)
    result, environment_id = backend.execute_rootfs(
        StagePlan("base-env", ("true",), "/workspace", (), timeout_seconds=300),
        artifact_dir=tmp_path,
        on_bound=lambda _execution: None,
    )
    assert result is stage
    assert environment_id == "derived-env"


def test_output_capture_has_per_stream_bound(tmp_path: Path) -> None:
    class Client:
        def read_run_output(self, *args, **kwargs):
            yield SimpleNamespace(stream=1, data=b"x" * ((16 << 20) + 100))
            yield SimpleNamespace(stream=2, data=b"error")

    stdout, stderr = AxernBackend(Client())._capture_output(
        "run", tmp_path, follow=False, timeout=1
    )
    assert stdout.stat().st_size == 16 << 20
    assert stderr.read_bytes() == b"error"


def test_sealed_output_manifest_size_is_bounded_before_download(tmp_path: Path) -> None:
    class Client:
        def get_sealed_output_manifest(self, _run_id):
            return [
                SimpleNamespace(
                    path="/outputs/large",
                    status="available",
                    reason="",
                    size_bytes=5,
                    output_id="output-1",
                )
            ]

        def download_sealed_output(self, *_args):
            raise AssertionError("oversized output must not be downloaded")

    with __import__("pytest").raises(ContractError, match="exceeds 4 bytes"):
        AxernBackend(Client())._download_outputs(
            "run",
            StagePlan("env", ("true",), "/workspace", (OutputSpec("/outputs/large", max_bytes=4),)),
            tmp_path,
        )


def test_transport_failure_after_launch_does_not_implicitly_cancel(
    tmp_path: Path, monkeypatch
) -> None:
    class Allocation:
        def write_file(self, _path, _value):
            return None

    class Client:
        def __init__(self):
            self.cancelled = False

        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-1")

        def allocation(self, _allocation_id):
            return Allocation()

        def cancel_run(self, _run_id):
            self.cancelled = True

    client = Client()
    backend = AxernBackend(client)
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: SimpleNamespace(id="run-1", allocation_id="alloc-1"),
    )
    monkeypatch.setattr(
        backend,
        "_capture_output",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("partition")),
    )
    with __import__("pytest").raises(ConnectionError, match="partition"):
        backend.execute(
            StagePlan("env", ("true",), "/workspace", ()),
            artifact_dir=tmp_path,
            on_bound=lambda _ref: None,
        )
    assert client.cancelled is False


def test_recovery_normalizes_unset_exit_code_on_failed_run(tmp_path: Path, monkeypatch) -> None:
    failed = SimpleNamespace(
        id="run-failed",
        allocation_id="alloc-failed",
        exit_code=0,
        diagnostic_code="WORKLOAD_DIAGNOSTIC_CODE_RUNTIME_START_ERROR",
    )

    class Client:
        def get_run(self, _run_id):
            return failed

    backend = AxernBackend(Client())
    monkeypatch.setattr(backend_module, "_status_name", lambda _run: "RUN_STATUS_FAILED")
    monkeypatch.setattr(
        backend, "_download_outputs", lambda *_args, **_kwargs: pytest.fail("must not download")
    )
    monkeypatch.setattr(
        backend, "_capture_output", lambda *_args, **_kwargs: (tmp_path / "out", tmp_path / "err")
    )
    result = backend.recover(
        ExecutionRef("env", "run-failed", "alloc-failed"),
        StagePlan("env", ("true",), "/workspace", (OutputSpec("/outputs/result"),)),
        artifact_dir=tmp_path,
    )
    assert result is not None
    assert result.exit_code == 1 and result.artifacts == ()


def test_prestart_runs_after_allocation_binding_and_before_release(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []

    class Allocation:
        def write_file(self, path, _value):
            assert path == "/run/axrun/inputs-ready"
            events.append("released")

    class Lifecycle:
        def start(self, execution, allocation):
            assert execution.allocation_id == "alloc-1"
            assert isinstance(allocation, Allocation)
            events.append("prestart")

        def close(self):
            events.append("closed")

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-1")

        def allocation(self, _allocation_id):
            return Allocation()

        def wait_run(self, _run_id, timeout):
            return SimpleNamespace(exit_code=0, diagnostic_code="")

        def cancel_run(self, _run_id):
            events.append("cancelled")

    backend = AxernBackend(Client())
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: SimpleNamespace(id="run-1", allocation_id="alloc-1"),
    )
    monkeypatch.setattr(
        backend, "_capture_output", lambda *_args, **_kwargs: (tmp_path / "out", tmp_path / "err")
    )
    monkeypatch.setattr(backend, "_download_outputs", lambda *_args, **_kwargs: ())
    backend.execute(
        StagePlan("env", ("true",), "/workspace", ()),
        artifact_dir=tmp_path,
        on_bound=lambda ref: events.append(
            "allocation-bound" if ref.allocation_id else "run-bound"
        ),
        lifecycle=Lifecycle(),
    )
    assert events == ["run-bound", "allocation-bound", "prestart", "released", "closed"]


def test_prestart_failure_cancels_run_before_release(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []

    class Lifecycle:
        def start(self, _execution, _allocation):
            events.append("prestart")
            raise RuntimeError("preflight failed")

        def close(self):
            events.append("closed")

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-1")

        def allocation(self, _allocation_id):
            return object()

        def cancel_run(self, run_id):
            events.append(f"cancelled:{run_id}")

    backend = AxernBackend(Client())
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: SimpleNamespace(id="run-1", allocation_id="alloc-1"),
    )
    with __import__("pytest").raises(RuntimeError, match="preflight failed"):
        backend.execute(
            StagePlan("env", ("true",), "/workspace", ()),
            artifact_dir=tmp_path,
            on_bound=lambda _ref: None,
            lifecycle=Lifecycle(),
        )
    assert events == ["prestart", "closed", "cancelled:run-1"]


def test_failed_run_carries_only_lifecycle_safe_diagnostic(tmp_path: Path, monkeypatch) -> None:
    class Allocation:
        def write_file(self, _path, _value):
            return None

    class Lifecycle:
        @property
        def failure_diagnostic(self):
            return {
                "protocol": "anthropic",
                "path": "/v1/messages",
                "status": 503,
                "reason_code": "upstream_response",
            }

        def start(self, _execution, _allocation):
            return None

        def close(self):
            return None

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-1")

        def allocation(self, _allocation_id):
            return Allocation()

        def wait_run(self, _run_id, timeout):
            return SimpleNamespace(exit_code=1, diagnostic_code="")

        def cancel_run(self, _run_id):
            raise AssertionError("released Run must not be cancelled")

    backend = AxernBackend(Client())
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: SimpleNamespace(id="run-1", allocation_id="alloc-1"),
    )
    monkeypatch.setattr(
        backend, "_capture_output", lambda *_args, **_kwargs: (tmp_path / "out", tmp_path / "err")
    )
    result = backend.execute(
        StagePlan("env", ("false",), "/workspace", ()),
        artifact_dir=tmp_path,
        on_bound=lambda _ref: None,
        lifecycle=Lifecycle(),
    )
    assert result.exit_code == 1
    assert result.diagnostic_details == Lifecycle().failure_diagnostic
