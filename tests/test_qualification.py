from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from axrun.catalog import resolve_adapters
from axrun.errors import ContractError, InfrastructureError, RecoveryRequiredError
from axrun.models import (
    Artifact,
    CandidateSpec,
    EnvironmentBinding,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageResult,
    TaskSpec,
    VerifierSpec,
)
from axrun.qualification import load_qualification_result, qualify_episode
from axrun.store import EpisodeStore
from axrun.tasks import GitWorktreeTaskAdapter

_TASK_IMAGE = f"registry.example/task@sha256:{'a' * 64}"
_CLAUDE_IMAGE = f"registry.example/claude@sha256:{'b' * 64}"


def _episode(tmp_path: Path) -> ResolvedEpisode:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("task", encoding="utf-8")
    return ResolvedEpisode(
        1,
        "episode",
        "task",
        "c" * 64,
        str(prompt),
        TaskSpec("git-worktree", "1", {"base_commit": "d" * 40}),
        EnvironmentBinding("env-inference", _TASK_IMAGE, "linux/arm64", "/workspace"),
        EnvironmentBinding("env-verification", _TASK_IMAGE, "linux/arm64", "/workspace"),
        HarnessSpec(
            "claude-code",
            "2.1.205",
            config={
                "mount_image": _CLAUDE_IMAGE,
                "model": "opaque-model",
                "default_opus_model": "opaque-model",
                "default_sonnet_model": "opaque-model",
                "default_haiku_model": "opaque-model",
                "subagent_model": "opaque-model",
                "max_turns": 40,
                "working_directory": "/workspace",
                "disallowed_tools": ["WebFetch", "WebSearch"],
            },
        ),
        CandidateSpec("git-patch", "1"),
        VerifierSpec("synthetic-code-task", "1"),
    )


class Client:
    def __init__(self, image: str = _TASK_IMAGE) -> None:
        self.image = image

    def get_environment(self, _environment_id: str):
        return SimpleNamespace(spec=SimpleNamespace(image=SimpleNamespace(ref=self.image)))


class Backend:
    def __init__(self) -> None:
        self.plans = []

    def execute(self, plan, *, artifact_dir, on_bound, lifecycle=None):
        assert lifecycle is None
        self.plans.append(plan)
        role = plan.labels["axrun.qualification.role"]
        execution = ExecutionRef(
            plan.environment_id, f"run-{role}-qualification", f"alloc-{role}-qualification"
        )
        on_bound(execution)
        payload = {
            "schema_version": 1,
            "role": role,
            "base_commit": "d" * 40,
            "git": "git version 2.51.0",
            "machine": "aarch64",
            "python": "3.12.11",
            "working_directory": "/workspace",
            "workspace_empty": None,
            "workspace_files": None,
            "archive_module": False,
            "verifier_file": False,
            "claude": (
                {
                    "entry": "/__claude_code/usr/local/bin/claude",
                    "mount_readonly": True,
                    "node_version": "v22.23.2",
                    "version": "2.1.205 (Claude Code)",
                }
                if role == "inference"
                else None
            ),
        }
        data = json.dumps(payload).encode()
        path = artifact_dir / "qualification.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        artifact = Artifact(
            "/outputs/qualification.json",
            str(path),
            len(data),
            hashlib.sha256(data).hexdigest(),
            "application/json",
        )
        return StageResult(execution, 0, "", (artifact,))

    def recover(self, execution, plan, *, artifact_dir):
        raise AssertionError("qualification is a new bounded Run")

    def cancel(self, execution):
        raise AssertionError("qualification should not be cancelled")

    def wait(self, execution, *, timeout=None):
        raise AssertionError("qualification should not be recovered")


def test_qualification_is_model_free_deny_all_and_digest_pinned(tmp_path: Path) -> None:
    backend = Backend()
    result = qualify_episode(
        _episode(tmp_path),
        client=Client(),
        backend=backend,
        store=EpisodeStore(tmp_path / "state"),
    )

    assert result.targets[0].run_id == "run-inference-qualification"
    assert result.targets[0].environment_image == _TASK_IMAGE
    assert result.targets[0].checks["claude"]["mount_readonly"] is True
    assert result.targets[1].checks["claude"] is None
    assert all(plan.network_policy == "deny_all" for plan in backend.plans)
    assert all(plan.env == {} and plan.secret_env == () for plan in backend.plans)
    assert backend.plans[0].image_mounts[0].image == _CLAUDE_IMAGE
    assert backend.plans[0].image_mounts[0].readonly is True
    assert backend.plans[1].image_mounts == ()
    evidence = (
        tmp_path
        / "state"
        / "qualifications"
        / "episode"
        / _episode(tmp_path).digest
        / "result.json"
    )
    assert (
        json.loads(evidence.read_text())["targets"][0]["output_sha256"]
        == result.targets[0].output_sha256
    )


class DisconnectedBackend(Backend):
    def __init__(self) -> None:
        super().__init__()
        self.original = None
        self.recovered = []
        self.active = False

    def execute(self, plan, *, artifact_dir, on_bound, lifecycle=None):
        stage = super().execute(plan, artifact_dir=artifact_dir, on_bound=on_bound)
        if self.original is None:
            self.original = stage
            raise ConnectionError("caller disconnected after Run binding")
        return stage

    def recover(self, execution, plan, *, artifact_dir):
        self.recovered.append(execution)
        assert self.original is not None
        assert execution == self.original.execution
        return None if self.active else self.original


