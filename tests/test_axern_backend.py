from __future__ import annotations

import hashlib
import inspect
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from axern_sdk import AxernClient, NetworkPolicy, SandboxNotFoundError

import axrun.axern_backend as backend_module
from axrun.axern_backend import AxernBackend
from axrun.errors import ContractError, InfrastructureError
from axrun.models import (
    ExecutionRef,
    InputFile,
    OutputSpec,
    ResourceSpec,
    StageNetworkPolicy,
    StagePlan,
)


def test_released_sdk_has_required_public_run_contract() -> None:
    parameters = inspect.signature(AxernClient.create_run).parameters
    assert {"image_mounts", "secret_env", "secret_files", "declared_outputs"} <= set(parameters)


def test_backend_allows_bounded_cold_image_startup_timeout() -> None:
    assert AxernBackend(object()).allocation_ready_timeout_seconds == 900.0
    assert (
        AxernBackend(
            object(), allocation_ready_timeout_seconds=30.0
        ).allocation_ready_timeout_seconds
        == 30.0
    )
    with pytest.raises(ValueError, match="must be positive"):
        AxernBackend(object(), allocation_ready_timeout_seconds=0)


def test_unavailable_sealed_output_does_not_echo_sdk_reason(tmp_path: Path) -> None:
    class Client:
        def get_sealed_output_manifest(self, _run_id):
            return [
                SimpleNamespace(
                    path="/outputs/result.json",
                    output_id="output-result",
                    status="Authorization: Bearer private",
                    reason="private request body",
                )
            ]

    plan = StagePlan("env", ("true",), "/workspace", outputs=(OutputSpec("/outputs/result.json"),))
    with pytest.raises(ContractError, match="not_available") as raised:
        AxernBackend(Client())._download_outputs("run", plan, tmp_path)
    assert "private" not in str(raised.value)
    assert "Authorization" not in str(raised.value)


def _run_input_stage(tmp_path: Path, monkeypatch, client, item: InputFile) -> None:
    backend = AxernBackend(client)
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: SimpleNamespace(id="run-input", allocation_id="alloc-input"),
    )
    monkeypatch.setattr(
        backend, "_capture_output", lambda *_args, **_kwargs: (tmp_path / "out", tmp_path / "err")
    )
    backend.execute(
        StagePlan("env", ("true",), "/workspace", (), inputs=(item,)),
        artifact_dir=tmp_path,
        on_bound=lambda _ref: None,
    )


