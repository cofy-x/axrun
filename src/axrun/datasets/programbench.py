"""Resolver for one upstream ProgramBench compatibility fixture.

This adapter intentionally accepts only ProgramBench's own calculator test fixture.  It proves
the task/candidate/verifier composition without claiming coverage of the 200 benchmark instances.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError
from axrun.harnesses import resolve_claude_code_spec
from axrun.models import (
    CandidateSpec,
    EnvironmentBinding,
    HarnessSpec,
    ResolvedEpisode,
    TaskSpec,
    VerifierSpec,
    canonical_digest,
)

_IDENTITY = "axrun.programbench-compatibility"
_VERSION = "programbench-1.2.4-fixture-1"
_INSTANCE = "testorg__calculator.abc1234"
_REPOSITORY = "testorg/calculator"
_COMMIT = "abc1234567890abcdef1234567890abcdef123456"


class ProgramBenchCompatibilityResolver:
    identity = _IDENTITY
    version = _VERSION

    def resolve(
        self,
        row: dict[str, Any],
        *,
        source_dir: Path,
        episode_id: str,
        inference_environment_id: str,
        verification_environment_id: str,
        inference_image: str,
        verification_image: str,
        task_platform: str,
        harness: HarnessSpec,
    ) -> ResolvedEpisode:
        expected = {
            "schema_version",
            "dataset_identity",
            "dataset_version",
            "instance_id",
            "repository",
            "commit",
            "language",
            "difficulty",
            "problem_statement_file",
            "problem_statement_sha256",
            "tests_metadata_file",
            "tests_metadata_sha256",
            "inference_image",
            "verification_image",
            "candidates",
            "verifier_file",
            "verifier_sha256",
        }
        if set(row) != expected:
            raise ContractError("ProgramBench compatibility row has an invalid shape")
        fixed = {
            "schema_version": 1,
            "dataset_identity": self.identity,
            "dataset_version": self.version,
            "instance_id": _INSTANCE,
            "repository": _REPOSITORY,
            "commit": _COMMIT,
            "language": "bash",
            "difficulty": "easy",
        }
        for key, value in fixed.items():
            if row[key] != value:
                raise ContractError(f"ProgramBench compatibility field {key} is unsupported")
        prompt = _checked_digest_file(
            source_dir,
            _string(row, "problem_statement_file"),
            _string(row, "problem_statement_sha256"),
            "problem statement",
        )
        _checked_digest_file(
            source_dir,
            _string(row, "tests_metadata_file"),
            _string(row, "tests_metadata_sha256"),
            "tests metadata",
        )
        verifier = _checked_digest_file(
            source_dir,
            _string(row, "verifier_file"),
            _string(row, "verifier_sha256"),
            "verifier",
        )
        _validate_image(source_dir, row["inference_image"], "inference")
        _validate_image(source_dir, row["verification_image"], "verification")
        resolved_harness, candidate_config = _resolve_harness(
            harness, source_dir, row["candidates"]
        )
        return ResolvedEpisode(
            schema_version=1,
            episode_id=episode_id,
            task_id=_INSTANCE,
            seed_digest=canonical_digest(row),
            prompt_file=str(prompt),
            task=TaskSpec(
                "programbench",
                "1",
                {"instance_id": _INSTANCE, "repository": _REPOSITORY, "commit": _COMMIT},
            ),
            inference_environment=EnvironmentBinding(
                inference_environment_id, inference_image, task_platform, "/workspace"
            ),
            verification_environment=EnvironmentBinding(
                verification_environment_id, verification_image, task_platform, "/workspace"
            ),
            harness=resolved_harness,
            candidate=CandidateSpec("workspace-archive", "1", candidate_config),
            verifier=VerifierSpec("programbench", "1", config={"verifier_file": str(verifier)}),
            metadata={
                "dataset_identity": self.identity,
                "dataset_version": self.version,
                "programbench_instance": _INSTANCE,
                "programbench_repository": _REPOSITORY,
                "programbench_commit": _COMMIT,
                "programbench_compatibility_fixture": "true",
            },
        )


def _resolve_harness(
    harness: HarnessSpec, source_dir: Path, candidates_value: object
) -> tuple[HarnessSpec, dict[str, Any]]:
    candidate_config: dict[str, Any] = {"exclude_paths": ["executable"]}
    if harness.identity == "claude-code":
        return resolve_claude_code_spec(harness), candidate_config
    if (harness.identity, harness.version) != ("static-candidate", "1"):
        raise ContractError(
            "ProgramBench compatibility supports static-candidate@1 or claude-code@2.1.205"
        )
    if set(harness.config) != {"candidate_variant"}:
        raise ContractError("static ProgramBench harness requires only candidate_variant")
    variant = _string(harness.config, "candidate_variant")
    if not isinstance(candidates_value, dict):
        raise ContractError("ProgramBench candidates must be an object")
    candidates = cast(dict[str, object], candidates_value)
    if set(candidates) != {"gold", "empty", "known-bad"} or variant not in candidates:
        raise ContractError("ProgramBench candidate variant is not registered")
    raw = candidates[variant]
    if raw is None:
        return HarnessSpec("static-candidate", "1", harness.timeout_seconds), candidate_config
    if not isinstance(raw, dict):
        raise ContractError("ProgramBench candidate definition has an invalid shape")
    definition = cast(dict[str, object], raw)
    if set(definition) != {"directory", "files"}:
        raise ContractError("ProgramBench candidate definition has an invalid shape")
    directory = definition["directory"]
    files = definition["files"]
    if not isinstance(directory, str) or not directory or not isinstance(files, dict):
        raise ContractError("ProgramBench candidate definition has an invalid shape")
    root = _checked_directory(source_dir, directory)
    actual = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    if actual != files:
        raise ContractError("ProgramBench candidate file manifest mismatch")
    candidate_config["source_directory"] = str(root)
    return HarnessSpec("static-candidate", "1", harness.timeout_seconds), candidate_config


def _validate_image(source_dir: Path, value: object, role: str) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"ProgramBench {role} image definition has an invalid shape")
    image = cast(dict[str, Any], value)
    if set(image) != {"dockerfile", "dockerfile_sha256", "platforms", "reference"}:
        raise ContractError(f"ProgramBench {role} image definition has an invalid shape")
    _checked_digest_file(
        source_dir,
        _string(image, "dockerfile"),
        _string(image, "dockerfile_sha256"),
        f"{role} Dockerfile",
    )
    if image["platforms"] != ["linux/amd64", "linux/arm64"]:
        raise ContractError(f"ProgramBench {role} image platforms are invalid")
    _string(image, "reference")


def _checked_digest_file(source_dir: Path, name: str, digest: str, label: str) -> Path:
    path = _safe_child(source_dir.resolve(), name)
    if not path.is_file() or path.is_symlink() or _sha256(path) != digest:
        raise ContractError(f"ProgramBench {label} is missing or has a digest mismatch")
    return path


def _checked_directory(source_dir: Path, name: str) -> Path:
    path = _safe_child(source_dir.resolve(), name)
    if not path.is_dir() or path.is_symlink() or any(item.is_symlink() for item in path.rglob("*")):
        raise ContractError("ProgramBench candidate directory is invalid")
    return path


def _safe_child(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ContractError("ProgramBench paths must be safe and relative")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ContractError("ProgramBench path escapes its root")
    return path


def _string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ContractError(f"ProgramBench field {key} must be a non-empty string")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
