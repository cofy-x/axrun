from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from axrun.errors import ContractError
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
from axrun.qualification import qualify_episode
from axrun.store import EpisodeStore

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
