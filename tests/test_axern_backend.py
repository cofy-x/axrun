from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from axern_sdk import AxernClient

import axrun.axern_backend as backend_module
from axrun.axern_backend import AxernBackend
from axrun.models import OutputSpec, ResourceSpec, StagePlan


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
