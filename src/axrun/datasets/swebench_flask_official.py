"""Unregistered, closed resolver for the official Verified Flask-5014 stage zero.

The official enriched row is checked against its complete canonical digest once.
Only the problem statement and evaluation script are materialized; the gold patch,
test patch, and hints never become task or candidate configuration.
"""

from __future__ import annotations

import hashlib
import re
import stat
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError
from axrun.harnesses import resolve_claude_code_spec
from axrun.models import (
    CandidateSpec,
    EnvironmentBinding,
    HarnessSpec,
    ResolvedEpisode,
    StageNetworkPolicy,
    TaskSpec,
    VerifierSpec,
    canonical_digest,
)

_DATASET = "SWE-bench/SWE-bench_Verified"
_DATASET_COMMIT = "78f471bf655a3137b2e8a75af1501690ec009ec3"
_SCHEMA = "enriched-v1"
_HARNESS_COMMIT = "f7bbbb2ccdf479001d6467c9e34af59e44a840f9"
_ROW_SHA256 = "36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e"
_EVAL_SCRIPT_SHA256 = "a752d2d3520db71513c263dd476e8da457395a447a346f6b5c18782dc0faf034"
_INSTANCE = "pallets__flask-5014"
_SOURCE_IMAGE = (
    "docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014"
    "@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4"
)
_CANONICAL_SOURCE_IMAGE = _SOURCE_IMAGE.replace("docker.io/", "index.docker.io/", 1)
_ROW_IMAGE = "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest"
_ROW_BASE_COMMIT = "7ee9ceb71e868944a46e1ff00b506772a53a4f1d"
# The locked official image has a clean worktree at this HEAD; the dataset row's
# base commit is present in its history but is not its checkout identity.
_IMAGE_HEAD = "966bb873e3a1e42d857362a17f5af2533dfd8f46"
_PLATFORM = "linux/amd64"
_ROW_FIELDS = frozenset(
    {
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "base_commit",
        "created_at",
        "difficulty",
        "environment_setup_commit",
        "eval_script",
        "eval_type",
        "hints_text",
        "image",
        "instance_id",
        "log_parser",
        "patch",
        "problem_statement",
        "repo",
        "test_patch",
        "version",
    }
)
_IMMUTABLE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
_LOCKED_WHEELS = (
    (
        "setuptools-70.0.0-py3-none-any.whl",
        863_432,
        "54faa7f2e8d2d11bcd2c07bed282eef1046b5c080d1c32add737d7b5817b1ad4",
    ),
    (
        "wheel-0.45.1-py3-none-any.whl",
        72_494,
        "708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248",
    ),
)


