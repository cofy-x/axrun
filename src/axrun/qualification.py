"""Stage-specific, model-free runtime qualification."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from axrun.backend import ExecutionBackend
from axrun.catalog import QualificationRequirements, resolve_qualification_requirements
from axrun.errors import ContractError, InfrastructureError, RecoveryRequiredError
from axrun.models import (
    EnvironmentBinding,
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
class QualificationTargetResult:
    role: str
    environment_id: str
    environment_image: str
    platform: str
    working_directory: str
    run_id: str
    allocation_id: str
    output_sha256: str
    checks: dict[str, Any]

    def __post_init__(self) -> None:
        if self.role not in {"inference", "verification"}:
            raise ContractError("qualification target role is invalid")
        if not all((self.environment_id, self.run_id, self.allocation_id)):
            raise ContractError("qualification target execution provenance is incomplete")
        if not _is_digest_image(self.environment_image):
            raise ContractError("qualification target image must use an OCI digest")
        _sha256(self.output_sha256, "qualification target output_sha256")


@dataclass(frozen=True, slots=True)
class QualificationResult:
    schema_version: int
    episode_id: str
    spec_digest: str
    targets: tuple[QualificationTargetResult, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.episode_id:
            raise ContractError("invalid qualification result identity")
        _sha256(self.spec_digest, "qualification spec_digest")
        if tuple(target.role for target in self.targets) != ("inference", "verification"):
            raise ContractError("qualification requires inference and verification targets")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def qualify_episode(
    episode: ResolvedEpisode,
    *,
    client: Any,
    backend: ExecutionBackend,
    store: EpisodeStore,
) -> QualificationResult:
    with store.lock(episode.episode_id):
        record = store.initialize(episode)
        if record.qualification_result:
            return load_qualification_result(store, episode)
        if record.phase != EpisodePhase.NEW:
            raise RecoveryRequiredError("episode started without qualification evidence")
    targets: list[QualificationTargetResult] = []
    executions: list[ExecutionRef] = []
    for role, binding in (
        ("inference", episode.inference_environment),
        ("verification", episode.verification_environment),
    ):
        requirements = resolve_qualification_requirements(episode, role)
        image = _environment_image(client, binding.environment_id)
        if image != binding.image:
            raise ContractError(f"{role} Environment image differs from the resolved episode")
        stage = backend.execute(
            _target_plan(episode, role, binding, requirements),
            artifact_dir=store.root / "qualification-artifacts" / episode.episode_id / role,
            on_bound=lambda _value: None,
        )
        if stage.exit_code != 0:
            raise InfrastructureError(
                f"{role} qualification Run failed: run={stage.execution.run_id} "
                f"allocation={stage.execution.allocation_id} diagnostic={stage.diagnostic_code}"
            )
        artifact = stage.artifact_for_path(_OUTPUT)
        try:
            raw: object = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("qualification output is not valid JSON") from exc
        checks = _validate_checks(raw, role, binding, requirements)
        executions.append(stage.execution)
        targets.append(
            QualificationTargetResult(
                role=role,
                environment_id=binding.environment_id,
                environment_image=image,
                platform=binding.platform,
                working_directory=binding.working_directory,
                run_id=stage.execution.run_id,
                allocation_id=stage.execution.allocation_id,
                output_sha256=artifact.sha256,
                checks=checks,
            )
        )
    result = QualificationResult(1, episode.episode_id, episode.digest, tuple(targets))
    result_path, result_digest = _persist(result, store.root)
    with store.lock(episode.episode_id):
        record = store.initialize(episode)
        if record.phase != EpisodePhase.NEW:
            raise RecoveryRequiredError("episode advanced before qualification was committed")
        if record.qualification_result:
            return load_qualification_result(store, episode)
        record.qualifications = tuple(executions)
        record.qualification_result = str(result_path)
        record.qualification_result_digest = result_digest
        store.save(record)
    return result


def _target_plan(
    episode: ResolvedEpisode,
    role: str,
    binding: EnvironmentBinding,
    requirements: QualificationRequirements,
) -> StagePlan:
    fixture = Path(__file__).parent / "fixtures" / "qualification" / "run.py"
    arguments = [
        "/opt/axrun/qualification.py",
        "--role",
        role,
        "--workspace",
        binding.working_directory,
        "--output",
        _OUTPUT,
    ]
    inputs = [InputFile(str(fixture), "/opt/axrun/qualification.py")]
    mounts: tuple[ImageMountSpec, ...] = ()
    if requirements.task_mode == "git":
        arguments.extend(("--base-commit", requirements.base_commit))
    elif requirements.task_mode == "empty":
        arguments.append("--require-empty-workspace")
    elif requirements.task_mode in {"prepared", "prepared_contains"}:
        if requirements.task_mode == "prepared":
            arguments.append("--require-exact-workspace-files")
        else:
            arguments.append("--require-workspace-files")
        for requirement in requirements.workspace_files:
            arguments.extend(
                ("--required-workspace-file", f"{requirement.mode:o}:{requirement.path}")
            )
    if role == "inference" and requirements.archive_finalizer:
        package_root = Path(__file__).parent
        inputs.extend(
            (
                InputFile(
                    str(package_root / "candidates" / "archive.py"),
                    "/opt/axrun/axrun/candidates/archive.py",
                ),
                InputFile(str(package_root / "errors.py"), "/opt/axrun/axrun/errors.py"),
            )
        )
        arguments.extend(("--archive-module", "/opt/axrun/axrun/candidates/archive.py"))
    if role == "verification" and requirements.verifier_file:
        inputs.append(InputFile(requirements.verifier_file, "/opt/axrun/verifier.py"))
        arguments.extend(("--verifier-file", "/opt/axrun/verifier.py"))
    if role == "inference" and requirements.claude_mount_image:
        if not _is_digest_image(requirements.claude_mount_image):
            raise ContractError("Claude qualification requires a digest-pinned mount image")
        mounts = (
            ImageMountSpec(
                image=requirements.claude_mount_image,
                target="/__claude_code",
                readonly=True,
            ),
        )
        arguments.append("--claude")
    return StagePlan(
        environment_id=binding.environment_id,
        argv=(
            "/bin/sh",
            "-lc",
            'if [ -x /usr/bin/python3 ]; then exec /usr/bin/python3 "$@"; '
            'else exec python3 "$@"; fi',
            "axrun-qualification",
            *arguments,
        ),
        cwd=binding.working_directory,
        inputs=tuple(inputs),
        outputs=(OutputSpec(_OUTPUT, media_type="application/json", max_bytes=16 << 10),),
        image_mounts=mounts,
        resources=(
            episode.inference_resources if role == "inference" else episode.verification_resources
        ),
        network_policy="deny_all",
        timeout_seconds=min(300, episode.harness.timeout_seconds),
        labels={"axrun.stage": "qualification", "axrun.qualification.role": role},
    )


def _validate_checks(
    raw: object,
    role: str,
    binding: EnvironmentBinding,
    requirements: QualificationRequirements,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ContractError("qualification output must be an object")
    checks = cast(dict[str, Any], raw)
    if set(checks) != {
        "schema_version",
        "role",
        "base_commit",
        "git",
        "machine",
        "python",
        "working_directory",
        "workspace_empty",
        "workspace_files",
        "archive_module",
        "verifier_file",
        "claude",
    }:
        raise ContractError("qualification output has an invalid shape")
    if (
        checks["schema_version"] != 1
        or checks["role"] != role
        or checks["working_directory"] != binding.working_directory
        or not isinstance(checks["machine"], str)
        or not isinstance(checks["python"], str)
    ):
        raise ContractError("qualification output does not match the target")
    if requirements.task_mode == "git":
        if (
            checks["base_commit"] != requirements.base_commit
            or not isinstance(checks["git"], str)
            or checks["workspace_empty"] is not None
            or checks["workspace_files"] is not None
        ):
            raise ContractError("Git task qualification checks are invalid")
    elif requirements.task_mode == "empty" and (
        checks["base_commit"] is not None
        or checks["git"] is not None
        or checks["workspace_empty"] is not True
        or checks["workspace_files"] is not None
    ):
        raise ContractError("greenfield task qualification checks are invalid")
    elif requirements.task_mode in {"prepared", "prepared_contains"}:
        expected = [
            {"mode": requirement.mode, "path": requirement.path}
            for requirement in requirements.workspace_files
        ]
        if (
            checks["base_commit"] is not None
            or checks["git"] is not None
            or checks["workspace_empty"] is not False
            or checks["workspace_files"] != expected
        ):
            raise ContractError("prepared task qualification checks are invalid")
    expected_archive = role == "inference" and requirements.archive_finalizer
    expected_verifier = role == "verification" and bool(requirements.verifier_file)
    if checks["archive_module"] is not expected_archive:
        raise ContractError("candidate qualification checks are invalid")
    if checks["verifier_file"] is not expected_verifier:
        raise ContractError("verifier qualification checks are invalid")
    claude = checks["claude"]
    if role == "inference" and requirements.claude_mount_image:
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
        raise ContractError("qualification unexpectedly reported a Claude runtime")
    return checks


def _environment_image(client: Any, environment_id: str) -> str:
    image = str(client.get_environment(environment_id).spec.image.ref)
    if not _is_digest_image(image):
        raise ContractError("Environment task image must use an OCI sha256 digest")
    return image


def _is_digest_image(value: str) -> bool:
    name, separator, digest = value.rpartition(_DIGEST_IMAGE)
    return bool(name and separator and len(digest) == 64) and all(
        character in "0123456789abcdef" for character in digest
    )


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ContractError(f"{name} must be lowercase SHA-256")


def _persist(result: QualificationResult, state_root: Path) -> tuple[Path, str]:
    path = state_root / "qualifications" / result.episode_id / result.spec_digest / "result.json"
    payload = json.dumps(result.as_dict(), sort_keys=True, indent=2).encode() + b"\n"
    digest = canonical_digest(result.as_dict())
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ContractError("qualification evidence already exists with different content")
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
    if record is None or len(record.qualifications) != 2:
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
    raw_targets = values.get("targets")
    if not isinstance(raw_targets, list):
        raise ContractError("qualification targets must be an array")
    target_values = cast(list[object], raw_targets)
    try:
        targets = tuple(
            QualificationTargetResult(**cast(dict[str, Any], target))
            for target in target_values
            if isinstance(target, dict)
        )
        result = QualificationResult(
            schema_version=int(values["schema_version"]),
            episode_id=str(values["episode_id"]),
            spec_digest=str(values["spec_digest"]),
            targets=targets,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("qualification evidence has an invalid shape") from exc
    if len(targets) != len(target_values):
        raise ContractError("qualification evidence has an invalid target")
    if result.episode_id != episode.episode_id or result.spec_digest != episode.digest:
        raise ContractError("qualification evidence provenance mismatch")
    for target, execution, (role, binding) in zip(
        result.targets,
        record.qualifications,
        (
            ("inference", episode.inference_environment),
            ("verification", episode.verification_environment),
        ),
        strict=True,
    ):
        requirements = resolve_qualification_requirements(episode, role)
        if (
            target.role != role
            or target.environment_id != binding.environment_id
            or target.run_id != execution.run_id
            or target.allocation_id != execution.allocation_id
        ):
            raise ContractError("qualification target provenance mismatch")
        _validate_checks(target.checks, role, binding, requirements)
    return result
