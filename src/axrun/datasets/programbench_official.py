"""Closed resolver for the stage-zero ProgramBench 1.2.4 official instance lock."""

from __future__ import annotations

import hashlib
import json
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

_IDENTITY = "programbench.official-single"
_VERSION = "programbench-1.2.4-tty-clock-f2f847c-v1"
_PROGRAMBENCH_VERSION = "1.2.4"
_PROGRAMBENCH_GIT_SHA = "963063c9271cc40fa179977356782ea4582e0b0c"
_INSTANCE = "xorg62__tty-clock.f2f847c"
_REPOSITORY = "xorg62/tty-clock"
_COMMIT = "f2f847cf2cc2949c8a8b7779a778f366d3743474"
_LANGUAGE = "c"
_DIFFICULTY = "easy"
_PLATFORM = "linux/amd64"
_IMAGE_TAG = "docker.io/programbench/xorg62_1776_tty-clock.f2f847c:task_cleanroom_v6"
_IMAGE_DIGEST = "sha256:7c070e64a44e0b7dc2a032acf02159da43a0a4993a154b5fd98c4ab997726272"
_IMAGE_REFERENCE = f"docker.io/programbench/xorg62_1776_tty-clock.f2f847c@{_IMAGE_DIGEST}"
_IMAGE_CONFIG_DIGEST = "sha256:d433c4a48704aee0b45a0f97b43f8bfee5a76bd4299bdeb1133b649e3e151820"
_HF_REPOSITORY = "programbench/ProgramBench-Tests"
_HF_REVISION = "de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5"
_BRANCHES = {
    "89bbe1810fa3": (12261, "b70f0d0f54d01410de343b14a27a8831b95512e77662c7c7ff74d13dbd5095b5"),
    "9951be903ea4": (10502, "62727f9092aea5ec4b5cf23b8717da3768059cfbd4322927243ead31634ab882"),
    "b2bd72001100": (9763, "bbea41ad480413a43db1e4423d7d3540264e322e3cc37dce87087182499c8a07"),
    "b48a2e05f04f": (10290, "0480561b30d79061894a00886ce358c4c69be0b3af22d4321d7f583532e53347"),
    "dc1d19eea619": (14420, "708404eb4dec87af386bef968f301d74fbedcaebe017e7ab964c451234415442"),
    "ed5c2b1ffc48": (92070, "b98a5f5468f1ee1f75342a004123041cebebea5b356b4016582d0174086ccf79"),
}
_ACTIVE_TESTS = 281
_IGNORED_TESTS = 38
_CAPABILITY = "post-compile-allocation-snapshot-v1"
_EVALUATOR_CONTRACT = "programbench-1.2.4-axrun-tty-clock-v1"
_TEST_MANIFEST_DIGEST = "9ce2363b10524b1f71c831949cf08e409aa6b482136f6c4844f68ab614964200"
_COMPILE_DIGEST = "eebb1a4f2452b314eac920e2dedd3b34b1a5d2b30621d23fef23ac92e4603d66"
_BRANCH_DIGEST = "9cc0fe9c6dcb3d2dc05ae7ed037d1e1208819c33fd05b5af2c482d3d1b6c2012"