class SweBenchFlaskOfficialResolver:
    """Resolve only the pinned official Flask instance; not catalog-registered."""

    identity = _DATASET
    version = _SCHEMA

    def resolve(
        self,
        row: dict[str, Any],
        *,
        asset_dir: Path,
        episode_id: str,
        inference_environment_id: str,
        verification_environment_id: str,
        task_image: str,
        image_import_receipt: dict[str, str],
        wheelhouse_dir: Path,
        harness: HarnessSpec,
        static_candidate_file: Path | None = None,
    ) -> ResolvedEpisode:
        strings, fail_to_pass, pass_to_pass = _checked_row(row)
        _check_import_receipt(image_import_receipt, task_image)
        if inference_environment_id == verification_environment_id:
            raise ContractError("Flask verification requires a distinct Environment")
        wheels = _checked_wheels(wheelhouse_dir)
        resolved_harness, candidate_config = _resolve_harness(
            harness, static_candidate_file, asset_dir
        )
        seed_digest = canonical_digest(
            {
                "dataset_identity": _DATASET,
                "dataset_commit": _DATASET_COMMIT,
                "row_schema": _SCHEMA,
                "row": row,
            }
        )
        assets = asset_dir / seed_digest
        prompt = _materialize(assets, "problem", strings["problem_statement"].encode())
        eval_script = _materialize(assets, "eval", strings["eval_script"].encode())
        verifier = (
            Path(__file__).parents[1] / "fixtures" / "swebench_flask_official" / "run_verifier.py"
        )
        # The companion adapter owns this fixture. Do not serialize a path to an
        # absent or unexpected evaluator and later treat that as a candidate failure.
        if not verifier.is_file() or verifier.is_symlink():
            raise ContractError("packaged Flask verifier is missing")
        return ResolvedEpisode(
            schema_version=2,
            episode_id=episode_id,
            task_id=_INSTANCE,
            seed_digest=seed_digest,
            prompt_file=str(prompt),
            task=TaskSpec(
                identity="swebench-flask-official",
                version="1",
                config={"base_commit": _IMAGE_HEAD},
            ),
            inference_environment=EnvironmentBinding(
                inference_environment_id, task_image, _PLATFORM, "/testbed"
            ),
            verification_environment=EnvironmentBinding(
                verification_environment_id, task_image, _PLATFORM, "/testbed"
            ),
            harness=resolved_harness,
            candidate=CandidateSpec("git-patch", "1", candidate_config),
            verifier=VerifierSpec(
                identity="swebench-flask-official",
                version="1",
                timeout_seconds=1860,
                config={
                    "verifier_file": str(verifier),
                    "eval_script_file": str(eval_script),
                    "eval_script_sha256": _EVAL_SCRIPT_SHA256,
                    "fail_to_pass": list(fail_to_pass),
                    "pass_to_pass": list(pass_to_pass),
                    "log_parser": "parse_log_flask",
                    "setuptools_wheel_file": str(wheels[0]),
                    "wheel_wheel_file": str(wheels[1]),
                    "harness_commit": _HARNESS_COMMIT,
                    "instance_id": _INSTANCE,
                    "eval_timeout_seconds": 1800,
                },
            ),
            inference_network_policy=StageNetworkPolicy.DENY_ALL,
            verification_network_policy=StageNetworkPolicy.DENY_ALL,
            metadata={
                "dataset_identity": _DATASET,
                "dataset_commit": _DATASET_COMMIT,
                "dataset_version": _SCHEMA,
                "official_row_sha256": _ROW_SHA256,
                "official_row_base_commit": _ROW_BASE_COMMIT,
                "official_image_head": _IMAGE_HEAD,
                "official_source_image": _SOURCE_IMAGE,
                "task_image": task_image,
                "task_platform": _PLATFORM,
                "official_instance_scope": "single-instance-stage-zero",
            },
        )


def _checked_row(row: dict[str, Any]) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    if set(row) != set(_ROW_FIELDS):
        raise ContractError("official Flask enriched row has an invalid shape")
    strings: dict[str, str] = {}
    for key in _ROW_FIELDS - {"FAIL_TO_PASS", "PASS_TO_PASS"}:
        value = row[key]
        if not isinstance(value, str) or (not value and key != "hints_text"):
            raise ContractError(f"official Flask row {key} must be a string")
        strings[key] = value
    fixed = {
        "instance_id": _INSTANCE,
        "repo": "pallets/flask",
        "base_commit": _ROW_BASE_COMMIT,
        "version": "2.3",
        "image": _ROW_IMAGE,
        "eval_type": "pass_and_fail",
        "log_parser": "parse_log_flask",
    }
    for key, value in fixed.items():
        if strings[key] != value:
            raise ContractError(f"official Flask row {key} differs from lock")
    if re.fullmatch(r"[0-9a-f]{40}", strings["environment_setup_commit"]) is None:
        raise ContractError("official Flask setup commit is malformed")
    fail_to_pass = _tests(row["FAIL_TO_PASS"], "FAIL_TO_PASS", expected=1)
    pass_to_pass = _tests(row["PASS_TO_PASS"], "PASS_TO_PASS", expected=59)
    if set(fail_to_pass) & set(pass_to_pass):
        raise ContractError("official Flask expected test classes overlap")
    if hashlib.sha256(strings["eval_script"].encode()).hexdigest() != _EVAL_SCRIPT_SHA256:
        raise ContractError("official Flask eval script differs from lock")
    if canonical_digest(row) != _ROW_SHA256:
        raise ContractError("official Flask enriched row digest differs from lock")
    return strings, fail_to_pass, pass_to_pass