def test_qualification_disconnect_recovers_original_run_without_resubmission(tmp_path: Path):
    episode, backend, store = (
        _episode(tmp_path),
        DisconnectedBackend(),
        EpisodeStore(tmp_path / "state"),
    )
    with pytest.raises(ConnectionError):
        qualify_episode(episode, client=Client(), backend=backend, store=store)
    record = store.load(episode.episode_id)
    assert record is not None
    assert record.qualifications == (backend.original.execution,)
    backend.active = True
    with pytest.raises(RecoveryRequiredError, match="still active"):
        qualify_episode(episode, client=Client(), backend=backend, store=store)
    assert len(backend.plans) == 1
    backend.active = False
    result = qualify_episode(episode, client=Client(), backend=backend, store=store)
    assert result.targets[0].run_id == backend.original.execution.run_id
    assert len(backend.plans) == 2  # Only the not-yet-submitted verification qualification is new.
    assert backend.recovered == [backend.original.execution] * 2


def test_qualification_recovery_independently_rechecks_sealed_output(tmp_path: Path):
    episode, backend, store = (
        _episode(tmp_path),
        DisconnectedBackend(),
        EpisodeStore(tmp_path / "state"),
    )
    with pytest.raises(ConnectionError):
        qualify_episode(episode, client=Client(), backend=backend, store=store)
    assert backend.original is not None
    Path(backend.original.artifacts[0].path).write_bytes(b"tampered")
    with pytest.raises(InfrastructureError, match="sealed output integrity"):
        qualify_episode(episode, client=Client(), backend=backend, store=store)
    assert len(backend.plans) == 1


def test_qualification_rejects_execution_environment_drift(tmp_path: Path):
    episode, store = _episode(tmp_path), EpisodeStore(tmp_path / "state")
    qualify_episode(episode, client=Client(), backend=Backend(), store=store)
    record = store.load(episode.episode_id)
    assert record is not None
    record.qualifications = (
        replace(record.qualifications[0], environment_id="env-foreign"),
        record.qualifications[1],
    )
    store.save(record)
    with pytest.raises(ContractError, match="provenance mismatch"):
        load_qualification_result(store, episode)


def test_explicit_selection_qualifies_closed_task_before_catalog_registration(
    tmp_path: Path,
) -> None:
    registered = _episode(tmp_path)
    episode = replace(
        registered,
        task=TaskSpec("closed-official-task", "1", {"base_commit": "d" * 40}),
    )
    selection = replace(
        resolve_adapters(registered),
        task=GitWorktreeTaskAdapter(name="closed-official-task"),
    )
    backend = Backend()
    store = EpisodeStore(tmp_path / "closed-state")

    with pytest.raises(ContractError, match="unsupported task adapter"):
        qualify_episode(episode, client=Client(), backend=backend, store=store)
    assert backend.plans == []

    result = qualify_episode(
        episode, client=Client(), backend=backend, store=store, selection=selection
    )
    assert [target.role for target in result.targets] == ["inference", "verification"]
    assert len(backend.plans) == 2
    assert load_qualification_result(store, episode, selection=selection) == result
    assert (
        qualify_episode(episode, client=Client(), backend=backend, store=store, selection=selection)
        == result
    )
    assert len(backend.plans) == 2
    with pytest.raises(ContractError, match="unsupported task adapter"):
        load_qualification_result(store, episode)


def test_qualification_rejects_mutable_environment_image(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="must use an OCI sha256 digest"):
        qualify_episode(
            _episode(tmp_path),
            client=Client("registry.example/task:latest"),
            backend=Backend(),
            store=EpisodeStore(tmp_path / "state"),
        )


def test_qualification_rejects_environment_image_drift(tmp_path: Path) -> None:
    other = f"registry.example/task@sha256:{'e' * 64}"
    with pytest.raises(ContractError, match="differs from the resolved episode"):
        qualify_episode(
            _episode(tmp_path),
            client=Client(other),
            backend=Backend(),
            store=EpisodeStore(tmp_path / "state"),
        )


def test_prepared_contains_qualification_allows_locked_seed_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = workspace / "executable"
    executable.write_text("reference")
    executable.chmod(0o111)
    (workspace / "source.c").write_text("int main(void) { return 0; }\n")
    output = tmp_path / "qualification.json"
    script = Path(__file__).parents[1] / "src" / "axrun" / "fixtures" / "qualification" / "run.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--role",
            "inference",
            "--workspace",
            str(workspace),
            "--require-workspace-files",
            "--required-workspace-file",
            "111:executable",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text())["workspace_files"] == [
        {"mode": 0o111, "path": "executable"}
    ]


def test_prepared_workspace_qualification_checks_exact_file_and_mode(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = workspace / "executable"
    executable.write_text("reference", encoding="utf-8")
    executable.chmod(0o111)
    output = tmp_path / "qualification.json"
    fixture = Path(__file__).parents[1] / "src" / "axrun" / "fixtures" / "qualification" / "run.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(fixture),
            "--role",
            "inference",
            "--workspace",
            str(workspace),
            "--require-exact-workspace-files",
            "--required-workspace-file",
            "111:executable",
            "--output",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["workspace_empty"] is False
    assert payload["workspace_files"] == [{"mode": 0o111, "path": "executable"}]

    (workspace / "unexpected").mkdir()
    rejected = subprocess.run(
        [
            sys.executable,
            str(fixture),
            "--role",
            "inference",
            "--workspace",
            str(workspace),
            "--require-exact-workspace-files",
            "--required-workspace-file",
            "111:executable",
            "--output",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert rejected.returncode != 0
