from __future__ import annotations

import hashlib
import json
from pathlib import Path

from axrun.adapters._candidate import persist_candidate
from axrun.models import (
    Artifact,
    ExecutionRef,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    StageResult,
    VerificationResult,
)
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore


class FakeBackend:
    def __init__(self) -> None:
        self.executions = 0

    def execute(self, plan, *, artifact_dir, on_bound):
        self.executions += 1
        stage = "inference" if self.executions == 1 else "verification"
        ref = ExecutionRef(plan.environment_id, f"run-{stage}", f"alloc-{stage}")
        on_bound(ref)
        return self._result(plan, artifact_dir, ref)

    def _result(self, plan, artifact_dir, ref):
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for index, output in enumerate(plan.outputs):
            path = artifact_dir / f"{index}.out"
            payload = (
                b'{"resolved":true,"score":1.0}'
                if output.path.endswith("verification.json")
                else b"candidate"
            )
            path.write_bytes(payload)
            artifacts.append(
                Artifact(
                    output.path,
                    str(path),
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                    output.media_type,
                )
            )
        return StageResult(ref, 0, "", tuple(artifacts))

    def recover(self, execution, plan, *, artifact_dir):
        return self._result(plan, artifact_dir, execution)


class Inference:
    name = "fake"

    def plan(self, episode):
        return StagePlan(
            episode.inference_environment_id,
            ("agent",),
            "/workspace",
            (OutputSpec("/outputs/candidate.patch"),),
        )

    def build_candidate(self, episode, result, *, destination):
        return persist_candidate(
            episode,
            result,
            destination=destination,
            required_paths=("/outputs/candidate.patch",),
        )


class Verifier:
    name = "fake-verifier"

    def plan(self, episode, candidate):
        return StagePlan(
            episode.verification_environment_id,
            ("verify",),
            "/workspace",
            (OutputSpec("/outputs/verification.json", media_type="application/json"),),
        )

    def parse_result(self, result):
        raw = json.loads(Path(result.artifacts[0].path).read_text())
        return VerificationResult(1, raw["resolved"], raw["score"], self.name)


def test_runner_uses_two_allocations_and_persists_result(tmp_path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("task", encoding="utf-8")
    episode = ResolvedEpisode(1, "ep", "task", "digest", "a" * 40, str(prompt), "env-i", "env-v")
    backend = FakeBackend()
    runner = EpisodeRunner(backend=backend, store=EpisodeStore(tmp_path / "state"))

    result = runner.run(episode, inference=Inference(), verifier=Verifier())

    assert result.resolved is True
    assert backend.executions == 2
    record = runner.store.load("ep")
    assert record is not None
    assert record.inference is not None and record.verification is not None
    assert record.inference.allocation_id != record.verification.allocation_id
    candidate = runner._load_candidate(record)
    assert all("/candidates/ep/" in artifact.path for artifact in candidate.artifacts)


def test_runner_recovers_terminal_inference_without_rerunning_it(tmp_path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("task", encoding="utf-8")
    episode = ResolvedEpisode(
        1, "recover", "task", "digest", "a" * 40, str(prompt), "env-i", "env-v"
    )
    store = EpisodeStore(tmp_path / "state")
    from axrun.models import EpisodePhase, EpisodeRecord

    store.save(
        EpisodeRecord(
            schema_version=1,
            episode=episode,
            phase=EpisodePhase.INFERENCE_RUNNING,
            inference=ExecutionRef("env-i", "run-inference", "alloc-inference"),
        )
    )
    backend = FakeBackend()
    runner = EpisodeRunner(backend=backend, store=store)

    result = runner.recover("recover", inference=Inference(), verifier=Verifier())

    assert result.resolved is True
    assert backend.executions == 1
    record = store.load("recover")
    assert record is not None and record.phase == EpisodePhase.COMPLETED
