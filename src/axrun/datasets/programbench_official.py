"""Closed resolver for explicitly qualified ProgramBench 1.2.4 instances."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError
from axrun.harnesses import resolve_claude_code_spec
from axrun.models import (
    CandidateSpec,
    EnvironmentBinding,
    HarnessSpec,
    ResolvedEpisode,
    ResourceSpec,
    TaskSpec,
    VerifierSpec,
    canonical_digest,
)

_IDENTITY = "programbench.official-single"
_VERSION = "programbench-1.2.4-tty-clock-f2f847c-v4"
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
_EVALUATOR_CONTRACT = "programbench-1.2.4-axrun-tty-clock-v4"
_DOCKER_CPUS = 10
_TEST_MANIFEST_DIGEST = "9ce2363b10524b1f71c831949cf08e409aa6b482136f6c4844f68ab614964200"
_COMPILE_DIGEST = "e0601e72ec6f3d1ebad21c1a72835ed0a511a03048b0b424d573071b634b8c88"
_BRANCH_DIGEST = "e7f74cb2570d933bda71fc138d71586a21f75db8736c3fc90defecec2726395f"
_DEPENDENCY_LOCK = "requirements.lock"
_DEPENDENCY_LOCK_DIGEST = "9b14aaddb4cd53fe338a8bf4391b0eed12ea264c49a4c47e7b774d54735f4777"
_REMOVE_HASHES = ["cd400708bcd6a5b9dd28bd450a211ec4625cde31470057e9d62f66072e297db0"]


@dataclass(frozen=True)
class _Case:
    version: str = _VERSION
    instance: str = _INSTANCE
    repository: str = _REPOSITORY
    commit: str = _COMMIT
    difficulty: str = _DIFFICULTY
    image_tag: str = _IMAGE_TAG
    image_digest: str = _IMAGE_DIGEST
    image_reference: str = _IMAGE_REFERENCE
    image_config_digest: str = _IMAGE_CONFIG_DIGEST
    branches: dict[str, tuple[int, str]] = field(default_factory=lambda: _BRANCHES)
    active_tests: int = _ACTIVE_TESTS
    ignored_tests: int = _IGNORED_TESTS
    evaluator_contract: str = _EVALUATOR_CONTRACT
    test_manifest_digest: str = _TEST_MANIFEST_DIGEST
    branch_digest: str = _BRANCH_DIGEST
    remove_hashes: list[str] = field(default_factory=lambda: _REMOVE_HASHES)
    limit_memory: str = ""

    def task_config(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance,
            "repository": self.repository,
            "commit": self.commit,
            "language": _LANGUAGE,
            "difficulty": self.difficulty,
            "programbench_version": _PROGRAMBENCH_VERSION,
            "programbench_git_sha": _PROGRAMBENCH_GIT_SHA,
            "official_image_digest": self.image_digest,
            "test_blob_revision": _HF_REVISION,
            "active_branch_count": len(self.branches),
            "active_test_count": self.active_tests,
            "ignored_test_count": self.ignored_tests,
        }


_CASES = {
    _INSTANCE: _Case(),
    "lh3__seqtk.94e7070": _Case(
        version="programbench-1.2.4-seqtk-94e7070-v1",
        instance="lh3__seqtk.94e7070",
        repository="lh3/seqtk",
        commit="94e707082d39b0a038f234df676e32d9802c0dc7",
        difficulty="",
        image_tag="docker.io/programbench/lh3_1776_seqtk.94e7070:task_cleanroom_v6",
        image_digest="sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0",
        image_reference="docker.io/programbench/lh3_1776_seqtk.94e7070@sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0",
        image_config_digest="sha256:742ff17f7c2fb045550e0545750ba44c698a9801bfffe0cdb13c9ad9610801ac",
        branches={
            "e592c32aec70": (
                107995,
                "3a9ba4e29bf1eed9cc80b8c8eab537af092fc0b559f8f05eac326b8f5a7943a0",
            ),
            "5d974fdda794": (
                73593,
                "b908e8eda5bdbb72b338c20a80ec7f18a086a92ee4f5e34a56b72303cb650d11",
            ),
        },
        active_tests=429,
        ignored_tests=11,
        evaluator_contract="programbench-1.2.4-axrun-seqtk-v1",
        test_manifest_digest="eecad6f24e3a09b3bcee6ed88ae45867f6aa929e05f9987c7d93dea25b29459e",
        branch_digest="1d17a75ccf55eb253679a5b83858bebcee0f233f810dd4e324c5efec25ad5037",
        remove_hashes=[],
        limit_memory="8GiB",
    ),
}


class ProgramBenchOfficialSingleResolver:
    """Resolve one of the explicitly locked official cases, without mutable resolver state."""

    identity = _IDENTITY

    def resolve(
        self,
        row: dict[str, Any],
        *,
        source_dir: Path,
        episode_id: str,
        inference_environment_id: str,
        verification_environment_id: str,
        harness: HarnessSpec,
        verification_image: str,
        runtime_image: str | None = None,
        test_assets_dir: Path | None = None,
        static_candidate_dir: Path | None = None,
    ) -> ResolvedEpisode:
        case = official_case(str(row.get("instance_id", "")))
        return _LockedResolver(case).resolve(
            row,
            source_dir=source_dir,
            episode_id=episode_id,
            inference_environment_id=inference_environment_id,
            verification_environment_id=verification_environment_id,
            harness=harness,
            verification_image=verification_image,
            runtime_image=runtime_image,
            test_assets_dir=test_assets_dir,
            static_candidate_dir=static_candidate_dir,
        )


def official_case(instance_id: str) -> _Case:
    case = _CASES.get(instance_id)
    if case is None:
        raise ContractError("ProgramBench official instance is unsupported")
    return case


class _LockedResolver:
    """Resolve an immutable case contract and its locked evaluator assets."""

    identity = _IDENTITY

    def __init__(self, case: _Case) -> None:
        self.case = case

    def resolve(
        self,
        row: dict[str, Any],
        *,
        source_dir: Path,
        episode_id: str,
        inference_environment_id: str,
        verification_environment_id: str,
        harness: HarnessSpec,
        verification_image: str,
        runtime_image: str | None = None,
        test_assets_dir: Path | None = None,
        static_candidate_dir: Path | None = None,
    ) -> ResolvedEpisode:
        runtime_image = runtime_image or self.case.image_reference
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
            "dataset_version": self.case.version,
            "programbench_version": _PROGRAMBENCH_VERSION,
            "programbench_git_sha": _PROGRAMBENCH_GIT_SHA,
            "instance_id": self.case.instance,
            "repository": self.case.repository,
            "commit": self.case.commit,
            "language": _LANGUAGE,
            "difficulty": self.case.difficulty,
            "required_verification_capability": _CAPABILITY,
        }
        for key, value in fixed.items():
            if row[key] != value:
                raise ContractError(f"ProgramBench official field {key} is unsupported")
        self._validate_image(row["image"])
        self._validate_test_assets(row["test_assets"])
        if (
            not runtime_image.endswith(f"@{self.case.image_digest}")
            or runtime_image.count("@") != 1
        ):
            raise ContractError("ProgramBench official runtime image must use the locked digest")
        if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", verification_image):
            raise ContractError("ProgramBench verification image requires an immutable digest")
        if verification_image.endswith(f"@{self.case.image_digest}"):
            raise ContractError("official base image is not dependency-closed for verification")
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
        dependency_lock = root / "verifier" / _DEPENDENCY_LOCK
        if (
            _sha256(compile_file) != _COMPILE_DIGEST
            or _sha256(branch_file) != self.case.branch_digest
            or _sha256(dependency_lock) != _DEPENDENCY_LOCK_DIGEST
        ):
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
        task_config = self.case.task_config()
        return ResolvedEpisode(
            schema_version=1,
            episode_id=episode_id,
            task_id=self.case.instance,
            seed_digest=canonical_digest(row),
            prompt_file=str(prompt),
            task=TaskSpec("programbench-official-single", "1", task_config),
            inference_environment=EnvironmentBinding(
                inference_environment_id, runtime_image, _PLATFORM, "/workspace"
            ),
            verification_environment=EnvironmentBinding(
                verification_environment_id, verification_image, _PLATFORM, "/workspace"
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
                    "evaluator_contract": self.case.evaluator_contract,
                    "compile_file": str(compile_file),
                    "compile_sha256": _COMPILE_DIGEST,
                    "branch_file": str(branch_file),
                    "branch_sha256": self.case.branch_digest,
                    "dependency_lock_file": str(dependency_lock),
                    "dependency_lock_sha256": _DEPENDENCY_LOCK_DIGEST,
                    "pytest_xdist_workers": _DOCKER_CPUS,
                    "remove_hashes": self.case.remove_hashes,
                },
            ),
            verification_resources=ResourceSpec(
                limit_cpu=str(_DOCKER_CPUS), limit_memory=self.case.limit_memory
            ),
            metadata={
                "dataset_identity": self.identity,
                "dataset_version": self.case.version,
                "programbench_instance": self.case.instance,
                "programbench_official_instance": "true",
                "programbench_validation_scope": "official-single-instance",
            },
        )

    @staticmethod
    def _resolve_harness(harness: HarnessSpec) -> HarnessSpec:
        if harness.identity == "claude-code":
            return resolve_claude_code_spec(harness)
        if (harness.identity, harness.version, harness.config) == ("static-candidate", "1", {}):
            return harness
        raise ContractError(
            "ProgramBench official resolver supports empty static-candidate@1 "
            "or claude-code@2.1.205"
        )

    def _validate_image(self, value: object) -> None:
        expected = {
            "source_tag": self.case.image_tag,
            "platform": _PLATFORM,
            "platform_reference": self.case.image_reference,
            "platform_digest": self.case.image_digest,
            "config_digest": self.case.image_config_digest,
        }
        if value != expected:
            raise ContractError("ProgramBench official image lock is unsupported")

    def _validate_test_assets(self, value: object) -> None:
        expected = {
            "repository": _HF_REPOSITORY,
            "revision": _HF_REVISION,
            "branch_count": len(self.case.branches),
            "active_test_count": self.case.active_tests,
            "ignored_test_count": self.case.ignored_tests,
            "manifest_sha256": self.case.test_manifest_digest,
        }
        if value != expected:
            raise ContractError("ProgramBench official test asset lock is unsupported")

    def _validate_tests(self, value: dict[str, Any]) -> None:
        if set(value) != {"branches"} or not isinstance(value["branches"], dict):
            raise ContractError("ProgramBench official tests metadata has an invalid shape")
        branches = cast(dict[str, object], value["branches"])
        if set(branches) != set(self.case.branches):
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
        if (active_count, ignored_count) != (self.case.active_tests, self.case.ignored_tests):
            raise ContractError("ProgramBench official test denominator changed")

    def _validate_lock(self, value: dict[str, Any]) -> None:
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
        if instance_data.get("instance_id") != self.case.instance:
            raise ContractError("ProgramBench official instance lock changed")
        if image != {
            "source": self.case.image_tag,
            "platform": _PLATFORM,
            "platform_digest": self.case.image_digest,
            "config_digest": self.case.image_config_digest,
        }:
            raise ContractError("ProgramBench official image asset lock changed")
        if evaluator != {
            "contract_version": self.case.evaluator_contract,
            "compile_file": "verifier/compile_candidate.py",
            "compile_sha256": _COMPILE_DIGEST,
            "branch_file": "verifier/run_branch.py",
            "branch_sha256": self.case.branch_digest,
            "dependency_lock_file": f"verifier/{_DEPENDENCY_LOCK}",
            "dependency_lock_sha256": _DEPENDENCY_LOCK_DIGEST,
            "docker_cpus": _DOCKER_CPUS,
            "remove_hashes": self.case.remove_hashes,
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
        if set(branch_items) != set(self.case.branches):
            raise ContractError("ProgramBench official blob branches changed")
        branch_data = cast(dict[str, object], raw_branches)
        for branch, (size, digest) in self.case.branches.items():
            if branch_data[branch] != {
                "path": f"{self.case.instance}/tests/{branch}.tar.gz",
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
