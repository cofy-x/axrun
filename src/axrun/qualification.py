"""Bounded, model-free pre-inference qualification."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from axrun.backend import ExecutionBackend
from axrun.errors import ContractError, InfrastructureError, RecoveryRequiredError
from axrun.models import (
    EpisodePhase,
    ExecutionRef,
    ImageMountSpec,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    canonical_digest,
)
from axrun.store import EpisodeStore

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

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.episode_id:
            raise ContractError("invalid qualification result identity")
        for name, value in (
            ("spec_digest", self.spec_digest),
            ("output_sha256", self.output_sha256),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ContractError(f"qualification {name} must be lowercase SHA-256")
        if (
            not _is_digest_image(self.environment_image)
            or not self.run_id
            or not self.allocation_id
        ):
            raise ContractError("qualification execution provenance is invalid")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def qualify_episode(
    episode: ResolvedEpisode,
    *,
    client: Any,
    backend: ExecutionBackend,
    store: EpisodeStore,
) -> QualificationResult:
    """Qualify immutable environment and runtime prerequisites without a model secret."""
    with store.lock(episode.episode_id):
        record = store.initialize(episode)
        if record.qualification_result:
            return load_qualification_result(store, episode)
        if record.phase != EpisodePhase.NEW:
            raise RecoveryRequiredError("episode started without qualification evidence")
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
    qualification_args = [
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
        qualification_args.append("--claude")
    argv = (
        "/bin/sh",
        "-lc",
        'if [ -x /usr/bin/python3 ]; then exec /usr/bin/python3 "$@"; else exec python3 "$@"; fi',
        "axrun-qualification",
        *qualification_args,
    )
    plan = StagePlan(
        environment_id=episode.inference_environment_id,
        argv=argv,
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
        artifact_dir=store.root / "qualification-artifacts" / episode.episode_id,
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
    result_path, result_digest = _persist(result, store.root)
    with store.lock(episode.episode_id):
        record = store.initialize(episode)
        if record.phase != EpisodePhase.NEW:
            raise RecoveryRequiredError("episode advanced before qualification was committed")
        if record.qualification_result:
            return load_qualification_result(store, episode)
        record.qualification = stage.execution
        record.qualification_result = str(result_path)
        record.qualification_result_digest = result_digest
        store.save(record)
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


def _persist(result: QualificationResult, state_root: Path) -> tuple[Path, str]:
    path = (
        state_root
        / "qualifications"
        / result.episode_id
        / result.spec_digest
        / f"{result.run_id}.json"
    )
    payload = json.dumps(result.as_dict(), sort_keys=True, indent=2).encode() + b"\n"
    digest = canonical_digest(result.as_dict())
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ContractError("qualification Run evidence already exists with different content")
        return path, digest
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path, digest


def load_qualification_result(store: EpisodeStore, episode: ResolvedEpisode) -> QualificationResult:
    record = store.load(episode.episode_id)
    if record is None or record.qualification is None:
        raise ContractError("qualification record is incomplete")
    try:
        raw: object = json.loads(Path(record.qualification_result).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("qualification evidence is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ContractError("qualification evidence must be an object")
    values = cast(dict[str, Any], raw)
    if canonical_digest(values) != record.qualification_result_digest:
        raise ContractError("qualification evidence digest mismatch")
    try:
        result = QualificationResult(**values)
    except TypeError as exc:
        raise ContractError("qualification evidence has an invalid shape") from exc
    if (
        result.schema_version != 1
        or result.episode_id != episode.episode_id
        or result.spec_digest != episode.digest
        or result.run_id != record.qualification.run_id
        or result.allocation_id != record.qualification.allocation_id
    ):
        raise ContractError("qualification evidence provenance mismatch")
    working_directory = episode.harness.config.get("working_directory", "/workspace")
    if not isinstance(working_directory, str):
        raise ContractError("qualification working directory is invalid")
    _validate_checks(result.checks, episode, working_directory)
    return result
