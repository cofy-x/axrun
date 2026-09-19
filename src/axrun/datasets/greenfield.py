"""Resolver for the repository-owned no-Git greenfield task."""

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


class SyntheticGreenfieldResolver:
    identity = "axrun.synthetic.greenfield-task"
    version = "1"

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
            "task_id",
            "problem_statement_file",
            "inference_image",
            "verification_image",
            "candidates",
            "verifier_file",
            "verifier_sha256",
        }
        if set(row) != expected:
            raise ContractError("greenfield dataset row has an invalid shape")
        if row["schema_version"] != 1 or (row["dataset_identity"], row["dataset_version"]) != (
            self.identity,
            self.version,
        ):
            raise ContractError("greenfield dataset identity/version mismatch")
        prompt = _checked_file(source_dir, _string(row, "problem_statement_file"))
        _validate_image(source_dir, row["inference_image"], "inference")
        _validate_image(source_dir, row["verification_image"], "verification")
        verifier_file = _checked_file(source_dir, _string(row, "verifier_file"))
        if _sha256(verifier_file) != _string(row, "verifier_sha256"):
            raise ContractError("greenfield verifier digest mismatch")
        resolved_harness, candidate_config = _resolve_harness(
            harness, source_dir, row["candidates"]
        )
        return ResolvedEpisode(
            schema_version=1,
            episode_id=episode_id,
            task_id=_string(row, "task_id"),
            seed_digest=canonical_digest(row),
            prompt_file=str(prompt),
            task=TaskSpec(self.identity, self.version),
            inference_environment=EnvironmentBinding(
                inference_environment_id, inference_image, task_platform, "/workspace"
            ),
            verification_environment=EnvironmentBinding(
                verification_environment_id, verification_image, task_platform, "/workspace"
            ),
            harness=resolved_harness,
            candidate=CandidateSpec("workspace-archive", "1", candidate_config),
            verifier=VerifierSpec(
                "synthetic-greenfield", "1", config={"verifier_file": str(verifier_file)}
            ),
            metadata={
                "dataset_identity": self.identity,
                "dataset_version": self.version,
                "inference_image_reference": _image_reference(row["inference_image"]),
                "verification_image_reference": _image_reference(row["verification_image"]),
            },
        )


def _resolve_harness(
    harness: HarnessSpec, source_dir: Path, candidates_value: object
) -> tuple[HarnessSpec, dict[str, Any]]:
    if harness.identity == "claude-code":
        return resolve_claude_code_spec(harness), {}
    if (harness.identity, harness.version) != ("static-candidate", "1"):
        raise ContractError("greenfield task supports static-candidate@1 or claude-code@2.1.205")
    if set(harness.config) != {"candidate_variant"}:
        raise ContractError("static greenfield harness requires only candidate_variant")
    variant = _string(harness.config, "candidate_variant")
    if not isinstance(candidates_value, dict):
        raise ContractError("greenfield candidates must be an object")
    candidates = cast(dict[str, object], candidates_value)
    if set(candidates) != {"gold", "empty", "known-bad"} or variant not in candidates:
        raise ContractError("greenfield candidate variant is not registered")
    raw = candidates[variant]
    if not isinstance(raw, dict):
        raise ContractError("greenfield candidate definition has an invalid shape")
    definition = cast(dict[str, object], raw)
    if set(definition) != {"directory", "files"}:
        raise ContractError("greenfield candidate definition has an invalid shape")
    directory = definition["directory"]
    files = definition["files"]
    if not isinstance(files, dict):
        raise ContractError("greenfield candidate files must be an object")
    if directory is None:
        if files:
            raise ContractError("empty greenfield candidate must not declare files")
        config: dict[str, Any] = {}
    elif isinstance(directory, str) and directory:
        root = _checked_directory(source_dir, directory)
        expected_files = {
            path.relative_to(root).as_posix(): _sha256(path)
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }
        if expected_files != files:
            raise ContractError("greenfield candidate file manifest mismatch")
        config = {"source_directory": str(root)}
    else:
        raise ContractError("greenfield candidate directory is invalid")
    return HarnessSpec("static-candidate", "1", harness.timeout_seconds), config


def _validate_image(source_dir: Path, value: object, role: str) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"greenfield {role} image definition has an invalid shape")
    image = cast(dict[str, Any], value)
    if set(image) != {
        "dockerfile",
        "dockerfile_sha256",
        "platforms",
        "reference",
    }:
        raise ContractError(f"greenfield {role} image definition has an invalid shape")
    dockerfile = _checked_file(source_dir, _string(image, "dockerfile"))
    if _sha256(dockerfile) != _string(image, "dockerfile_sha256"):
        raise ContractError(f"greenfield {role} Dockerfile digest mismatch")
    if image["platforms"] != ["linux/amd64", "linux/arm64"]:
        raise ContractError(f"greenfield {role} image platforms are invalid")
    _string(image, "reference")


def _image_reference(value: object) -> str:
    return _string(cast(dict[str, Any], value), "reference")


def _string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ContractError(f"greenfield field {key} must be a non-empty string")
    return result


def _checked_file(source_dir: Path, relative_name: str) -> Path:
    root = source_dir.resolve()
    path = _safe_child(root, relative_name)
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"greenfield file does not exist: {relative_name}")
    return path


def _checked_directory(source_dir: Path, relative_name: str) -> Path:
    root = source_dir.resolve()
    path = _safe_child(root, relative_name)
    if not path.is_dir() or path.is_symlink():
        raise ContractError(f"greenfield directory does not exist: {relative_name}")
    if any(item.is_symlink() for item in path.rglob("*")):
        raise ContractError("greenfield candidate directory rejects symlinks")
    return path


def _safe_child(root: Path, relative_name: str) -> Path:
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ContractError(f"greenfield path must be safe and relative: {relative_name}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ContractError(f"greenfield path escapes its root: {relative_name}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
