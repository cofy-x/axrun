"""Resolver for the explicit SWE-bench Verified enriched row schema."""

from __future__ import annotations

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

_FIELDS = {
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
_DATASET = "SWE-bench/SWE-bench_Verified"
_SCHEMA_VERSION = "enriched-v1"
_SUPPORTED_INSTANCE = "django__django-12419"
_SUPPORTED_REPO = "django/django"
_SUPPORTED_BASE_COMMIT = "7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
_SUPPORTED_IMAGE = "swebench/sweb.eval.x86_64.django_1776_django-12419:latest"
_SUPPORTED_TASK_IMAGE_NAMES = {
    "linux/amd64": "swebench/sweb.eval.x86_64.django_1776_django-12419",
    "linux/arm64": "library/axrun-swebench-verified-django-12419",
}
_SUPPORTED_LOG_PARSER = "parse_log_django"


class SweBenchVerifiedResolver:
    identity = _DATASET
    version = _SCHEMA_VERSION

    def resolve(
        self,
        row: dict[str, Any],
        *,
        asset_dir: Path,
        episode_id: str,
        inference_environment_id: str,
        verification_environment_id: str,
        task_image: str,
        task_platform: str = "linux/amd64",
        harness: HarnessSpec,
    ) -> ResolvedEpisode:
        if set(row) != _FIELDS:
            missing = sorted(_FIELDS - set(row))
            unknown = sorted(set(row) - _FIELDS)
            raise ContractError(
                f"invalid SWE-bench Verified {_SCHEMA_VERSION} row "
                f"(missing={missing}, unknown={unknown})"
            )
        strings = {
            key: _required_string(row, key) for key in _FIELDS - {"FAIL_TO_PASS", "PASS_TO_PASS"}
        }
        base_commit = strings["base_commit"]
        if len(base_commit) != 40 or any(value not in "0123456789abcdef" for value in base_commit):
            raise ContractError("SWE-bench Verified base_commit must be lowercase Git SHA-1")
        setup_commit = strings["environment_setup_commit"]
        if len(setup_commit) != 40 or any(
            value not in "0123456789abcdef" for value in setup_commit
        ):
            raise ContractError(
                "SWE-bench Verified environment_setup_commit must be lowercase Git SHA-1"
            )
        fail_to_pass = _test_list(row, "FAIL_TO_PASS", require_nonempty=True)
        pass_to_pass = _test_list(row, "PASS_TO_PASS", require_nonempty=False)
        if strings["eval_type"] != "pass_and_fail":
            raise ContractError("SWE-bench Verified resolver requires pass_and_fail eval_type")
        supported = {
            "instance_id": _SUPPORTED_INSTANCE,
            "repo": _SUPPORTED_REPO,
            "base_commit": _SUPPORTED_BASE_COMMIT,
            "image": _SUPPORTED_IMAGE,
            "log_parser": _SUPPORTED_LOG_PARSER,
        }
        for key, expected in supported.items():
            if strings[key] != expected:
                raise ContractError(
                    f"minimal SWE-bench Verified vertical requires {key}={expected}"
                )
        if not _digest_image(task_image):
            raise ContractError("SWE-bench task_image must use an OCI sha256 digest")
        expected_image_name = _SUPPORTED_TASK_IMAGE_NAMES.get(task_platform)
        if expected_image_name is None:
            raise ContractError("SWE-bench task_platform must be linux/amd64 or linux/arm64")
        if _image_name(task_image) != expected_image_name:
            raise ContractError(
                f"SWE-bench task_image does not match the {task_platform} image contract"
            )
        resolved_harness = resolve_claude_code_spec(harness)
        seed_digest = canonical_digest(
            {
                "dataset": _DATASET,
                "row_schema": _SCHEMA_VERSION,
                "row": row,
            }
        )
        assets = asset_dir / seed_digest
        prompt = _write_asset(assets / "problem.txt", strings["problem_statement"])
        eval_script = _write_asset(assets / "eval.sh", strings["eval_script"])
        verifier = Path(__file__).parents[1] / "fixtures" / "swebench_verified" / "run_verifier.py"
        if not verifier.is_file():
            raise ContractError("packaged SWE-bench Verified verifier is missing")
        return ResolvedEpisode(
            schema_version=1,
            episode_id=episode_id,
            task_id=strings["instance_id"],
            seed_digest=seed_digest,
            prompt_file=str(prompt),
            task=TaskSpec(
                identity="swebench-verified",
                version="1",
                config={"base_commit": base_commit},
            ),
            inference_environment=EnvironmentBinding(
                inference_environment_id, task_image, task_platform, "/testbed"
            ),
            verification_environment=EnvironmentBinding(
                verification_environment_id, task_image, task_platform, "/testbed"
            ),
            harness=resolved_harness,
            candidate=CandidateSpec(identity="git-patch", version="1"),
            verifier=VerifierSpec(
                identity="swebench-verified",
                version="1",
                config={
                    "eval_script_file": str(eval_script),
                    "fail_to_pass": list(fail_to_pass),
                    "pass_to_pass": list(pass_to_pass),
                    "log_parser": strings["log_parser"],
                    "verifier_file": str(verifier),
                },
            ),
            metadata={
                "dataset_identity": _DATASET,
                "dataset_version": _SCHEMA_VERSION,
                "difficulty": strings["difficulty"],
                "official_image": strings["image"],
                "repo": strings["repo"],
                "task_image": task_image,
                "task_platform": task_platform,
                "version": strings["version"],
            },
        )


def _required_string(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or (not value and key != "hints_text"):
        raise ContractError(f"SWE-bench Verified field {key} must be a string")
    return value


def _test_list(row: dict[str, Any], key: str, *, require_nonempty: bool) -> tuple[str, ...]:
    value = row.get(key)
    if not isinstance(value, list) or (require_nonempty and not value):
        raise ContractError(f"SWE-bench Verified field {key} must be a string array")
    tests = cast(list[object], value)
    if any(not isinstance(item, str) or not item for item in tests):
        raise ContractError(f"SWE-bench Verified field {key} must be a string array")
    result = tuple(cast(list[str], tests))
    if len(result) != len(set(result)):
        raise ContractError(f"SWE-bench Verified field {key} contains duplicates")
    return result


def _digest_image(value: str) -> bool:
    name, separator, digest = value.rpartition("@sha256:")
    return bool(name and separator and len(digest) == 64) and all(
        character in "0123456789abcdef" for character in digest
    )


def _image_name(value: str) -> str:
    without_digest = value.split("@", 1)[0]
    tail = without_digest.rsplit("/", 1)[-1]
    if ":" in tail:
        without_digest = without_digest.rsplit(":", 1)[0]
    return without_digest.removeprefix("docker.io/").removeprefix("index.docker.io/")


def _write_asset(path: Path, value: str) -> Path:
    payload = value.encode()
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != payload:
            raise ContractError(f"resolved SWE-bench asset differs: {path.name}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path