class ProgramBenchOfficialSingleResolver:
    """Resolve only the immutable tty-clock contract; execution remains fail-closed.

    Axern SDK 0.10.0 exposes the required Run rootfs result and derived Environment contract. The
    closed catalog still has no adapters for the task/verifier identities emitted here: official
    evaluator orchestration and parity must be implemented before this contract becomes runnable.
    """

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
        harness: HarnessSpec,
        test_assets_dir: Path | None = None,
        static_candidate_dir: Path | None = None,
    ) -> ResolvedEpisode:
        expected = {
            "schema_version",
            "dataset_identity",
            "dataset_version",
            "programbench_version",
            "programbench_git_sha",
            "instance_id",
            "repository",
            "commit",
            "language",
            "difficulty",
            "prompt_file",
            "prompt_sha256",
            "task_metadata_file",
            "task_metadata_sha256",
            "tests_metadata_file",
            "tests_metadata_sha256",
            "asset_lock_file",
            "asset_lock_sha256",
            "image",
            "test_assets",
            "candidate",
            "required_verification_capability",
        }
        if set(row) != expected:
            raise ContractError("ProgramBench official row has an invalid shape")
        fixed: dict[str, object] = {
            "schema_version": 1,
            "dataset_identity": self.identity,
            "dataset_version": self.version,
            "programbench_version": _PROGRAMBENCH_VERSION,
            "programbench_git_sha": _PROGRAMBENCH_GIT_SHA,
            "instance_id": _INSTANCE,
            "repository": _REPOSITORY,
            "commit": _COMMIT,
            "language": _LANGUAGE,
            "difficulty": _DIFFICULTY,
            "required_verification_capability": _CAPABILITY,
        }
        for key, value in fixed.items():
            if row[key] != value:
                raise ContractError(f"ProgramBench official field {key} is unsupported")
        self._validate_image(row["image"])
        self._validate_test_assets(row["test_assets"])
        if row["candidate"] != {
            "identity": "workspace-archive",
            "version": "1",
            "exclude_paths": ["executable"],
        }:
            raise ContractError("ProgramBench official candidate contract is unsupported")
        root = source_dir.resolve()
        prompt = _checked_file(root, row, "prompt")
        _checked_file(root, row, "task_metadata")
        tests_path, tests = _checked_json_file(root, row, "tests_metadata")
        lock_path, lock = _checked_json_file(root, row, "asset_lock")
        self._validate_tests(tests)
        self._validate_lock(lock)
        compile_file = root / "verifier" / "compile_candidate.py"
        branch_file = root / "verifier" / "run_branch.py"
        if _sha256(compile_file) != _COMPILE_DIGEST or _sha256(branch_file) != _BRANCH_DIGEST:
            raise ContractError("ProgramBench official evaluator asset digest mismatch")
        if inference_environment_id == verification_environment_id:
            raise ContractError(
                "ProgramBench official verification requires a different Environment"
            )
        resolved_harness = self._resolve_harness(harness)
        asset_directory = (test_assets_dir or root).resolve()
        candidate_config: dict[str, Any] = {"exclude_paths": ["executable"]}
        if static_candidate_dir is not None:
            if resolved_harness.identity != "static-candidate":
                raise ContractError("static candidate directory requires static-candidate@1")
            candidate_root = static_candidate_dir.resolve()
            if (
                not candidate_root.is_dir()
                or candidate_root.is_symlink()
                or any(path.is_symlink() for path in candidate_root.rglob("*"))
            ):
                raise ContractError("ProgramBench static candidate directory is invalid")
            manifest = {
                path.relative_to(candidate_root).as_posix(): _sha256(path)
                for path in sorted(candidate_root.rglob("*"))
                if path.is_file()
            }
            candidate_config.update(
                source_directory=str(candidate_root),
                source_mode="overlay",
                source_manifest_digest=canonical_digest(manifest),
            )
        task_config: dict[str, Any] = {
            "instance_id": _INSTANCE,
            "repository": _REPOSITORY,
            "commit": _COMMIT,
            "language": _LANGUAGE,
            "difficulty": _DIFFICULTY,
            "programbench_version": _PROGRAMBENCH_VERSION,
            "programbench_git_sha": _PROGRAMBENCH_GIT_SHA,
            "official_image_digest": _IMAGE_DIGEST,
            "test_blob_revision": _HF_REVISION,
            "active_branch_count": len(_BRANCHES),
            "active_test_count": _ACTIVE_TESTS,
            "ignored_test_count": _IGNORED_TESTS,
        }
        return ResolvedEpisode(
            schema_version=1,
            episode_id=episode_id,
            task_id=_INSTANCE,
            seed_digest=canonical_digest(row),
            prompt_file=str(prompt),
            task=TaskSpec("programbench-official-single", "1", task_config),
            inference_environment=EnvironmentBinding(
                inference_environment_id, _IMAGE_REFERENCE, _PLATFORM, "/workspace"
            ),
            verification_environment=EnvironmentBinding(
                verification_environment_id, _IMAGE_REFERENCE, _PLATFORM, "/workspace"
            ),
            harness=resolved_harness,
            candidate=CandidateSpec("workspace-archive", "1", candidate_config),
            verifier=VerifierSpec(
                "programbench-official-single",
                "1",
                config={
                    "asset_lock_file": str(lock_path),
                    "tests_metadata_file": str(tests_path),
                    "required_public_capability": _CAPABILITY,
                    "test_assets_dir": str(asset_directory),
                    "evaluator_contract": _EVALUATOR_CONTRACT,
                    "compile_file": str(compile_file),
                    "compile_sha256": _COMPILE_DIGEST,
                    "branch_file": str(branch_file),
                    "branch_sha256": _BRANCH_DIGEST,
                },
            ),
            metadata={
                "dataset_identity": self.identity,
                "dataset_version": self.version,
                "programbench_instance": _INSTANCE,
                "programbench_official_instance": "true",
                "programbench_stage_zero": "public_snapshot_capability_validated",
            },
        )

    @staticmethod
    def _resolve_harness(harness: HarnessSpec) -> HarnessSpec:
        if harness.identity == "claude-code":
            return resolve_claude_code_spec(harness)
        if (harness.identity, harness.version, harness.config) == ("static-candidate", "1", {}):
            return harness
        raise ContractError(
            "ProgramBench official stage-zero resolver supports empty static-candidate@1 "
            "or claude-code@2.1.205"
        )

    @staticmethod
    def _validate_image(value: object) -> None:
        expected = {
            "source_tag": _IMAGE_TAG,
            "platform": _PLATFORM,
            "platform_reference": _IMAGE_REFERENCE,
            "platform_digest": _IMAGE_DIGEST,
            "config_digest": _IMAGE_CONFIG_DIGEST,
        }
        if value != expected:
            raise ContractError("ProgramBench official image lock is unsupported")

    @staticmethod
    def _validate_test_assets(value: object) -> None:
        expected = {
            "repository": _HF_REPOSITORY,
            "revision": _HF_REVISION,
            "branch_count": len(_BRANCHES),
            "active_test_count": _ACTIVE_TESTS,
            "ignored_test_count": _IGNORED_TESTS,
            "manifest_sha256": _TEST_MANIFEST_DIGEST,
        }
        if value != expected:
            raise ContractError("ProgramBench official test asset lock is unsupported")

    @staticmethod
    def _validate_tests(value: dict[str, Any]) -> None:
        if set(value) != {"branches"} or not isinstance(value["branches"], dict):
            raise ContractError("ProgramBench official tests metadata has an invalid shape")
        branches = cast(dict[str, object], value["branches"])
        if set(branches) != set(_BRANCHES):
            raise ContractError("ProgramBench official test branches do not match the lock")
        active_count = 0
        ignored_count = 0
        for raw in branches.values():
            if not isinstance(raw, dict):
                raise ContractError("ProgramBench official branch metadata has an invalid shape")
            branch = cast(dict[str, object], raw)
            if set(branch) != {"ignored", "ignore_reason", "tests", "ignored_tests"}:
                raise ContractError("ProgramBench official branch metadata has an invalid shape")
            if branch["ignored"] is not False or branch["ignore_reason"] != "":
                raise ContractError("ProgramBench official active branch metadata changed")
            raw_tests = branch["tests"]
            raw_ignored = branch["ignored_tests"]
            if not isinstance(raw_tests, list):
                raise ContractError("ProgramBench official expected tests are invalid")
            test_items = cast(list[object], raw_tests)
            if not all(isinstance(item, str) for item in test_items):
                raise ContractError("ProgramBench official expected tests are invalid")
            if not isinstance(raw_ignored, list):
                raise ContractError("ProgramBench official ignored tests are invalid")
            ignored_items = cast(list[object], raw_ignored)
            if not all(isinstance(item, dict) for item in ignored_items):
                raise ContractError("ProgramBench official ignored tests are invalid")
            tests = cast(list[str], raw_tests)
            ignored = cast(list[dict[str, object]], raw_ignored)
            if not all(isinstance(item.get("name"), str) for item in ignored):
                raise ContractError("ProgramBench official ignored test name is invalid")
            ignored_names = {cast(str, item["name"]) for item in ignored}
            if not ignored_names <= set(tests):
                raise ContractError("ProgramBench official ignored test is not expected")
            ignored_count += len(ignored_names)
            active_count += len(tests) - len(ignored_names)
        if (active_count, ignored_count) != (_ACTIVE_TESTS, _IGNORED_TESTS):
            raise ContractError("ProgramBench official test denominator changed")

    @staticmethod
    def _validate_lock(value: dict[str, Any]) -> None:
        try:
            programbench = value["programbench"]
            instance = value["instance"]
            image = value["image"]
            test_blobs = value["test_blobs"]
            evaluator = value["evaluator"]
        except KeyError as exc:
            raise ContractError("ProgramBench official asset lock is incomplete") from exc
        if set(value) != {
            "schema_version",
            "programbench",
            "instance",
            "image",
            "evaluator",
            "test_blobs",
        }:
            raise ContractError("ProgramBench official asset lock has unknown fields")
        if value["schema_version"] != 1 or programbench != {
            "package_version": _PROGRAMBENCH_VERSION,
            "git_sha": _PROGRAMBENCH_GIT_SHA,
        }:
            raise ContractError("ProgramBench official version lock changed")
        if not isinstance(instance, dict):
            raise ContractError("ProgramBench official instance lock changed")
        instance_data = cast(dict[str, object], instance)
        if instance_data.get("instance_id") != _INSTANCE:
            raise ContractError("ProgramBench official instance lock changed")
        if image != {
            "source": _IMAGE_TAG,
            "platform": _PLATFORM,
            "platform_digest": _IMAGE_DIGEST,
            "config_digest": _IMAGE_CONFIG_DIGEST,
        }:
            raise ContractError("ProgramBench official image asset lock changed")
        if evaluator != {
            "contract_version": _EVALUATOR_CONTRACT,
            "compile_file": "verifier/compile_candidate.py",
            "compile_sha256": _COMPILE_DIGEST,
            "branch_file": "verifier/run_branch.py",
            "branch_sha256": _BRANCH_DIGEST,
        }:
            raise ContractError("ProgramBench official evaluator asset lock changed")
        if not isinstance(test_blobs, dict):
            raise ContractError("ProgramBench official blob repository changed")
        blob_data = cast(dict[str, object], test_blobs)
        if blob_data.get("repository") != _HF_REPOSITORY:
            raise ContractError("ProgramBench official blob repository changed")
        if blob_data.get("revision") != _HF_REVISION:
            raise ContractError("ProgramBench official blob revision changed")
        raw_branches = blob_data.get("branches")
        if not isinstance(raw_branches, dict):
            raise ContractError("ProgramBench official blob branches changed")
        branch_items = cast(dict[object, object], raw_branches)
        if set(branch_items) != set(_BRANCHES):
            raise ContractError("ProgramBench official blob branches changed")
        branch_data = cast(dict[str, object], raw_branches)
        for branch, (size, digest) in _BRANCHES.items():
            if branch_data[branch] != {
                "path": f"{_INSTANCE}/tests/{branch}.tar.gz",
                "size_bytes": size,
                "sha256": digest,
            }:
                raise ContractError("ProgramBench official blob manifest changed")


def _checked_file(root: Path, row: dict[str, Any], prefix: str) -> Path:
    name = row.get(f"{prefix}_file")
    digest = row.get(f"{prefix}_sha256")
    if not isinstance(name, str) or not name or not isinstance(digest, str):
        raise ContractError(f"ProgramBench official {prefix} reference is invalid")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ContractError(f"ProgramBench official {prefix} path is unsafe")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ContractError(f"ProgramBench official {prefix} file is missing")
    if _sha256(path) != digest:
        raise ContractError(f"ProgramBench official {prefix} digest mismatch")
    return path


def _checked_json_file(root: Path, row: dict[str, Any], prefix: str) -> tuple[Path, dict[str, Any]]:
    path = _checked_file(root, row, prefix)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractError(f"ProgramBench official {prefix} must be a JSON object")
    return path, cast(dict[str, Any], raw)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
