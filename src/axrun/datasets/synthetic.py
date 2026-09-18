"""Resolver for the repository-owned deterministic synthetic code task."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError
from axrun.models import (
    HarnessSpec,
    ResolvedEpisode,
    VerifierSpec,
    canonical_digest,
)


class SyntheticCodeTaskResolver:
    identity = "axrun.synthetic.code-task"
    version = "1"

    def resolve(
        self,
        row: dict[str, Any],
        *,
        source_dir: Path,
        episode_id: str,
        inference_environment_id: str,
        verification_environment_id: str,
        harness: HarnessSpec,
    ) -> ResolvedEpisode:
        expected = {
            "schema_version",
            "dataset_identity",
            "dataset_version",
            "task_id",
            "base_commit",
            "problem_statement_file",
            "task_image",
        }
        unknown = set(row) - expected
        missing = expected - set(row)
        if unknown or missing:
            details: list[str] = []
            if missing:
                details.append(f"missing: {', '.join(sorted(missing))}")
            if unknown:
                details.append(f"unknown: {', '.join(sorted(unknown))}")
            raise ContractError(f"invalid synthetic dataset row ({'; '.join(details)})")
        if row["schema_version"] != 1:
            raise ContractError("synthetic dataset row schema_version must be 1")
        if row["dataset_identity"] != self.identity or row["dataset_version"] != self.version:
            raise ContractError("synthetic dataset identity/version mismatch")
        task_id = _required_string(row, "task_id")
        base_commit = _required_string(row, "base_commit")
        prompt = _checked_file(source_dir, _required_string(row, "problem_statement_file"))
        task_image = row["task_image"]
        if not isinstance(task_image, dict):
            raise ContractError("synthetic task_image has an invalid shape")
        task_image_values = cast(dict[str, Any], task_image)
        if set(task_image_values) != {
            "dockerfile",
            "platforms",
            "reference",
            "sources",
        }:
            raise ContractError("synthetic task_image has an invalid shape")
        dockerfile = _checked_file(source_dir, _required_string(task_image_values, "dockerfile"))
        if task_image_values["platforms"] != ["linux/amd64", "linux/arm64"]:
            raise ContractError(
                "synthetic task image platforms must be linux/amd64 and linux/arm64"
            )
        task_image_reference = _required_string(task_image_values, "reference")
        verifier = Path(__file__).parents[1] / "fixtures" / "synthetic" / "run_verifier.py"
        if not verifier.is_file():
            raise ContractError("packaged synthetic verifier is missing")
        sources: object = task_image_values["sources"]
        if not isinstance(sources, list) or not sources:
            raise ContractError("synthetic task image sources must be a non-empty array")
        for index, raw_item in enumerate(cast(list[object], sources)):
            item = cast(dict[str, Any], raw_item) if isinstance(raw_item, dict) else None
            if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                raise ContractError(f"synthetic task image sources[{index}] has an invalid shape")
            source = _checked_file(source_dir, _required_string(item, "path"))
            digest = _required_string(item, "sha256")
            if _sha256(source) != digest:
                raise ContractError(f"synthetic task image source digest mismatch: {item['path']}")
        resolved_harness = _resolve_harness(harness, source_dir)
        return ResolvedEpisode(
            schema_version=1,
            episode_id=episode_id,
            task_id=task_id,
            seed_digest=canonical_digest(row),
            base_commit=base_commit,
            prompt_file=str(prompt),
            inference_environment_id=inference_environment_id,
            verification_environment_id=verification_environment_id,
            harness=resolved_harness,
            verifier=VerifierSpec(
                identity="synthetic-code-task",
                version="1",
                config={"verifier_file": str(verifier)},
            ),
            metadata={
                "dataset_identity": self.identity,
                "dataset_version": self.version,
                "task_image_dockerfile": str(dockerfile),
                "task_image_reference": task_image_reference,
            },
        )


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ContractError(f"synthetic field {key} must be a non-empty string")
    return result


def _resolve_harness(harness: HarnessSpec, source_dir: Path) -> HarnessSpec:
    config = dict(harness.config)
    if harness.identity == "static-patch":
        if set(config) != {"candidate_file"}:
            raise ContractError("static-patch config requires only candidate_file")
        candidate = _checked_file(source_dir, _required_string(config, "candidate_file"))
        config = {"candidate_file": str(candidate)}
    elif harness.identity == "claude-code":
        unknown = set(config) - {
            "mount_image",
            "model",
            "default_opus_model",
            "default_sonnet_model",
            "default_haiku_model",
            "subagent_model",
            "effort_level",
            "auto_compact_window",
            "max_turns",
        }
        if unknown:
            raise ContractError(f"unknown Claude Code config: {', '.join(sorted(unknown))}")
        _required_string(config, "mount_image")
        _required_string(config, "model")
    else:
        raise ContractError(f"unsupported synthetic harness: {harness.identity}")
    return HarnessSpec(
        identity=harness.identity,
        version=harness.version,
        timeout_seconds=harness.timeout_seconds,
        config=config,
    )


def _checked_file(source_dir: Path, relative_name: str) -> Path:
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ContractError(f"synthetic file path must be safe and relative: {relative_name}")
    root = source_dir.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ContractError(f"synthetic file does not exist: {relative_name}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
