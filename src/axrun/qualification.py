"""Bounded, model-free pre-inference qualification."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from axrun.backend import ExecutionBackend
from axrun.errors import ContractError, InfrastructureError
from axrun.models import (
    ExecutionRef,
    ImageMountSpec,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
)

_OUTPUT = "/outputs/qualification.json"
_DIGEST_IMAGE = "@sha256:"


@dataclass(frozen=True, slots=True)
class QualificationResult:
    schema_version: int
    episode_id: str
    spec_digest: str
    environment_image: str
    run_id: str
    allocation_id: str
    output_sha256: str
    checks: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def qualify_episode(
    episode: ResolvedEpisode,
    *,
    client: Any,
    backend: ExecutionBackend,
    state_root: Path,
) -> QualificationResult:
    """Qualify immutable environment and runtime prerequisites without a model secret."""
    inference_image = _environment_image(client, episode.inference_environment_id)
    verification_image = _environment_image(client, episode.verification_environment_id)
    if inference_image != verification_image:
        raise ContractError("inference and verification Environments use different task images")
    expected_image = episode.metadata.get("task_image", "")
    if expected_image and inference_image != expected_image:
        raise ContractError("Environment task image differs from the resolved episode")

    working_directory = episode.harness.config.get("working_directory", "/workspace")
    if not isinstance(working_directory, str) or not working_directory.startswith("/"):
        raise ContractError("qualification working directory must be absolute")
    fixture = Path(__file__).parent / "fixtures" / "qualification" / "run.py"
    argv = [
        "/usr/bin/python3",
        "/opt/axrun/qualification.py",
        "--workspace",
        working_directory,
        "--base-commit",
        episode.base_commit,
        "--output",
        _OUTPUT,
    ]
    mounts: tuple[ImageMountSpec, ...] = ()
    if episode.harness.identity == "claude-code":
        image = episode.harness.config.get("mount_image")
        if not isinstance(image, str) or not _is_digest_image(image):
            raise ContractError("Claude qualification requires a digest-pinned mount image")
        mounts = (ImageMountSpec(image=image, target="/__claude_code", readonly=True),)
        argv.append("--claude")
    plan = StagePlan(
        environment_id=episode.inference_environment_id,
        argv=tuple(argv),
        cwd=working_directory,
        inputs=(InputFile(str(fixture), "/opt/axrun/qualification.py"),),
        outputs=(OutputSpec(_OUTPUT, media_type="application/json", max_bytes=16 << 10),),
        image_mounts=mounts,
        resources=episode.inference_resources,
        network_policy="deny_all",
        timeout_seconds=min(300, episode.harness.timeout_seconds),
        labels={"axrun.stage": "qualification"},
    )

    def bound(_value: ExecutionRef) -> None:
        return

    stage = backend.execute(
        plan,
        artifact_dir=state_root / "qualification-artifacts" / episode.episode_id,
        on_bound=bound,
    )
    if stage.exit_code != 0:
        raise InfrastructureError(
            f"qualification Run failed: run={stage.execution.run_id} "
            f"allocation={stage.execution.allocation_id} diagnostic={stage.diagnostic_code}"
        )
    artifact = stage.artifact_for_path(_OUTPUT)
    try:
        raw: object = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("qualification output is not valid JSON") from exc
    checks = _validate_checks(raw, episode, working_directory)
    result = QualificationResult(
        schema_version=1,
        episode_id=episode.episode_id,
        spec_digest=episode.digest,
        environment_image=inference_image,
        run_id=stage.execution.run_id,
        allocation_id=stage.execution.allocation_id,
        output_sha256=artifact.sha256,
        checks=checks,
    )
    _persist(result, state_root)
    return result


def _environment_image(client: Any, environment_id: str) -> str:
    environment = client.get_environment(environment_id)
    image = str(environment.spec.image.ref)
    if not _is_digest_image(image):
        raise ContractError("Environment task image must use an OCI sha256 digest")
    return image


def _is_digest_image(value: str) -> bool:
    name, separator, digest = value.rpartition(_DIGEST_IMAGE)
    return bool(name and separator and len(digest) == 64) and all(
        character in "0123456789abcdef" for character in digest
    )


def _validate_checks(
    raw: object, episode: ResolvedEpisode, working_directory: str
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ContractError("qualification output must be an object")
    checks = cast(dict[str, Any], raw)
    if set(checks) != {
        "schema_version",
        "base_commit",
        "git",
        "machine",
        "python",
        "working_directory",
        "claude",
    }:
        raise ContractError("qualification output has an invalid shape")
    if (
        checks["schema_version"] != 1
        or checks["base_commit"] != episode.base_commit
        or checks["working_directory"] != working_directory
    ):
        raise ContractError("qualification output does not match the episode")
    if not all(
        isinstance(checks[key], str) and checks[key] for key in ("git", "machine", "python")
    ):
        raise ContractError("qualification output contains invalid runtime versions")
    claude = checks["claude"]
    if episode.harness.identity == "claude-code":
        if not isinstance(claude, dict) or set(cast(dict[object, object], claude)) != {
            "entry",
            "mount_readonly",
            "node_version",
            "version",
        }:
            raise ContractError("qualification output has an invalid Claude result")
        claude = cast(dict[str, Any], claude)
        if (
            claude["entry"] != "/__claude_code/usr/local/bin/claude"
            or claude["mount_readonly"] is not True
            or claude["node_version"] != "v22.23.2"
            or "2.1.205 (Claude Code)" not in str(claude["version"])
        ):
            raise ContractError("qualification output has an incompatible Claude runtime")
    elif claude is not None:
        raise ContractError("non-Claude qualification unexpectedly reported a Claude runtime")
    return checks


def _persist(result: QualificationResult, state_root: Path) -> None:
    path = (
        state_root
        / "qualifications"
        / result.episode_id
        / result.spec_digest
        / f"{result.run_id}.json"
    )
    payload = json.dumps(result.as_dict(), sort_keys=True, indent=2).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ContractError("qualification Run evidence already exists with different content")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
