from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from axrun.errors import ContractError
from axrun.models import (
    Artifact,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageResult,
    VerifierSpec,
)
from axrun.qualification import qualify_episode

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
        "d" * 40,
        str(prompt),
        "env-inference",
        "env-verification",
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
        VerifierSpec("synthetic-code-task", "1"),
        metadata={"task_image": _TASK_IMAGE},
    )


class Client:
    def __init__(self, image: str = _TASK_IMAGE) -> None:
        self.image = image

    def get_environment(self, _environment_id: str):
        return SimpleNamespace(spec=SimpleNamespace(image=SimpleNamespace(ref=self.image)))


class Backend:
    def __init__(self) -> None:
        self.plan = None

    def execute(self, plan, *, artifact_dir, on_bound, lifecycle=None):
        assert lifecycle is None
        self.plan = plan
        execution = ExecutionRef(plan.environment_id, "run-qualification", "alloc-qualification")
        on_bound(execution)
        payload = {
            "schema_version": 1,
            "base_commit": "d" * 40,
            "git": "git version 2.51.0",
            "machine": "aarch64",
            "python": "3.12.11",
            "working_directory": "/workspace",
            "claude": {
                "entry": "/__claude_code/usr/local/bin/claude",
                "mount_readonly": True,
                "node_version": "v22.23.2",
                "version": "2.1.205 (Claude Code)",
            },
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
        _episode(tmp_path), client=Client(), backend=backend, state_root=tmp_path / "state"
    )

    assert result.run_id == "run-qualification"
    assert result.environment_image == _TASK_IMAGE
    assert result.checks["claude"]["mount_readonly"] is True
    assert backend.plan.network_policy == "deny_all"
    assert backend.plan.env == {} and backend.plan.secret_env == ()
    assert backend.plan.image_mounts[0].image == _CLAUDE_IMAGE
    assert backend.plan.image_mounts[0].readonly is True
    evidence = (
        tmp_path
        / "state"
        / "qualifications"
        / "episode"
        / _episode(tmp_path).digest
        / "run-qualification.json"
    )
    assert json.loads(evidence.read_text())["output_sha256"] == result.output_sha256


def test_qualification_rejects_mutable_environment_image(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="must use an OCI sha256 digest"):
        qualify_episode(
            _episode(tmp_path),
            client=Client("registry.example/task:latest"),
            backend=Backend(),
            state_root=tmp_path / "state",
        )


def test_qualification_rejects_environment_image_drift(tmp_path: Path) -> None:
    other = f"registry.example/task@sha256:{'e' * 64}"
    with pytest.raises(ContractError, match="differs from the resolved episode"):
        qualify_episode(
            _episode(tmp_path),
            client=Client(other),
            backend=Backend(),
            state_root=tmp_path / "state",
        )