def _tests(value: object, name: str, *, expected: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractError(f"official Flask {name} must contain {expected} tests")
    items = cast(list[object], value)
    if len(items) != expected:
        raise ContractError(f"official Flask {name} must contain {expected} tests")
    if any(not isinstance(item, str) or not item for item in items):
        raise ContractError(f"official Flask {name} must contain strings")
    result = tuple(cast(list[str], items))
    if len(set(result)) != len(result):
        raise ContractError(f"official Flask {name} contains duplicates")
    return result


def _check_import_receipt(receipt: dict[str, str], task_image: str) -> None:
    if set(receipt) != {
        "source_ref",
        "canonical_ref",
        "immutable_ref",
        "content_digest",
        "platform",
    }:
        raise ContractError("Flask image import receipt has an invalid shape")
    if (
        receipt["source_ref"] != _SOURCE_IMAGE
        or receipt["canonical_ref"] != _CANONICAL_SOURCE_IMAGE
        or receipt["platform"] != _PLATFORM
    ):
        raise ContractError("Flask image import receipt differs from locked source/platform")
    if _IMMUTABLE_REF.fullmatch(task_image) is None:
        raise ContractError("Flask task image requires an immutable OCI digest reference")
    name = task_image.split("@", 1)[0]
    if ":" in name.rsplit("/", 1)[-1]:
        raise ContractError("Flask task image cannot contain a mutable tag")
    if name != _CANONICAL_SOURCE_IMAGE.split("@", 1)[0]:
        raise ContractError("Flask imported image repository differs from locked source")
    if receipt["immutable_ref"] != task_image:
        raise ContractError("Flask task image differs from public import receipt")
    content_digest = receipt["content_digest"]
    if content_digest != task_image.rsplit("@", 1)[-1]:
        raise ContractError("Flask import content digest differs from immutable reference")


def _resolve_harness(
    harness: HarnessSpec, static_candidate_file: Path | None, asset_dir: Path
) -> tuple[HarnessSpec, dict[str, Any]]:
    if harness.identity == "claude-code":
        if static_candidate_file is not None:
            raise ContractError("Claude inference cannot receive a static candidate")
        resolved = resolve_claude_code_spec(harness)
        if resolved.config["working_directory"] != "/testbed":
            raise ContractError("Claude working directory must be /testbed")
        return resolved, {}
    if (harness.identity, harness.version, harness.config) != ("static-candidate", "1", {}):
        raise ContractError("Flask supports only empty static-candidate@1 or Claude Code 2.1.205")
    if static_candidate_file is None:
        raise ContractError("static Flask candidate requires an explicit patch file")
    candidate = _checked_regular_file(static_candidate_file, "static candidate", max_size=64 << 20)
    payload = candidate.read_bytes()
    materialized = _materialize(asset_dir / "static-candidates", "candidate", payload)
    return harness, {"source_file": str(materialized)}


def _checked_wheels(wheelhouse_dir: Path) -> tuple[Path, Path]:
    if wheelhouse_dir.is_symlink() or not wheelhouse_dir.is_dir():
        raise ContractError("Flask verifier wheelhouse is missing or is a symlink")
    entries = {item.name for item in wheelhouse_dir.iterdir()}
    if entries != {name for name, _, _ in _LOCKED_WHEELS}:
        raise ContractError("Flask verifier wheelhouse entries differ from lock")
    checked: list[Path] = []
    for name, size, digest in _LOCKED_WHEELS:
        path = _checked_regular_file(wheelhouse_dir / name, name, max_size=size)
        if path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ContractError(f"Flask verifier {name} differs from lock")
        checked.append(path.resolve())
    return checked[0], checked[1]


def _checked_regular_file(path: Path, name: str, *, max_size: int) -> Path:
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ContractError(f"Flask {name} must be a regular file")
    if path.stat().st_size > max_size:
        raise ContractError(f"Flask {name} exceeds the size limit")
    return path


def _materialize(directory: Path, stem: str, payload: bytes) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    destination = directory / f"{stem}-{digest}.txt"
    if directory.is_symlink():
        raise ContractError("Flask asset directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if (
            destination.is_symlink()
            or not destination.is_file()
            or destination.read_bytes() != payload
        ):
            raise ContractError(f"Flask materialized {stem} asset differs")
        return destination.resolve()
    with destination.open("xb") as stream:
        stream.write(payload)
    return destination.resolve()
