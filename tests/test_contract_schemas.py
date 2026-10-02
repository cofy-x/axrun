"""The published schemas must describe bytes written by Axrun's serializers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from axrun.adapters._candidate import load_candidate, persist_candidate
from axrun.models import (
    Artifact,
    CandidateSpec,
    EnvironmentBinding,
    ExecutionRef,
    HarnessSpec,
    ResolvedEpisode,
    StageNetworkPolicy,
    StageResult,
    TaskSpec,
    VerifierSpec,
    canonical_digest,
)
from axrun.store import EpisodeStore

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _episode(tmp_path: Path) -> ResolvedEpisode:
    return ResolvedEpisode(
        schema_version=1,
        episode_id="episode-1",
        task_id="task-1",
        seed_digest="a" * 64,
        prompt_file=str(tmp_path / "prompt.txt"),
        task=TaskSpec("git-worktree", "1", {"base_commit": "b" * 40}),
        inference_environment=EnvironmentBinding(
            "env-i", f"registry.invalid/task@sha256:{'c' * 64}", "linux/amd64", "/workspace"
        ),
        verification_environment=EnvironmentBinding(
            "env-v", f"registry.invalid/task@sha256:{'d' * 64}", "linux/amd64", "/workspace"
        ),
        harness=HarnessSpec("static-candidate", "1", config={"inputs": ["prompt.txt"]}),
        candidate=CandidateSpec("git-patch", "1", {"format": "patch"}),
        verifier=VerifierSpec("command-verifier", "1"),
        metadata={"suite": "contract"},
    )


@pytest.mark.parametrize("version", [1, 2])
def test_persisted_resolved_episode_matches_versioned_schema(tmp_path: Path, version: int) -> None:
    episode = _episode(tmp_path)
    if version == 2:
        episode = replace(
            episode,
            schema_version=2,
            inference_network_policy=StageNetworkPolicy.UNRESTRICTED,
            verification_network_policy=StageNetworkPolicy.DENY_ALL,
        )
    store = EpisodeStore(tmp_path / "state")
    record = store.initialize(episode)
    raw = json.loads(store.spec_path_for(episode.episode_id).read_text(encoding="utf-8"))
    _validator(f"resolved-episode-v{version}.schema.json").validate(raw)
    assert record.spec_digest == canonical_digest(raw) == episode.digest
    assert store.load_spec(episode.episode_id) == episode
    assert ("inference_network_policy" in raw) is (version == 2)


def test_resolved_episode_schema_rejects_stale_and_cross_version_fields(tmp_path: Path) -> None:
    raw = _episode(tmp_path).as_dict()
    validator = _validator("resolved-episode-v1.schema.json")
    validator.validate(raw)
    raw["base_commit"] = "b" * 40
    with pytest.raises(ValidationError):
        validator.validate(raw)
    raw.pop("base_commit")
    raw["inference_environment_id"] = raw.pop("inference_environment")["environment_id"]
    with pytest.raises(ValidationError):
        validator.validate(raw)
    raw = _episode(tmp_path).as_dict()
    raw["schema_version"] = 2
    with pytest.raises(ValidationError):
        _validator("resolved-episode-v2.schema.json").validate(raw)


def test_persisted_candidate_manifest_matches_schema(tmp_path: Path) -> None:
    episode = _episode(tmp_path)
    output = tmp_path / "candidate.patch"
    output.write_bytes(b"diff --git a/a b/a\n")
    artifact = Artifact(
        "/outputs/candidate.patch",
        str(output),
        output.stat().st_size,
        hashlib.sha256(output.read_bytes()).hexdigest(),
        "text/x-patch",
    )
    result = StageResult(ExecutionRef("env-i", "run-i", "alloc-i"), 0, "", (artifact,))
    bundle = persist_candidate(
        episode,
        result,
        destination=tmp_path / "candidates",
        required_outputs=(("patch", artifact.name),),
        harness=episode.harness.identity,
        harness_version=episode.harness.version,
    )
    path = Path(bundle.root) / "candidate-manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    validator = _validator("candidate-bundle-v1.schema.json")
    validator.validate(raw)
    assert load_candidate(path) == bundle
    assert raw["digest"] == canonical_digest(
        {key: value for key, value in raw.items() if key != "digest"}
    )
    assert raw["files"][0]["role"] == "patch"
    assert "base_commit" not in raw
    raw["files"][0].pop("role")
    with pytest.raises(ValidationError):
        validator.validate(raw)