def test_small_regular_input_uses_write_file(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "small.txt"
    source.write_bytes(b"small input")
    events: list[tuple[str, object]] = []

    class Allocation:
        def write_file(self, path, value):
            events.append((path, value))

        def upload_archive(self, *_args):
            pytest.fail("small regular input must not use archive upload")

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-input")

        def allocation(self, _allocation_id):
            return Allocation()

        def wait_run(self, _run_id, timeout):
            return SimpleNamespace(exit_code=0, diagnostic_code="")

        def cancel_run(self, _run_id):
            pytest.fail("successful Run must not be cancelled")

    _run_input_stage(
        tmp_path,
        monkeypatch,
        Client(),
        InputFile(
            str(source), "/opt/inputs/small.txt", hashlib.sha256(source.read_bytes()).hexdigest()
        ),
    )
    assert events == [
        ("/opt/inputs/small.txt", b"small input"),
        ("/run/axrun/inputs-ready", b"ready\n"),
    ]


def test_large_regular_input_uses_single_safe_streamed_tar(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "setuptools.whl"
    payload = b"fixed-wheel-bytes" * 53_965
    assert len(payload) > 512 << 10
    source.write_bytes(payload)
    uploads: list[tuple[str, bytes]] = []
    releases: list[str] = []

    class Allocation:
        def write_file(self, path, _value):
            releases.append(path)

        def upload_archive(self, path, chunk_factory):
            chunks = list(chunk_factory())
            assert chunks and all(0 < len(chunk) <= 1 << 20 for chunk in chunks)
            uploads.append((path, b"".join(chunks)))

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-input")

        def allocation(self, _allocation_id):
            return Allocation()

        def wait_run(self, _run_id, timeout):
            return SimpleNamespace(exit_code=0, diagnostic_code="")

        def cancel_run(self, _run_id):
            pytest.fail("successful Run must not be cancelled")

    _run_input_stage(
        tmp_path,
        monkeypatch,
        Client(),
        InputFile(
            str(source), "/opt/axrun-wheelhouse/setuptools.whl", hashlib.sha256(payload).hexdigest()
        ),
    )
    assert len(uploads) == 1
    assert uploads[0][0] == "/opt/axrun-wheelhouse"
    assert releases == ["/run/axrun/inputs-ready"]
    with tarfile.open(fileobj=io.BytesIO(uploads[0][1]), mode="r:") as archive:
        members = archive.getmembers()
        assert len(members) == 1
        assert members[0].name == "setuptools.whl"
        assert members[0].isfile() and not members[0].issym()
        assert members[0].mode == 0o644 and members[0].mtime == 0
        extracted = archive.extractfile(members[0])
        assert extracted is not None and extracted.read() == payload


@pytest.mark.parametrize(
    ("size", "expected_method"),
    [(512 << 10, "write_file"), ((512 << 10) + 1, "upload_archive")],
)
def test_regular_input_transport_boundary_is_explicit(
    tmp_path: Path, size: int, expected_method: str
) -> None:
    source = tmp_path / "boundary.bin"
    payload = b"x" * size
    source.write_bytes(payload)
    events: list[str] = []

    class Allocation:
        def write_file(self, _target, contents):
            assert contents == payload
            events.append("write_file")

        def upload_archive(self, _target, chunk_factory):
            assert b"".join(chunk_factory())
            events.append("upload_archive")

    backend_module._upload_regular_input(
        Allocation(),
        InputFile(str(source), "/opt/inputs/boundary.bin", hashlib.sha256(payload).hexdigest()),
        source,
    )
    assert events == [expected_method]


def test_explicit_archive_input_keeps_existing_upload_contract(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "workspace.tar"
    source.write_bytes(b"archive-stream")
    uploads: list[tuple[str, bytes]] = []

    class Allocation:
        def write_file(self, path, value):
            assert (path, value) == ("/run/axrun/inputs-ready", b"ready\n")

        def upload_archive(self, path, chunk_factory):
            uploads.append((path, b"".join(chunk_factory())))

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-input")

        def allocation(self, _allocation_id):
            return Allocation()

        def wait_run(self, _run_id, timeout):
            return SimpleNamespace(exit_code=0, diagnostic_code="")

        def cancel_run(self, _run_id):
            pytest.fail("successful Run must not be cancelled")

    _run_input_stage(
        tmp_path,
        monkeypatch,
        Client(),
        InputFile(
            str(source), "/workspace", hashlib.sha256(source.read_bytes()).hexdigest(), archive=True
        ),
    )
    assert uploads == [("/workspace", b"archive-stream")]


@pytest.mark.parametrize("invalid_target", ["/opt/../escape", "/opt//escape", "/opt/.", "/opt/"])
def test_unsafe_regular_input_target_cancels_before_release(
    tmp_path: Path, monkeypatch, invalid_target: str
) -> None:
    source = tmp_path / "input.bin"
    source.write_bytes(b"x" * (513 << 10))
    events: list[str] = []

    class Allocation:
        def write_file(self, _path, _value):
            pytest.fail("unsafe input must not release the Run")

        def upload_archive(self, *_args):
            pytest.fail("unsafe input must not upload")

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-input")

        def allocation(self, _allocation_id):
            return Allocation()

        def cancel_run(self, run_id):
            events.append(f"cancelled:{run_id}")

    with pytest.raises(ContractError, match="normalized absolute file path"):
        _run_input_stage(tmp_path, monkeypatch, Client(), InputFile(str(source), invalid_target))
    assert events == ["cancelled:run-input"]


@pytest.mark.parametrize("error_kind", ["digest", "upload"])
def test_large_input_failure_cleans_spool_and_cancels_run(
    tmp_path: Path, monkeypatch, error_kind: str
) -> None:
    source = tmp_path / "input.whl"
    source.write_bytes(b"x" * (2 << 20))
    events: list[str] = []
    spools = []
    original_spooled_file = backend_module.tempfile.SpooledTemporaryFile

    def tracked_spooled_file(*args, **kwargs):
        spool = original_spooled_file(*args, **kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr(backend_module.tempfile, "SpooledTemporaryFile", tracked_spooled_file)

    class Allocation:
        def write_file(self, _path, _value):
            pytest.fail("failed upload must not release the Run")

        def upload_archive(self, _path, chunk_factory):
            events.append("upload")
            assert b"".join(chunk_factory())
            raise RuntimeError("upload failed")

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-input")

        def allocation(self, _allocation_id):
            return Allocation()

        def cancel_run(self, run_id):
            events.append(f"cancelled:{run_id}")

    expected = (
        "0" * 64 if error_kind == "digest" else hashlib.sha256(source.read_bytes()).hexdigest()
    )
    with pytest.raises((InfrastructureError, RuntimeError)):
        _run_input_stage(
            tmp_path,
            monkeypatch,
            Client(),
            InputFile(str(source), "/opt/inputs/input.whl", expected),
        )
    assert events == (
        ["cancelled:run-input"] if error_kind == "digest" else ["upload", "cancelled:run-input"]
    )
    assert len(spools) == 1 and spools[0].closed


def test_symlink_regular_source_cancels_before_release(tmp_path: Path, monkeypatch) -> None:
    actual = tmp_path / "actual.bin"
    actual.write_bytes(b"x" * (513 << 10))
    source = tmp_path / "linked.bin"
    source.symlink_to(actual)
    cancelled: list[str] = []

    class Allocation:
        def write_file(self, _path, _value):
            pytest.fail("symlink source must not release the Run")

        def upload_archive(self, *_args):
            pytest.fail("symlink source must not upload")

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-input")

        def allocation(self, _allocation_id):
            return Allocation()

        def cancel_run(self, run_id):
            cancelled.append(run_id)

    with pytest.raises(OSError):
        _run_input_stage(
            tmp_path, monkeypatch, Client(), InputFile(str(source), "/opt/inputs/linked.bin")
        )
    assert cancelled == ["run-input"]


@pytest.mark.parametrize(
    "network_policy", [StageNetworkPolicy.DENY_ALL, StageNetworkPolicy.UNRESTRICTED]
)
def test_backend_creates_run_without_private_execution_identity(
    tmp_path: Path, monkeypatch, network_policy: StageNetworkPolicy
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
            network_policy=network_policy,
        ),
        artifact_dir=tmp_path,
        on_bound=bound.append,
    )
    assert client.kwargs is not None
    assert "node_id" not in client.kwargs and "runtime_id" not in client.kwargs
    assert client.kwargs["request_cpu"] == "500m"
    assert client.kwargs["limit_memory"] == "2Gi"
    assert client.kwargs["argv"][:4] == [
        "/bin/sh",
        "-c",
        'rm -f "$1"; while [ ! -f "$1" ]; do sleep 0.1; done; shift; exec "$@"',
        "axrun",
    ]
    assert [value.run_id for value in bound] == ["run-1", "run-1"]
    assert bound[-1].allocation_id == "alloc-1"
    assert client.kwargs["rootfs_snapshot"] is False
    if network_policy == StageNetworkPolicy.DENY_ALL:
        assert isinstance(client.kwargs["network_policy"], NetworkPolicy)
    else:
        # The released SDK represents unrestricted egress by omitting the policy.
        assert "network_policy" not in client.kwargs


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


def test_derived_environment_cleanup_is_idempotent() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def delete_environment(self, environment_id: str) -> None:
            assert environment_id == "derived-env"
            self.calls += 1
            if self.calls > 1:
                raise SandboxNotFoundError(
                    operation="delete environment", code="NOT_FOUND", details="not found"
                )

    client = Client()
    backend = AxernBackend(client)
    backend.delete_environment("derived-env")
    backend.delete_environment("derived-env")
    assert client.calls == 2


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("exit_code", [23, 130])
def test_unsuccessful_workload_never_requests_a_usable_rootfs(
    tmp_path: Path, monkeypatch, recover, exit_code
) -> None:
    execution = ExecutionRef("base-env", "run-compile", "alloc-compile")
    stage = SimpleNamespace(execution=execution, exit_code=exit_code)

    class Client:
        def wait_rootfs_snapshot(self, *_args, **_kwargs):
            raise AssertionError("failed workload must not wait for or accept a derived image")

    backend = AxernBackend(Client())
    monkeypatch.setattr(backend, "recover" if recover else "_execute", lambda *a, **k: stage)
    plan = StagePlan("base-env", ("false",), "/workspace", ())
    if recover:
        result = backend.recover_rootfs(execution, plan, artifact_dir=tmp_path)
    else:
        result = backend.execute_rootfs(plan, artifact_dir=tmp_path, on_bound=lambda ref: None)
    assert result == (stage, "")


@pytest.mark.parametrize("recover", [False, True])
def test_sealing_failure_after_success_is_infrastructure_failure(
    tmp_path: Path, monkeypatch, recover
) -> None:
    execution = ExecutionRef("base-env", "run-compile", "alloc-compile")
    stage = SimpleNamespace(execution=execution, exit_code=0)

    class Client:
        def wait_rootfs_snapshot(self, *_args, **_kwargs):
            raise RuntimeError("registry sealing failed")

    backend = AxernBackend(Client())
    monkeypatch.setattr(backend, "recover" if recover else "_execute", lambda *a, **k: stage)
    plan = StagePlan("base-env", ("true",), "/workspace", ())
    with pytest.raises(InfrastructureError, match="rootfs result did not become ready"):
        if recover:
            backend.recover_rootfs(execution, plan, artifact_dir=tmp_path)
        else:
            backend.execute_rootfs(plan, artifact_dir=tmp_path, on_bound=lambda ref: None)


@pytest.mark.parametrize("recover", [False, True])
def test_rootfs_output_failure_cleans_derived_environment(
    tmp_path: Path, monkeypatch, recover
) -> None:
    execution = ExecutionRef("base-env", "run-compile", "alloc-compile")
    stage = SimpleNamespace(execution=execution, exit_code=0, artifacts=())

    class Client:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def wait_rootfs_snapshot(self, *_args, **_kwargs):
            return SimpleNamespace(
                environment_id="derived-env",
                image_ref=f"registry.invalid/rootfs@sha256:{'a' * 64}",
                platform_os="linux",
                platform_arch="amd64",
            )

        def delete_environment(self, environment_id: str) -> None:
            self.deleted.append(environment_id)

    client = Client()
    backend = AxernBackend(client)
    monkeypatch.setattr(backend, "recover" if recover else "_execute", lambda *a, **k: stage)
    monkeypatch.setattr(
        backend,
        "_download_outputs",
        lambda *a, **k: (_ for _ in ()).throw(ContractError("missing evaluator result")),
    )
    plan = StagePlan("base-env", ("true",), "/workspace", ())
    with pytest.raises(InfrastructureError, match="rootfs workload output"):
        if recover:
            backend.recover_rootfs(execution, plan, artifact_dir=tmp_path)
        else:
            backend.execute_rootfs(plan, artifact_dir=tmp_path, on_bound=lambda ref: None)
    assert client.deleted == ["derived-env"]


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


def _sealed_output(
    path: str = "/outputs/result", output_id: str = "output-1", payload: bytes = b"sealed"
) -> SimpleNamespace:
    return SimpleNamespace(
        path=path,
        output_id=output_id,
        status="available",
        reason="",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        media_type="application/octet-stream",
    )


@pytest.mark.parametrize("duplicate", ["path", "output_id", "empty_output_id"])
def test_sealed_manifest_ambiguous_identity_is_rejected_before_download(
    tmp_path: Path, duplicate: str
) -> None:
    first = _sealed_output()
    second = _sealed_output("/outputs/other", "output-2")
    if duplicate == "path":
        second.path = first.path
    elif duplicate == "output_id":
        second.output_id = first.output_id
    else:
        first.output_id = ""

    class Client:
        def get_sealed_output_manifest(self, _run_id):
            return [first, second]

        def download_sealed_output(self, *_args):
            pytest.fail("ambiguous identity must not reach download")

    with pytest.raises(InfrastructureError, match="manifest identity is ambiguous"):
        AxernBackend(Client())._download_outputs(
            "run", StagePlan("env", ("true",), "/workspace", (OutputSpec(first.path),)), tmp_path
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("size_bytes", -1),
        ("size_bytes", True),
        ("sha256", "bad-digest"),
        ("media_type", "text/plain"),
    ],
)
def test_sealed_manifest_invalid_metadata_is_rejected_before_download(
    tmp_path: Path, field: str, value: object
) -> None:
    sealed = _sealed_output()
    setattr(sealed, field, value)

    class Client:
        def get_sealed_output_manifest(self, _run_id):
            return [sealed]

        def download_sealed_output(self, *_args):
            pytest.fail("invalid metadata must not reach download")

    with pytest.raises(InfrastructureError, match=r"manifest .* is invalid"):
        AxernBackend(Client())._download_outputs(
            "run", StagePlan("env", ("true",), "/workspace", (OutputSpec(sealed.path),)), tmp_path
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("output_id", "foreign-output"),
        ("path", "/outputs/foreign"),
        ("size_bytes", 7),
        ("sha256", "c" * 64),
        ("media_type", "text/plain"),
        ("status", "missing"),
    ],
)
def test_downloaded_metadata_must_match_original_sealed_manifest(
    tmp_path: Path, field: str, value: object
) -> None:
    sealed = _sealed_output()
    returned = SimpleNamespace(**vars(sealed))
    setattr(returned, field, value)

    class Client:
        def get_sealed_output_manifest(self, _run_id):
            return [sealed]

        def download_sealed_output(self, run_id, output_id, stream):
            assert (run_id, output_id) == ("run", sealed.output_id)
            stream.write(b"sealed")
            return returned

    with pytest.raises(InfrastructureError, match="metadata changed during download"):
        AxernBackend(Client())._download_outputs(
            "run", StagePlan("env", ("true",), "/workspace", (OutputSpec(sealed.path),)), tmp_path
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("payload", [b"short", b"forged"])
def test_downloaded_bytes_are_independently_checked_before_publication(
    tmp_path: Path, payload: bytes
) -> None:
    sealed = _sealed_output()

    class Client:
        def get_sealed_output_manifest(self, _run_id):
            return [sealed]

        def download_sealed_output(self, _run_id, _output_id, stream):
            stream.write(payload)
            return sealed

    with pytest.raises(InfrastructureError, match="failed integrity check"):
        AxernBackend(Client())._download_outputs(
            "run", StagePlan("env", ("true",), "/workspace", (OutputSpec(sealed.path),)), tmp_path
        )
    assert not list(tmp_path.iterdir())


def test_download_interruption_preserves_published_outputs_and_removes_only_own_partial(
    tmp_path: Path,
) -> None:
    first = _sealed_output("/outputs/first", "output-first")
    second = _sealed_output("/outputs/second", "output-second")
    untouched = tmp_path / "caller-owned.txt"
    untouched.write_bytes(b"retain")

    class Client:
        def get_sealed_output_manifest(self, _run_id):
            return [first, second]

        def download_sealed_output(self, _run_id, output_id, stream):
            if output_id == first.output_id:
                stream.write(b"sealed")
                return first
            stream.write(b"partial")
            raise ConnectionError("private-header-never-echo")

    with pytest.raises(InfrastructureError, match="sealed output download failed") as raised:
        AxernBackend(Client())._download_outputs(
            "run",
            StagePlan(
                "env", ("true",), "/workspace", (OutputSpec(first.path), OutputSpec(second.path))
            ),
            tmp_path,
        )
    assert "private-header-never-echo" not in str(raised.value)
    assert (tmp_path / "00-first").read_bytes() == b"sealed"
    assert not (tmp_path / "01-second").exists()
    assert untouched.read_bytes() == b"retain"
    assert {path.name for path in tmp_path.iterdir()} == {"00-first", "caller-owned.txt"}


def test_recover_redownloads_interrupted_sealed_output_from_original_run(
    tmp_path: Path, monkeypatch
) -> None:
    sealed = _sealed_output()
    calls: list[tuple[str, str]] = []

    class Client:
        def get_run(self, run_id):
            assert run_id == "persisted-run"
            return SimpleNamespace(
                id=run_id,
                environment_id="env",
                allocation_id="persisted-allocation",
                exit_code=0,
                diagnostic_code="",
            )

        def get_sealed_output_manifest(self, run_id):
            assert run_id == "persisted-run"
            return [sealed]

        def download_sealed_output(self, run_id, output_id, stream):
            calls.append((run_id, output_id))
            if len(calls) == 1:
                stream.write(b"partial")
                raise ConnectionError("partition")
            stream.write(b"sealed")
            return sealed

        def create_run(self, **_kwargs):
            pytest.fail("recovery must not re-execute the stage")

    backend = AxernBackend(Client())
    monkeypatch.setattr(backend_module, "_status_name", lambda _run: "RUN_STATUS_SUCCEEDED")
    monkeypatch.setattr(
        backend, "_capture_output", lambda *_args, **_kwargs: (tmp_path / "out", tmp_path / "err")
    )
    execution = ExecutionRef("env", "persisted-run", "persisted-allocation")
    plan = StagePlan("env", ("true",), "/workspace", (OutputSpec(sealed.path),))
    with pytest.raises(InfrastructureError, match="sealed output download failed"):
        backend.recover(execution, plan, artifact_dir=tmp_path)
    assert not list(tmp_path.iterdir())
    result = backend.recover(execution, plan, artifact_dir=tmp_path)
    assert result is not None and result.execution == execution
    assert len(result.artifacts) == 1
    assert calls == [("persisted-run", sealed.output_id), ("persisted-run", sealed.output_id)]
    artifact = result.artifacts[0]
    assert Path(artifact.path).read_bytes() == b"sealed"
    assert (artifact.size_bytes, artifact.sha256) == (sealed.size_bytes, sealed.sha256)
    assert {path.name for path in tmp_path.iterdir()} == {"00-result"}


def test_recovery_rejects_plan_environment_before_querying_run(tmp_path: Path) -> None:
    class Client:
        def get_run(self, _run_id):
            pytest.fail("conflicting local recovery identities must not query the Run")

    with pytest.raises(InfrastructureError, match="plan differs from the persisted Environment"):
        AxernBackend(Client()).recover(
            ExecutionRef("env-original", "run-original", "alloc-original"),
            StagePlan("env-other", ("true",), "/workspace", ()),
            artifact_dir=tmp_path,
        )


@pytest.mark.parametrize(
    ("field", "value", "persisted_allocation_id"),
    [
        ("id", "private-foreign-run", "alloc-original"),
        ("environment_id", "private-foreign-environment", "alloc-original"),
        ("environment_id", "private-foreign-environment", ""),
        ("environment_id", None, ""),
        ("allocation_id", "private-foreign-allocation", "alloc-original"),
        ("allocation_id", "", "alloc-original"),
        ("allocation_id", None, ""),
    ],
)
@pytest.mark.parametrize("status", ["RUN_STATUS_RUNNING", "RUN_STATUS_SUCCEEDED"])
def test_recovery_rejects_foreign_public_execution_before_dataplane(
    tmp_path: Path,
    monkeypatch,
    field: str,
    value: object,
    persisted_allocation_id: str,
    status: str,
) -> None:
    run = SimpleNamespace(
        id="run-original",
        environment_id="env-original",
        allocation_id="alloc-original",
        exit_code=0,
        diagnostic_code="",
    )
    setattr(run, field, value)

    class Client:
        def get_run(self, run_id):
            assert run_id == "run-original"
            return run

    backend = AxernBackend(Client())
    monkeypatch.setattr(backend_module, "_status_name", lambda _run: status)
    monkeypatch.setattr(
        backend,
        "_download_outputs",
        lambda *_args, **_kwargs: pytest.fail("foreign execution must not download outputs"),
    )
    monkeypatch.setattr(
        backend,
        "_capture_output",
        lambda *_args, **_kwargs: pytest.fail("foreign execution must not read logs"),
    )
    with pytest.raises(InfrastructureError, match="persisted Axern execution") as raised:
        backend.recover(
            ExecutionRef("env-original", "run-original", persisted_allocation_id),
            StagePlan("env-original", ("true",), "/workspace", ()),
            artifact_dir=tmp_path,
        )
    assert "private" not in str(raised.value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("allocation_bound", [False, True])
def test_recovery_preserves_original_run_and_accepts_new_allocation_binding(
    tmp_path: Path, monkeypatch, allocation_bound: bool
) -> None:
    run = SimpleNamespace(
        id="run-original",
        environment_id="env-original",
        allocation_id="alloc-original" if allocation_bound else "",
        exit_code=0,
        diagnostic_code="",
    )

    class Client:
        def get_run(self, run_id):
            assert run_id == "run-original"
            return run

    backend = AxernBackend(Client())
    monkeypatch.setattr(
        backend_module,
        "_status_name",
        lambda _run: "RUN_STATUS_SUCCEEDED" if allocation_bound else "RUN_STATUS_PENDING",
    )
    monkeypatch.setattr(
        backend, "_capture_output", lambda *_args, **_kwargs: (tmp_path / "out", tmp_path / "err")
    )
    result = backend.recover(
        ExecutionRef("env-original", "run-original"),
        StagePlan("env-original", ("true",), "/workspace", ()),
        artifact_dir=tmp_path,
    )
    if allocation_bound:
        assert result is not None
        assert result.execution == ExecutionRef("env-original", "run-original", "alloc-original")
    else:
        assert result is None


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


def test_allocation_readiness_failure_cancels_before_release(tmp_path: Path, monkeypatch) -> None:
    class Client:
        def __init__(self) -> None:
            self.cancelled: list[str] = []

        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-placed")

        def cancel_run(self, run_id: str) -> None:
            self.cancelled.append(run_id)

    client = Client()
    backend = AxernBackend(client)
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("cold image")),
    )
    with pytest.raises(TimeoutError, match="cold image"):
        backend.execute(
            StagePlan("env", ("true",), "/workspace", ()),
            artifact_dir=tmp_path,
            on_bound=lambda _ref: None,
        )
    assert client.cancelled == ["run-placed"]


@pytest.mark.parametrize("failure", ["run_binding", "allocation_binding", "allocation_handle"])
def test_binding_and_handle_failures_cancel_the_new_unreleased_run(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    events: list[str] = []

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-unreleased")

        def allocation(self, allocation_id):
            assert allocation_id == "alloc-unreleased"
            events.append("allocation_handle")
            if failure == "allocation_handle":
                raise ContractError("allocation handle unavailable")
            pytest.fail("a rejected binding cannot obtain an Allocation handle")

        def cancel_run(self, run_id):
            events.append(f"cancelled:{run_id}")

    def bind(execution: ExecutionRef) -> None:
        kind = "allocation_binding" if execution.allocation_id else "run_binding"
        events.append(kind)
        if kind == failure:
            raise ContractError("local execution identity rejected")

    backend = AxernBackend(Client())
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: SimpleNamespace(
            id="run-unreleased", allocation_id="alloc-unreleased"
        ),
    )
    with pytest.raises(ContractError):
        backend.execute(
            StagePlan("env", ("true",), "/workspace", ()),
            artifact_dir=tmp_path,
            on_bound=bind,
        )
    assert events[-1] == "cancelled:run-unreleased"
    assert events.count("cancelled:run-unreleased") == 1
    assert (
        events[:-1]
        == {
            "run_binding": ["run_binding"],
            "allocation_binding": ["run_binding", "allocation_binding"],
            "allocation_handle": ["run_binding", "allocation_binding", "allocation_handle"],
        }[failure]
    )


def test_prestart_cleanup_failure_still_cancels_and_does_not_echo_secret(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []

    class Lifecycle:
        def start(self, _execution, _allocation):
            events.append("prestart")
            raise ContractError("preflight rejected")

        def close(self):
            events.append("cleanup_failed")
            raise RuntimeError("private-token-never-echo")

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-unreleased")

        def allocation(self, _allocation_id):
            return object()

        def cancel_run(self, run_id):
            events.append(f"cancelled:{run_id}")

    backend = AxernBackend(Client())
    monkeypatch.setattr(
        backend_module,
        "_wait_running",
        lambda *_args, **_kwargs: SimpleNamespace(
            id="run-unreleased", allocation_id="alloc-unreleased"
        ),
    )
    with pytest.raises(InfrastructureError, match="lifecycle_cleanup_failed") as raised:
        backend.execute(
            StagePlan("env", ("true",), "/workspace", ()),
            artifact_dir=tmp_path,
            on_bound=lambda _execution: None,
            lifecycle=Lifecycle(),
        )
    assert "private-token-never-echo" not in str(raised.value)
    assert events == ["prestart", "cleanup_failed", "cancelled:run-unreleased"]


def test_unreleased_cancel_failure_has_safe_diagnostic(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []

    class Client:
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-unreleased")

        def cancel_run(self, run_id):
            events.append(f"cancelled:{run_id}")
            raise RuntimeError("private-response-body-never-echo")

    def reject_binding(_execution: ExecutionRef) -> None:
        raise ContractError("local execution identity rejected")

    backend = AxernBackend(Client())
    monkeypatch.setattr(
        backend_module, "_wait_running", lambda *_args, **_kwargs: pytest.fail("binding rejected")
    )
    with pytest.raises(InfrastructureError, match="unreleased_run_cancel_failed") as raised:
        backend.execute(
            StagePlan("env", ("true",), "/workspace", ()),
            artifact_dir=tmp_path,
            on_bound=reject_binding,
        )
    assert events == ["cancelled:run-unreleased"]
    assert "private-response-body-never-echo" not in str(raised.value)


def test_recovery_normalizes_unset_exit_code_on_failed_run(tmp_path: Path, monkeypatch) -> None:
    failed = SimpleNamespace(
        id="run-failed",
        environment_id="env",
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
