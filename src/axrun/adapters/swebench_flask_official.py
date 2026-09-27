"""Unregistered, closed verifier adapter for SWE-bench Verified Flask-5014."""

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
from axrun.fixtures.swebench_flask_official import run_verifier as flask_verifier
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
)

_INSTANCE_ID = "pallets__flask-5014"
_TASK_IMAGE = (
    "docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014"
    "@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4"
)
_IMAGE_HEAD = "966bb873e3a1e42d857362a17f5af2533dfd8f46"
_HARNESS_COMMIT = "f7bbbb2ccdf479001d6467c9e34af59e44a840f9"
_EVAL_SCRIPT_SHA256 = "a752d2d3520db71513c263dd476e8da457395a447a346f6b5c18782dc0faf034"
_WHEELS = {
    "setuptools_wheel_file": (
        "setuptools-70.0.0-py3-none-any.whl",
        863_432,
        "54faa7f2e8d2d11bcd2c07bed282eef1046b5c080d1c32add737d7b5817b1ad4",
    ),
    "wheel_wheel_file": (
        "wheel-0.45.1-py3-none-any.whl",
        72_494,
        "708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248",
    ),
}
_RUNNER = Path(__file__).parents[1] / "fixtures" / "swebench_flask_official" / "run_verifier.py"
_RESULT = "/outputs/verification.json"
_LOG = "/outputs/verifier.log"
_CONFIG_KEYS = {
    "verifier_file",
    "eval_script_file",
    "eval_script_sha256",
    "fail_to_pass",
    "pass_to_pass",
    "log_parser",
    "setuptools_wheel_file",
    "wheel_wheel_file",
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
_TEST_STATUSES = {"PASSED", "FAILED", "SKIPPED", "ERROR", "XFAIL"}


def _digest(path: Path, *, size: int | None = None, expected_sha256: str = "") -> str:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            raise ContractError("Flask verifier asset must be a regular file")
        if size is not None and path.stat().st_size != size:
            raise ContractError("Flask verifier asset size differs from lock")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContractError("Flask verifier asset is unavailable") from exc
    if expected_sha256 and digest != expected_sha256:
        raise ContractError("Flask verifier asset SHA-256 differs from lock")
    return digest


def _sealed_bytes(artifact: Artifact) -> bytes:
    path = Path(artifact.path)
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            raise ContractError("Flask sealed output is not a regular file")
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError("Flask sealed output is unavailable") from exc
    if (
        len(payload) != artifact.size_bytes
        or hashlib.sha256(payload).hexdigest() != artifact.sha256
    ):
        raise ContractError("Flask sealed output integrity mismatch")
    return payload


def _config_path(config: dict[str, Any], key: str) -> Path:
    value = config[key]
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ContractError(f"Flask verifier {key} must be an absolute file path")
    return Path(value)


def _selection(config: dict[str, Any], key: str, count: int) -> list[str]:
    raw = config[key]
    if not isinstance(raw, list):
        raise ContractError(f"Flask verifier {key} must contain {count} tests")
    tests = cast(list[object], raw)
    if len(tests) != count:
        raise ContractError(f"Flask verifier {key} must contain {count} tests")
    if any(not isinstance(test, str) or not test for test in tests):
        raise ContractError(f"Flask verifier {key} must be a string array")
    result = cast(list[str], tests)
    if len(result) != len(set(result)):
        raise ContractError(f"Flask verifier {key} contains duplicate tests")
    return result


@dataclass(frozen=True, slots=True)
class SweBenchFlaskOfficialVerifierAdapter(CommandVerifierAdapter):
    """One immutable image, dataset row, parser and offline asset contract."""

    name: str = "swebench-flask-official"
    version: str = "1"

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan:
        if (
            episode.task_id != _INSTANCE_ID
            or episode.task.identity != self.name
            or episode.task.version != self.version
            or episode.task.config != {"base_commit": _IMAGE_HEAD}
            or episode.verifier.identity != self.name
            or episode.verifier.version != self.version
        ):
            raise ContractError("Flask official verifier requires the locked single instance")
        binding = episode.verification_environment
        if (
            episode.metadata.get("official_source_image") != _TASK_IMAGE
            or episode.metadata.get("task_image") != binding.image
            or binding.image != episode.inference_environment.image
            or binding.platform != "linux/amd64"
            or episode.inference_environment.platform != "linux/amd64"
            or binding.working_directory != "/testbed"
            or episode.inference_environment.working_directory != "/testbed"
            or episode.verification_network != StageNetworkPolicy.DENY_ALL
        ):
            raise ContractError("Flask official verifier requires the locked offline amd64 image")
        if (
            candidate.episode_id != episode.episode_id
            or candidate.task_id != episode.task_id
            or candidate.seed_digest != episode.seed_digest
            or candidate.candidate != "git-patch"
            or candidate.candidate_version != "1"
            or len(candidate.files) != 1
            or candidate.files[0].role != "patch"
        ):
            raise ContractError("Flask official verifier requires this episode's single patch role")
        patch = candidate.files[0]
        patch_path = Path(candidate.root) / patch.bundle_path
        _digest(patch_path, size=patch.size_bytes, expected_sha256=patch.sha256)

        config = episode.verifier.config
        if set(config) != _CONFIG_KEYS:
            raise ContractError("Flask verifier configuration is incomplete or unknown")
        expected_values = {
            "instance_id": _INSTANCE_ID,
            "harness_commit": _HARNESS_COMMIT,
            "eval_script_sha256": _EVAL_SCRIPT_SHA256,
            "log_parser": "parse_log_flask",
            "eval_timeout_seconds": 1800,
        }
        if any(config[key] != value for key, value in expected_values.items()):
            raise ContractError("Flask verifier configuration differs from the official lock")
        if episode.verifier.timeout_seconds != 1860:
            raise ContractError("Flask verifier Run timeout differs from the locked bound")
        fail_to_pass = _selection(config, "fail_to_pass", 1)
        pass_to_pass = _selection(config, "pass_to_pass", 59)
        if set(fail_to_pass) & set(pass_to_pass):
            raise ContractError("Flask verifier expected test classes overlap")
        verifier_file = _config_path(config, "verifier_file")
        if verifier_file != _RUNNER:
            raise ContractError("Flask verifier runner must be the packaged asset")
        verifier_sha = _digest(verifier_file)
        eval_script = _config_path(config, "eval_script_file")
        _digest(eval_script, expected_sha256=_EVAL_SCRIPT_SHA256)
        inputs = [
            InputFile(str(patch_path), "/inputs/candidate.patch", patch.sha256),
            InputFile(str(verifier_file), "/opt/axrun-flask/run_verifier.py", verifier_sha),
            InputFile(str(eval_script), "/opt/axrun-flask/eval.sh", _EVAL_SCRIPT_SHA256),
        ]
        for key, (name, size, sha256) in _WHEELS.items():
            path = _config_path(config, key)
            if path.name != name:
                raise ContractError("Flask verifier wheel filename differs from lock")
            _digest(path, size=size, expected_sha256=sha256)
            inputs.append(InputFile(str(path), f"/opt/axrun-wheelhouse/{name}", sha256))

        return StagePlan(
            environment_id=binding.environment_id,
            argv=(
                "python3",
                "/opt/axrun-flask/run_verifier.py",
                "--workspace",
                "/testbed",
                "--candidate",
                "/inputs/candidate.patch",
                "--candidate-sha256",
                patch.sha256,
                "--candidate-digest",
                candidate.digest,
                "--eval-script",
                "/opt/axrun-flask/eval.sh",
                "--fail-to-pass",
                json.dumps(fail_to_pass, separators=(",", ":")),
                "--pass-to-pass",
                json.dumps(pass_to_pass, separators=(",", ":")),
                "--eval-timeout-seconds",
                "1800",
                "--result",
                _RESULT,
                "--log",
                _LOG,
            ),
            cwd="/testbed",
            inputs=tuple(inputs),
            env={"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": "/opt/axrun-wheelhouse"},
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
                f"Flask official verifier failed with exit code {result.exit_code}: "
                f"{result.diagnostic_code}"
            )
        artifact = result.artifact_for_path(_RESULT)
        log = result.artifact_for_path(_LOG)
        try:
            raw: Any = json.loads(_sealed_bytes(artifact).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("Flask verifier result is not valid JSON") from exc
        log_bytes = _sealed_bytes(log)
        if not isinstance(raw, dict) or set(cast(dict[object, object], raw)) != _RESULT_KEYS:
            raise ContractError("Flask verifier result has an incomplete or unknown schema")
        payload = cast(dict[str, Any], raw)
        if payload["schema_version"] != "axrun.swebench-flask-official-result@1":
            raise ContractError("Flask verifier result schema differs")
        digest = payload["candidate_digest"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ContractError("Flask verifier candidate digest is invalid")
        if payload["test_output_sha256"] != log.sha256:
            raise ContractError("Flask verifier result does not match its sealed test log")
        if not isinstance(payload["resolved"], bool):
            raise ContractError("Flask verifier resolution must be boolean")
        classification = payload["classification"]
        if classification in {"empty_patch_unscored", "patch_apply_failed_unscored"}:
            expected_diagnostic = (
                "SWEBENCH_EMPTY_PATCH"
                if classification == "empty_patch_unscored"
                else "SWEBENCH_PATCH_APPLY_FAILED"
            )
            expected_apply = None if classification == "empty_patch_unscored" else False
            if (
                payload["resolved"]
                or payload["score"] is not None
                or payload["diagnostic_code"] != expected_diagnostic
                or payload["patch_successfully_applied"] is not expected_apply
                or payload["status_map"] is not None
                or payload["tests_status"] is not None
                or payload["missing_expected"] is not None
                or payload["eval_exit_code"] is not None
                or log.size_bytes != 0
            ):
                raise ContractError("Flask unscored patch must remain test-free")
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
                or not isinstance(payload["status_map"], dict)
                or not isinstance(payload["tests_status"], dict)
                or not isinstance(payload["missing_expected"], list)
            ):
                raise ContractError("Flask scored result fields are inconsistent")
            self._check_test_details(payload)
            self._check_sealed_test_log(payload, log_bytes)
        else:
            raise ContractError("Flask verifier result classification is unknown")
        started_at = payload["started_at"]
        completed_at = payload["completed_at"]
        if not isinstance(started_at, str) or not isinstance(completed_at, str):
            raise ContractError("Flask verifier result timestamps are invalid")
        return VerificationResult(
            schema_version=1,
            candidate_digest=digest,
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
    def _check_test_details(payload: dict[str, Any]) -> None:
        statuses = cast(dict[object, object], payload["status_map"])
        if any(
            not isinstance(key, str) or not isinstance(value, str) or value not in _TEST_STATUSES
            for key, value in statuses.items()
        ):
            raise ContractError("Flask verifier status map contains an invalid status")
        sections = cast(dict[str, object], payload["tests_status"])
        if set(sections) != _STATUS_CATEGORIES:
            raise ContractError("Flask verifier test report categories are incomplete")
        scored_failures = 0
        expected_cases: set[str] = set()
        for category, expected_count in (
            ("FAIL_TO_PASS", 1),
            ("PASS_TO_PASS", 59),
            ("FAIL_TO_FAIL", 0),
            ("PASS_TO_FAIL", 0),
        ):
            section = sections[category]
            if not isinstance(section, dict):
                raise ContractError("Flask verifier test report section is malformed")
            members = cast(dict[object, object], section)
            if set(members) != {"success", "failure"}:
                raise ContractError("Flask verifier test report section is malformed")
            success_value = members["success"]
            failure_value = members["failure"]
            if not isinstance(success_value, list) or not isinstance(failure_value, list):
                raise ContractError("Flask verifier test report section is malformed")
            success = cast(list[object], success_value)
            failure = cast(list[object], failure_value)
            if (
                any(not isinstance(item, str) for item in [*success, *failure])
                or len(success) + len(failure) != expected_count
                or len(set([*success, *failure])) != expected_count
            ):
                raise ContractError("Flask verifier test report denominator differs")
            if category in {"FAIL_TO_PASS", "PASS_TO_PASS"}:
                cases = cast(list[str], [*success, *failure])
                if expected_cases & set(cases):
                    raise ContractError("Flask verifier expected test classes overlap")
                expected_cases.update(cases)
                if any(statuses.get(item) not in {"PASSED", "XFAIL"} for item in success):
                    raise ContractError("Flask verifier success contradicts the status map")
                if any(statuses.get(item) in {"PASSED", "XFAIL", "SKIPPED"} for item in failure):
                    raise ContractError("Flask verifier failure contradicts the status map")
                scored_failures += len(failure)
        resolved = scored_failures == 0
        if payload["resolved"] is not resolved:
            raise ContractError("Flask verifier resolution differs from test report")
        missing = payload["missing_expected"]
        if any(not isinstance(item, str) for item in missing) or len(missing) != len(set(missing)):
            raise ContractError("Flask verifier missing-test list is malformed")
        if missing != sorted(expected_cases - statuses.keys()):
            raise ContractError("Flask verifier missing-test status contradicts the log")

    @staticmethod
    def _check_sealed_test_log(payload: dict[str, Any], log_bytes: bytes) -> None:
        try:
            log_text = log_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError("Flask sealed test log is not UTF-8") from exc
        sections = cast(dict[str, dict[str, list[str]]], payload["tests_status"])
        fail_to_pass = [
            *sections["FAIL_TO_PASS"]["success"],
            *sections["FAIL_TO_PASS"]["failure"],
        ]
        pass_to_pass = [
            *sections["PASS_TO_PASS"]["success"],
            *sections["PASS_TO_PASS"]["failure"],
        ]
        try:
            grade = flask_verifier.score_log(log_text, fail_to_pass, pass_to_pass)
        except flask_verifier.VerifierError as exc:
            raise ContractError("Flask sealed test log cannot be graded") from exc
        for key in ("status_map", "tests_status", "missing_expected", "resolved"):
            if payload[key] != grade[key]:
                raise ContractError("Flask verifier result differs from its sealed test log")
