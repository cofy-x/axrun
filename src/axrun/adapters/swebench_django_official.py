"""Closed official verifier adapter for SWE-bench Verified Django-12419."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from axrun.adapters.command_verifier import CommandVerifierAdapter
from axrun.errors import ContractError, InfrastructureError
from axrun.fixtures.swebench_django_official import run_verifier as django_verifier
from axrun.models import (
    Artifact,
    CandidateBundle,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StageNetworkPolicy,
    StagePlan,
    StageResult,
    VerificationResult,
    canonical_digest,
)

_INSTANCE_ID = "django__django-12419"
_TASK_IMAGE = (
    "docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419"
    "@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768"
)
_RUNTIME_IMAGE = (
    "index.docker.io/library/axrun-django-seed-0121"
    "@sha256:3912793ab27162e63adec6835a9267b150341b9b5cba1532e6d7ac8933c8cbb6"
)
_IMAGE_HEAD = "7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
_HARNESS_COMMIT = "f7bbbb2ccdf479001d6467c9e34af59e44a840f9"
_EVAL_SCRIPT_SHA256 = "da94f6e6b371f5f4f929fd0e71d2de2aa38427429380e7a18dfdc4498e5e5cd7"
_SELECTION_SHA256 = "452bd1de2fd32e99ec6f365e0dc44a09212104be795b7904965b3cfedae7a23a"
_RUNNER_SHA256 = "17b05204944b07824133a33d7b96011312d77c0b049eb1205663643fe73fea70"
_RUNNER = Path(__file__).parents[1] / "fixtures" / "swebench_django_official" / "run_verifier.py"
_RESULT = "/outputs/verification.json"
_LOG = "/outputs/verifier.log"
_CONFIG_KEYS = {
    "verifier_file",
    "eval_script_file",
    "eval_script_sha256",
    "test_selection_digest",
    "log_parser",
    "harness_commit",
    "instance_id",
    "eval_timeout_seconds",
}
_RESULT_KEYS = {
    "schema_version",
    "candidate_digest",
    "classification",
    "patch_successfully_applied",
    "resolved",
    "score",
    "diagnostic_code",
    "started_at",
    "completed_at",
    "eval_exit_code",
    "test_output_sha256",
    "status_map",
    "tests_status",
    "missing_expected",
}
_STATUS_CATEGORIES = {"FAIL_TO_PASS", "PASS_TO_PASS", "FAIL_TO_FAIL", "PASS_TO_FAIL"}


def _digest(path: Path, *, size: int | None = None, expected_sha256: str = "") -> str:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ContractError("Django verifier asset must be a regular file")
        if size is not None and metadata.st_size != size:
            raise ContractError("Django verifier asset size differs from lock")
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError("Django verifier asset is unavailable") from exc
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ContractError("Django verifier asset SHA-256 differs from lock")
    return digest


def _sealed_bytes(artifact: Artifact, *, media_type: str, maximum: int) -> bytes:
    if artifact.media_type != media_type or not 0 <= artifact.size_bytes <= maximum:
        raise ContractError("Django sealed output metadata differs from lock")
    path = Path(artifact.path)
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ContractError("Django sealed output is not a regular file")
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError("Django sealed output is unavailable") from exc
    if (
        len(payload) != artifact.size_bytes
        or hashlib.sha256(payload).hexdigest() != artifact.sha256
    ):
        raise ContractError("Django sealed output integrity mismatch")
    return payload


def _absolute_file(config: dict[str, Any], key: str) -> Path:
    value = config[key]
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ContractError(f"Django verifier {key} must be an absolute file path")
    return Path(value)


def validated_django_verifier_inputs(
    episode: ResolvedEpisode,
) -> tuple[InputFile, ...]:
    """Bind the exact packaged runner and private eval script, without loading a row."""
    config = episode.verifier.config
    if set(config) != _CONFIG_KEYS:
        raise ContractError("Django verifier configuration is incomplete or unknown")
    expected = {
        "instance_id": _INSTANCE_ID,
        "harness_commit": _HARNESS_COMMIT,
        "eval_script_sha256": _EVAL_SCRIPT_SHA256,
        "test_selection_digest": _SELECTION_SHA256,
        "log_parser": "parse_log_django",
        "eval_timeout_seconds": 1800,
    }
    if any(config[key] != value for key, value in expected.items()):
        raise ContractError("Django verifier configuration differs from the official lock")
    if episode.verifier.timeout_seconds != 1860:
        raise ContractError("Django verifier Run timeout differs from the locked bound")
    runner_path = _absolute_file(config, "verifier_file")
    if runner_path != _RUNNER:
        raise ContractError("Django verifier runner must be the packaged asset")
    runner_sha256 = _digest(runner_path, expected_sha256=_RUNNER_SHA256)
    eval_path = _absolute_file(config, "eval_script_file")
    _digest(eval_path, expected_sha256=_EVAL_SCRIPT_SHA256)
    return (
        InputFile(str(runner_path), "/opt/axrun-django/run_verifier.py", runner_sha256),
        InputFile(str(eval_path), "/opt/axrun-django/eval.sh", _EVAL_SCRIPT_SHA256),
    )


def _checked_json(payload: bytes) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ContractError("Django verifier result contains duplicate JSON keys")
            value[key] = item
        return value

    def reject_constant(_value: str) -> None:
        raise ContractError("Django verifier result contains nonfinite JSON")

    try:
        raw: object = json.loads(
            payload, object_pairs_hook=unique_pairs, parse_constant=reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("Django verifier result is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ContractError("Django verifier result has an incomplete or unknown schema")
    value = cast(dict[str, Any], raw)
    if set(value) != _RESULT_KEYS:
        raise ContractError("Django verifier result has an incomplete or unknown schema")
    return value


@dataclass(frozen=True, slots=True)
class SweBenchDjangoOfficialVerifierAdapter(CommandVerifierAdapter):
    """One immutable source, imported runtime, TestSpec, and parser contract."""

    name: str = "swebench-django-official"
    version: str = "1"

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan:
        if (
            episode.task_id != _INSTANCE_ID
            or episode.task.identity != self.name
            or episode.task.version != self.version
            or episode.task.config.get("base_commit") != _IMAGE_HEAD
            or episode.verifier.identity != self.name
            or episode.verifier.version != self.version
        ):
            raise ContractError("Django official verifier requires the locked single instance")
        binding = episode.verification_environment
        inference = episode.inference_environment
        if (
            episode.metadata.get("official_source_image") != _TASK_IMAGE
            or episode.metadata.get("task_image") != _RUNTIME_IMAGE
            or binding.image != _RUNTIME_IMAGE
            or inference.image != _RUNTIME_IMAGE
            or binding.platform != "linux/amd64"
            or inference.platform != "linux/amd64"
            or binding.working_directory != "/testbed"
            or inference.working_directory != "/testbed"
            or episode.verification_network != StageNetworkPolicy.DENY_ALL
        ):
            raise ContractError(
                "Django official verifier requires the locked offline amd64 runtime"
            )
        if (
            candidate.episode_id != episode.episode_id
            or candidate.task_id != episode.task_id
            or candidate.seed_digest != episode.seed_digest
            or not candidate.inference_run_id
            or candidate.candidate != "git-patch"
            or candidate.candidate_version != "1"
            or len(candidate.files) != 1
            or candidate.files[0].role != "patch"
        ):
            raise ContractError(
                "Django official verifier requires this episode's single patch role"
            )
        patch = candidate.files[0]
        patch_path = Path(candidate.root) / patch.bundle_path
        _digest(patch_path, size=patch.size_bytes, expected_sha256=patch.sha256)
        assets = validated_django_verifier_inputs(episode)
        return StagePlan(
            environment_id=binding.environment_id,
            argv=(
                "/usr/bin/python3",
                "/opt/axrun-django/run_verifier.py",
                "--workspace",
                "/testbed",
                "--candidate",
                "/inputs/candidate.patch",
                "--candidate-sha256",
                patch.sha256,
                "--candidate-digest",
                candidate.digest,
                "--eval-script",
                "/opt/axrun-django/eval.sh",
                "--eval-timeout-seconds",
                "1800",
                "--result",
                _RESULT,
                "--log",
                _LOG,
            ),
            cwd="/testbed",
            inputs=(InputFile(str(patch_path), "/inputs/candidate.patch", patch.sha256), *assets),
            env={"PIP_NO_INDEX": "1"},
            outputs=(
                OutputSpec(_RESULT, media_type="application/json", max_bytes=1 << 20),
                OutputSpec(_LOG, media_type="text/plain", max_bytes=16 << 20),
            ),
            resources=episode.verification_resources,
            network_policy=StageNetworkPolicy.DENY_ALL,
            timeout_seconds=1860,
            labels={"axrun.stage": "verification", "axrun.verifier": self.name},
        )

    def parse_result(self, result: StageResult) -> VerificationResult:
        if result.exit_code != 0:
            raise InfrastructureError(
                f"Django official verifier failed with exit code {result.exit_code}: "
                f"{result.diagnostic_code}"
            )
        if len(result.artifacts) != 2 or {item.name for item in result.artifacts} != {
            _RESULT,
            _LOG,
        }:
            raise ContractError("Django verifier sealed output set differs from contract")
        artifact = result.artifact_for_path(_RESULT)
        log = result.artifact_for_path(_LOG)
        payload = _checked_json(
            _sealed_bytes(artifact, media_type="application/json", maximum=1 << 20)
        )
        log_bytes = _sealed_bytes(log, media_type="text/plain", maximum=16 << 20)
        if payload["schema_version"] != django_verifier.RESULT_SCHEMA:
            raise ContractError("Django verifier result schema differs")
        candidate_digest = payload["candidate_digest"]
        if (
            not isinstance(candidate_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", candidate_digest) is None
        ):
            raise ContractError("Django verifier candidate digest is invalid")
        if payload["test_output_sha256"] != log.sha256:
            raise ContractError("Django verifier result does not match its sealed test log")
        if not isinstance(payload["resolved"], bool):
            raise ContractError("Django verifier resolution must be boolean")
        classification = payload["classification"]
        if classification in {"empty_patch_unscored", "patch_apply_failed_unscored"}:
            empty = classification == "empty_patch_unscored"
            if (
                payload["resolved"] is not False
                or payload["score"] is not None
                or payload["diagnostic_code"]
                != ("SWEBENCH_EMPTY_PATCH" if empty else "SWEBENCH_PATCH_APPLY_FAILED")
                or payload["patch_successfully_applied"] is not (None if empty else False)
                or payload["eval_exit_code"] is not None
                or payload["status_map"] is not None
                or payload["tests_status"] is not None
                or payload["missing_expected"] is not None
                or log_bytes
            ):
                raise ContractError("Django unscored patch must remain test-free")
            score = None
        elif classification == "scored":
            score = 1.0 if payload["resolved"] else 0.0
            if (
                type(payload["score"]) not in (int, float)
                or payload["score"] != score
                or payload["diagnostic_code"]
                != ("" if payload["resolved"] else "SWEBENCH_TESTS_FAILED")
                or payload["patch_successfully_applied"] is not True
                or type(payload["eval_exit_code"]) is not int
                or not 0 <= payload["eval_exit_code"] <= 255
            ):
                raise ContractError("Django scored result fields are inconsistent")
            self._check_test_details(payload, log_bytes)
        else:
            raise ContractError("Django verifier result classification is unknown")
        started_at, completed_at = payload["started_at"], payload["completed_at"]
        if not isinstance(started_at, str) or not isinstance(completed_at, str):
            raise ContractError("Django verifier result timestamps are invalid")
        return VerificationResult(
            schema_version=1,
            candidate_digest=candidate_digest,
            verifier=self.name,
            verifier_version=self.version,
            verdict="passed" if payload["resolved"] else "failed",
            diagnostic_code=payload["diagnostic_code"],
            verifier_exit_code=result.exit_code,
            output_digest=artifact.sha256,
            started_at=started_at,
            completed_at=completed_at,
            score=score,
            details={
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "candidate_digest",
                    "resolved",
                    "score",
                    "diagnostic_code",
                    "started_at",
                    "completed_at",
                }
            },
        )

    @staticmethod
    def _check_test_details(payload: dict[str, Any], log_bytes: bytes) -> None:
        try:
            log = log_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError("Django sealed test log is not UTF-8") from exc
        statuses_raw = payload["status_map"]
        sections_raw = payload["tests_status"]
        if not isinstance(statuses_raw, dict) or not isinstance(sections_raw, dict):
            raise ContractError("Django verifier test status map is malformed")
        statuses = cast(dict[object, object], statuses_raw)
        sections = cast(dict[str, object], sections_raw)
        if (
            any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or value not in django_verifier.TEST_STATUSES
                for key, value in statuses.items()
            )
            or set(sections) != _STATUS_CATEGORIES
        ):
            raise ContractError("Django verifier test status map is malformed")
        matching_cases = [
            case
            for case in statuses
            if isinstance(case, str)
            and canonical_digest({"fail_to_pass": [case], "pass_to_pass": []}) == _SELECTION_SHA256
        ]
        if len(matching_cases) != 1:
            raise ContractError("Django sealed status map lacks the locked test selection")
        expected_case = matching_cases[0]
        cases: dict[str, list[str]] = {}
        for category, expected_count in (
            ("FAIL_TO_PASS", 1),
            ("PASS_TO_PASS", 0),
            ("FAIL_TO_FAIL", 0),
            ("PASS_TO_FAIL", 0),
        ):
            section_raw = sections[category]
            if not isinstance(section_raw, dict):
                raise ContractError("Django verifier test report section is malformed")
            section = cast(dict[str, object], section_raw)
            if set(section) != {"success", "failure"}:
                raise ContractError("Django verifier test report section is malformed")
            success_raw, failure_raw = section["success"], section["failure"]
            if not isinstance(success_raw, list) or not isinstance(failure_raw, list):
                raise ContractError("Django verifier test report section is malformed")
            success, failure = cast(list[object], success_raw), cast(list[object], failure_raw)
            if (
                any(not isinstance(item, str) or not item for item in [*success, *failure])
                or len(success) + len(failure) != expected_count
                or len(set([*success, *failure])) != expected_count
            ):
                raise ContractError("Django verifier test report denominator differs")
            cases[category] = cast(list[str], [*success, *failure])
        if cases["FAIL_TO_PASS"] != [expected_case]:
            raise ContractError("Django verifier report differs from locked test selection")
        if payload["missing_expected"] != []:
            raise ContractError("Django verifier expected test is missing")
        try:
            grade = django_verifier.score_log(log, cases["FAIL_TO_PASS"], cases["PASS_TO_PASS"])
        except django_verifier.VerifierError as exc:
            raise ContractError("Django sealed test log cannot be graded") from exc
        for key in ("status_map", "tests_status", "missing_expected", "resolved"):
            if payload[key] != grade[key]:
                raise ContractError("Django verifier result differs from its sealed test log")
