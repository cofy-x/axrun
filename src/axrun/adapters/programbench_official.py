"""Multi-Run verifier for one locked ProgramBench 1.2.4 official instance."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from axrun.adapters.base import VerifierQualificationRequirements
from axrun.backend import ExecutionBackend
from axrun.errors import ContractError, InfrastructureError, RecoveryRequiredError
from axrun.models import (
    Artifact,
    CandidateBundle,
    ExecutionRef,
    InputFile,
    OutputSpec,
    ResolvedEpisode,
    StagePlan,
    VerificationResult,
    canonical_digest,
    canonical_json,
)
from axrun.verification import MultiRunVerificationCoordinator

_INSTANCE = "xorg62__tty-clock.f2f847c"
_CONTRACT = "programbench-1.2.4-axrun-tty-clock-v1"
_COMPILE_RESULT = "/outputs/programbench-compile.json"
_BRANCH_RESULT = "/outputs/programbench-branch.json"
_STASH = "/opt/axrun-programbench/candidate-executable"
_COMPILE_BUSINESS_EXIT_CODES = {
    21: "seed_git_failed",
    22: "compile_script_missing",
    23: "compile_failed",
    24: "executable_missing",
    25: "executable_not_executable",
}


@dataclass(slots=True)
class _Step:
    state: str = "pending"
    execution: ExecutionRef | None = None
    result_path: str = ""
    result_digest: str = ""
    reason_code: str = ""


@dataclass(slots=True)
class _ExecutionRecord:
    schema_version: int
    execution_id: str
    episode_id: str
    candidate_digest: str
    verifier_contract_digest: str
    state: str = "new"
    compile: _Step = field(default_factory=_Step)
    derived_environment_id: str = ""
    executable_digest: str = ""
    branches: dict[str, _Step] = field(default_factory=dict[str, _Step])
    aggregation_state: str = "pending"
    details_path: str = ""
    details_digest: str = ""
    cleanup_state: str = "not_started"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class _ExecutionStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, execution_id: str) -> Path:
        return self.root / "verifications" / execution_id / "execution.json"

    def initialize(
        self,
        *,
        execution_id: str,
        episode_id: str,
        candidate_digest: str,
        contract_digest: str,
        branches: tuple[str, ...],
    ) -> _ExecutionRecord:
        with self.lock(execution_id):
            existing = self.load(execution_id)
            if existing is not None:
                if (
                    existing.episode_id,
                    existing.candidate_digest,
                    existing.verifier_contract_digest,
                    tuple(existing.branches),
                ) != (episode_id, candidate_digest, contract_digest, branches):
                    raise RecoveryRequiredError(
                        "ProgramBench execution identity conflicts with state"
                    )
                return existing
            record = _ExecutionRecord(
                schema_version=1,
                execution_id=execution_id,
                episode_id=episode_id,
                candidate_digest=candidate_digest,
                verifier_contract_digest=contract_digest,
                branches={branch: _Step() for branch in branches},
            )
            self.save(record)
            return record

    def load(self, execution_id: str) -> _ExecutionRecord | None:
        path = self.path(execution_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ContractError("unsupported ProgramBench execution record")
        compile_step = _step(raw["compile"])
        branches = {name: _step(value) for name, value in raw["branches"].items()}
        return _ExecutionRecord(
            schema_version=1,
            execution_id=str(raw["execution_id"]),
            episode_id=str(raw["episode_id"]),
            candidate_digest=str(raw["candidate_digest"]),
            verifier_contract_digest=str(raw["verifier_contract_digest"]),
            state=str(raw["state"]),
            compile=compile_step,
            derived_environment_id=str(raw["derived_environment_id"]),
            executable_digest=str(raw["executable_digest"]),
            branches=branches,
            aggregation_state=str(raw["aggregation_state"]),
            details_path=str(raw["details_path"]),
            details_digest=str(raw["details_digest"]),
            cleanup_state=str(raw["cleanup_state"]),
        )

    def save(self, record: _ExecutionRecord) -> None:
        _atomic_write(self.path(record.execution_id), canonical_json(record.as_dict()) + b"\n")

    def publish_details(self, value: dict[str, Any]) -> tuple[Path, str]:
        digest = canonical_digest(value)
        path = self.root / "verification-details" / "sha256" / digest / "programbench.json"
        _atomic_write(path, json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")
        return path, digest

    def claim_compile(self, execution_id: str) -> _ExecutionRecord:
        with self.lock(execution_id):
            record = self.load(execution_id)
            if record is None:
                raise RecoveryRequiredError("ProgramBench execution record disappeared")
            if record.compile.state == "running" and record.compile.execution is None:
                raise RecoveryRequiredError(
                    "ProgramBench compile Run submission is ambiguous; no Run ID was persisted"
                )
            if record.compile.state not in {"completed", "business_failed"}:
                record.state = "compile_running"
                record.compile.state = "running"
                self.save(record)
            return record

    def claim_branch(self, execution_id: str, branch: str) -> _ExecutionRecord:
        with self.lock(execution_id):
            record = self.load(execution_id)
            if record is None or branch not in record.branches:
                raise RecoveryRequiredError("ProgramBench branch execution record disappeared")
            step = record.branches[branch]
            if step.state == "running" and step.execution is None:
                raise RecoveryRequiredError(
                    f"ProgramBench branch Run submission is ambiguous: {branch}"
                )
            if step.state != "completed":
                step.state = "running"
                self.save(record)
            return record

    @contextmanager
    def lock(self, execution_id: str) -> Generator[None, None, None]:
        import fcntl

        path = self.root / "locks" / f"{execution_id}.verification.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True, slots=True)
class ProgramBenchOfficialVerifierAdapter:
    timeout_seconds: int = 7200
    version: str = "1"
    name: str = "programbench-official-single"
    multi_run: bool = True

    def qualification_requirements(
        self, episode: ResolvedEpisode
    ) -> VerifierQualificationRequirements:
        self._validate_episode(episode)
        value = episode.verifier.config.get("compile_file")
        if not isinstance(value, str):
            raise ContractError("ProgramBench compile verifier path is invalid")
        return VerifierQualificationRequirements(verifier_file=value)

    def plan(self, episode: ResolvedEpisode, candidate: CandidateBundle) -> StagePlan:
        raise ContractError("ProgramBench official verification is a bounded multi-Run adapter")

    def parse_result(self, result: Any) -> VerificationResult:
        raise ContractError("ProgramBench official results are aggregated caller-side")

    def verify(
        self,
        episode: ResolvedEpisode,
        candidate: CandidateBundle,
        *,
        backend: ExecutionBackend,
        state_root: Path,
        on_primary_bound: Any,
    ) -> tuple[VerificationResult, ExecutionRef]:
        self._validate_episode(episode)
        workspace = next((item for item in candidate.files if item.role == "workspace"), None)
        if workspace is None:
            raise ContractError("CandidateBundle does not contain workspace role")
        tests = _load_tests(Path(cast(str, episode.verifier.config["tests_metadata_file"])))
        branches = tuple(sorted(tests))
        contract_digest = self._contract_digest(episode, branches)
        execution_id = f"{episode.episode_id}-programbench"
        store = _ExecutionStore(state_root)
        record = store.initialize(
            execution_id=execution_id,
            episode_id=episode.episode_id,
            candidate_digest=candidate.digest,
            contract_digest=contract_digest,
            branches=branches,
        )
        coordinator = MultiRunVerificationCoordinator(backend)
        started_at = datetime.now(UTC).isoformat()

        if record.compile.state != "completed":
            record = store.claim_compile(execution_id)

            def bind_compile(execution: ExecutionRef) -> None:
                record.compile.execution = execution
                store.save(record)
                on_primary_bound(execution)

            compile_result, environment_id = coordinator.run_with_rootfs(
                self._compile_plan(episode, candidate, workspace),
                artifact_dir=(
                    state_root / "artifacts" / episode.episode_id / "verification" / "compile"
                ),
                existing=record.compile.execution,
                on_bound=bind_compile,
            )
            if compile_result.exit_code in _COMPILE_BUSINESS_EXIT_CODES:
                record.compile.state = "business_failed"
                record.compile.reason_code = _COMPILE_BUSINESS_EXIT_CODES[compile_result.exit_code]
                record.state = "aggregating"
                store.save(record)
                return self._finish_compile_failure(
                    candidate,
                    record,
                    store,
                    tests,
                    started_at,
                    compile_result.execution,
                )
            if compile_result.exit_code != 0:
                raise InfrastructureError(
                    f"ProgramBench compile Run failed: {compile_result.diagnostic_code}"
                )
            compile_value, compile_artifact = _load_artifact_json(compile_result, _COMPILE_RESULT)
            if (
                set(compile_value)
                != {
                    "status",
                    "diagnostic_code",
                    "executable_sha256",
                    "executable_mode",
                }
                or compile_value["status"] != "succeeded"
            ):
                raise ContractError("ProgramBench compile result has an invalid shape")
            executable_digest = str(compile_value["executable_sha256"])
            _require_digest(executable_digest, "ProgramBench executable")
            if not environment_id:
                raise InfrastructureError("successful compile has no derived Environment")
            record.compile.execution = compile_result.execution
            record.compile.state = "completed"
            record.compile.result_path = compile_artifact.path
            record.compile.result_digest = compile_artifact.sha256
            record.derived_environment_id = environment_id
            record.executable_digest = executable_digest
            record.state = "branches_running"
            store.save(record)

        if not record.derived_environment_id or not record.executable_digest:
            raise RecoveryRequiredError("completed compile record is incomplete")
        for branch in branches:
            step = record.branches[branch]
            if step.state == "completed":
                continue
            record = store.claim_branch(execution_id, branch)
            step = record.branches[branch]
            asset = self._branch_asset(episode, branch)
            plan = self._branch_plan(episode, branch, asset, record)

            def bind_branch(
                execution: ExecutionRef,
                *,
                current: _Step = step,
                current_record: _ExecutionRecord = record,
            ) -> None:
                current.execution = execution
                store.save(current_record)

            result = coordinator.run(
                plan,
                artifact_dir=(
                    state_root
                    / "artifacts"
                    / episode.episode_id
                    / "verification"
                    / "branches"
                    / branch
                ),
                existing=step.execution,
                on_bound=bind_branch,
            )
            if result.exit_code != 0:
                raise InfrastructureError(
                    f"ProgramBench branch Run failed: {result.diagnostic_code}"
                )
            value, artifact = _load_artifact_json(result, _BRANCH_RESULT)
            _validate_branch_result(value, branch)
            step.execution = result.execution
            step.state = "completed"
            step.result_path = artifact.path
            step.result_digest = artifact.sha256
            step.reason_code = str(value["reason_code"])
            store.save(record)

        record.state = "aggregating"
        record.aggregation_state = "running"
        store.save(record)
        details = _aggregate(record, tests)
        path, digest = store.publish_details(details)
        record.details_path = str(path)
        record.details_digest = digest
        record.aggregation_state = "completed"
        record.cleanup_state = "running"
        store.save(record)
        coordinator.delete_environment(record.derived_environment_id)
        record.cleanup_state = "completed"
        record.state = "completed"
        store.save(record)
        primary = record.compile.execution
        if primary is None:
            raise RecoveryRequiredError("ProgramBench compile execution identity is missing")
        completed_at = datetime.now(UTC).isoformat()
        return (
            VerificationResult(
                schema_version=1,
                candidate_digest=candidate.digest,
                verifier=self.name,
                verifier_version=self.version,
                verdict="passed" if details["resolved"] else "failed",
                diagnostic_code="" if details["resolved"] else "PROGRAMBENCH_TESTS_FAILED",
                verifier_exit_code=0,
                output_digest=digest,
                started_at=started_at,
                completed_at=completed_at,
                score=float(details["score"]),
                details={
                    "details_digest": digest,
                    "active_branch_count": details["active_branch_count"],
                    "active_test_count": details["active_test_count"],
                    "passed": details["passed"],
                    "failed": details["failed"],
                    "not_run": details["not_run"],
                    "branch_error_count": len(cast(dict[str, object], details["branch_errors"])),
                    "executable_sha256": record.executable_digest,
                    "derived_environment_id": record.derived_environment_id,
                },
            ),
            primary,
        )

    def _finish_compile_failure(
        self,
        candidate: CandidateBundle,
        record: _ExecutionRecord,
        store: _ExecutionStore,
        tests: dict[str, dict[str, Any]],
        started_at: str,
        primary: ExecutionRef,
    ) -> tuple[VerificationResult, ExecutionRef]:
        active_count = sum(len(value["active_tests"]) for value in tests.values())
        details: dict[str, Any] = {
            "schema_version": 1,
            "instance_id": _INSTANCE,
            "candidate_digest": candidate.digest,
            "evaluator_contract": _CONTRACT,
            "executable_sha256": "",
            "compile_error": record.compile.reason_code,
            "active_branch_count": len(tests),
            "active_test_count": active_count,
            "passed": 0,
            "failed": 0,
            "not_run": active_count,
            "ignored_branch_count": 0,
            "ignored_test_count": sum(len(value["ignored_tests"]) for value in tests.values()),
            "branch_errors": {},
            "score": 0.0,
            "resolved": False,
            "tests": [
                {"branch": branch, "name": name, "status": "not_run"}
                for branch, value in tests.items()
                for name in value["active_tests"]
            ],
        }
        path, digest = store.publish_details(details)
        record.details_path = str(path)
        record.details_digest = digest
        record.aggregation_state = "completed"
        record.cleanup_state = "not_created"
        record.state = "completed"
        store.save(record)
        completed_at = datetime.now(UTC).isoformat()
        return (
            VerificationResult(
                schema_version=1,
                candidate_digest=candidate.digest,
                verifier=self.name,
                verifier_version=self.version,
                verdict="failed",
                diagnostic_code="PROGRAMBENCH_COMPILE_FAILED",
                verifier_exit_code=0,
                output_digest=digest,
                started_at=started_at,
                completed_at=completed_at,
                score=0.0,
                details={
                    "details_digest": digest,
                    "active_branch_count": len(tests),
                    "active_test_count": active_count,
                    "passed": 0,
                    "failed": 0,
                    "not_run": active_count,
                    "compile_error": record.compile.reason_code,
                },
            ),
            primary,
        )

    def _compile_plan(
        self, episode: ResolvedEpisode, candidate: CandidateBundle, workspace: Any
    ) -> StagePlan:
        package_root = Path(__file__).parents[1]
        runtime_init = package_root / "fixtures" / "claude" / "runtime_package_init.py"
        compile_file = Path(cast(str, episode.verifier.config["compile_file"]))
        remove_hashes = cast(list[str], episode.verifier.config["remove_hashes"])
        argv = [
            "python3",
            "/opt/axrun-programbench/compile_candidate.py",
            "--candidate",
            "/inputs/workspace.tar",
            "--workspace",
            "/workspace",
            "--stash",
            _STASH,
            "--result",
            _COMPILE_RESULT,
        ]
        for digest in remove_hashes:
            argv.extend(("--remove-sha256", digest))
        return StagePlan(
            environment_id=episode.verification_environment.environment_id,
            argv=tuple(argv),
            cwd="/workspace",
            inputs=(
                InputFile(
                    str(Path(candidate.root) / workspace.bundle_path),
                    "/inputs/workspace.tar",
                    workspace.sha256,
                ),
                InputFile(str(runtime_init), "/opt/axrun/axrun/__init__.py"),
                InputFile(str(runtime_init), "/opt/axrun/axrun/candidates/__init__.py"),
                InputFile(str(package_root / "errors.py"), "/opt/axrun/axrun/errors.py"),
                InputFile(
                    str(package_root / "candidates" / "archive.py"),
                    "/opt/axrun/axrun/candidates/archive.py",
                ),
                InputFile(
                    str(compile_file),
                    "/opt/axrun-programbench/compile_candidate.py",
                    cast(str, episode.verifier.config["compile_sha256"]),
                ),
            ),
            outputs=(OutputSpec(_COMPILE_RESULT, media_type="application/json"),),
            resources=episode.verification_resources,
            network_policy="deny_all",
            timeout_seconds=self.timeout_seconds,
            labels={"axrun.stage": "verification-compile", "axrun.verifier": self.name},
        )

    def _branch_plan(
        self,
        episode: ResolvedEpisode,
        branch: str,
        asset: Path,
        record: _ExecutionRecord,
    ) -> StagePlan:
        branch_file = Path(cast(str, episode.verifier.config["branch_file"]))
        return StagePlan(
            environment_id=record.derived_environment_id,
            argv=(
                "python3",
                "/opt/axrun-programbench/run_branch.py",
                "--branch",
                branch,
                "--asset",
                f"/inputs/{branch}.tar.gz",
                "--workspace",
                "/workspace",
                "--stash",
                _STASH,
                "--executable-sha256",
                record.executable_digest,
                "--result",
                _BRANCH_RESULT,
            ),
            cwd="/workspace",
            inputs=(
                InputFile(str(asset), f"/inputs/{branch}.tar.gz", _sha256(asset)),
                InputFile(
                    str(branch_file),
                    "/opt/axrun-programbench/run_branch.py",
                    cast(str, episode.verifier.config["branch_sha256"]),
                ),
            ),
            outputs=(OutputSpec(_BRANCH_RESULT, media_type="application/json"),),
            resources=episode.verification_resources,
            network_policy="deny_all",
            timeout_seconds=self.timeout_seconds,
            labels={
                "axrun.stage": "verification-branch",
                "axrun.verifier": self.name,
                "axrun.programbench.branch": branch,
            },
        )

    def _branch_asset(self, episode: ResolvedEpisode, branch: str) -> Path:
        lock = json.loads(
            Path(cast(str, episode.verifier.config["asset_lock_file"])).read_text(encoding="utf-8")
        )
        value = lock["test_blobs"]["branches"][branch]
        root = Path(cast(str, episode.verifier.config["test_assets_dir"])).resolve()
        path = (root / str(value["path"])).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            raise InfrastructureError(f"ProgramBench branch asset is missing: {branch}")
        if path.stat().st_size != int(value["size_bytes"]) or _sha256(path) != str(value["sha256"]):
            raise InfrastructureError(f"ProgramBench branch asset integrity failed: {branch}")
        return path

    def _contract_digest(self, episode: ResolvedEpisode, branches: tuple[str, ...]) -> str:
        return canonical_digest(
            {
                "identity": self.name,
                "version": self.version,
                "contract": _CONTRACT,
                "task": episode.task.config,
                "branches": branches,
                "compile_sha256": episode.verifier.config["compile_sha256"],
                "branch_sha256": episode.verifier.config["branch_sha256"],
                "remove_hashes": episode.verifier.config["remove_hashes"],
            }
        )

    def _validate_episode(self, episode: ResolvedEpisode) -> None:
        if (episode.verifier.identity, episode.verifier.version) != (self.name, self.version):
            raise ContractError(
                "ProgramBench official verifier requires programbench-official-single@1"
            )
        if (
            episode.task_id != _INSTANCE
            or episode.verifier.config.get("evaluator_contract") != _CONTRACT
        ):
            raise ContractError("ProgramBench official verifier contract changed")
        if (episode.candidate.identity, episode.candidate.version) != ("workspace-archive", "1"):
            raise ContractError("ProgramBench official verifier requires workspace-archive@1")
        if episode.candidate.config.get("exclude_paths") != ["executable"]:
            raise ContractError("ProgramBench official candidate must exclude executable")
        required = {
            "asset_lock_file",
            "tests_metadata_file",
            "required_public_capability",
            "test_assets_dir",
            "evaluator_contract",
            "compile_file",
            "compile_sha256",
            "branch_file",
            "branch_sha256",
            "remove_hashes",
        }
        if set(episode.verifier.config) != required:
            raise ContractError("ProgramBench official verifier configuration changed")
        remove_hashes = episode.verifier.config["remove_hashes"]
        if remove_hashes != ["cd400708bcd6a5b9dd28bd450a211ec4625cde31470057e9d62f66072e297db0"]:
            raise ContractError("ProgramBench official submission-clean hash set changed")


def _step(raw: dict[str, Any]) -> _Step:
    execution = raw.get("execution")
    return _Step(
        state=str(raw["state"]),
        execution=ExecutionRef(**execution) if execution is not None else None,
        result_path=str(raw["result_path"]),
        result_digest=str(raw["result_digest"]),
        reason_code=str(raw["reason_code"]),
    )


def _load_tests(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    branches: dict[str, dict[str, Any]] = {}
    for name, value in cast(dict[str, dict[str, Any]], raw["branches"]).items():
        if value["ignored"]:
            continue
        ignored = {str(item["name"]) for item in value["ignored_tests"]}
        tests = [str(item) for item in value["tests"]]
        branches[name] = {
            "active_tests": [item for item in tests if item not in ignored],
            "ignored_tests": sorted(ignored),
        }
    if len(branches) != 6 or sum(len(item["active_tests"]) for item in branches.values()) != 281:
        raise ContractError("ProgramBench expected-test denominator changed")
    return branches


def _load_artifact_json(result: Any, name: str) -> tuple[dict[str, Any], Artifact]:
    artifact = result.artifact_for_path(name)
    if _sha256(Path(artifact.path)) != artifact.sha256:
        raise InfrastructureError("ProgramBench sealed artifact digest mismatch")
    raw = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractError("ProgramBench output must be a JSON object")
    return cast(dict[str, Any], raw), artifact


def _validate_branch_result(value: dict[str, Any], branch: str) -> None:
    if set(value) != {"schema_version", "branch", "status", "reason_code", "tests"}:
        raise ContractError("ProgramBench branch result has an invalid shape")
    if value["schema_version"] != 1 or value["branch"] != branch:
        raise ContractError("ProgramBench branch result identity mismatch")
    if value["status"] not in {"completed", "branch_error"}:
        raise ContractError("ProgramBench branch result status is invalid")
    if not isinstance(value["reason_code"], str) or not isinstance(value["tests"], list):
        raise ContractError("ProgramBench branch result fields are invalid")
    for item in cast(list[object], value["tests"]):
        if not isinstance(item, dict):
            raise ContractError("ProgramBench test result has an invalid shape")
        test = cast(dict[str, object], item)
        if set(test) != {"name", "status"}:
            raise ContractError("ProgramBench test result has an invalid shape")
        if not isinstance(test["name"], str) or test["status"] not in {
            "passed",
            "skipped",
            "failure",
            "error",
            "system_error",
        }:
            raise ContractError("ProgramBench test result is invalid")


def _aggregate(record: _ExecutionRecord, tests: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result_map: dict[str, dict[str, str]] = {}
    branch_errors: dict[str, list[dict[str, str]]] = {}
    for branch, expected in tests.items():
        step = record.branches[branch]
        if step.state != "completed" or not step.result_path:
            raise RecoveryRequiredError("ProgramBench branch result is incomplete")
        path = Path(step.result_path)
        if _sha256(path) != step.result_digest:
            raise InfrastructureError("persisted ProgramBench branch result digest mismatch")
        value = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        _validate_branch_result(value, branch)
        active = set(cast(list[str], expected["active_tests"]))
        ignored = set(cast(list[str], expected["ignored_tests"]))
        if value["status"] == "branch_error":
            reason = str(value["reason_code"])
            branch_errors[branch] = [{"error_code": reason}]
            for name in expected["active_tests"]:
                result_map[f"{branch}/{name}"] = {
                    "branch": branch,
                    "name": name,
                    "status": "not_run",
                }
            continue
        observed = cast(list[dict[str, str]], value["tests"])
        got: set[str] = set()
        for item in observed:
            if item["name"] in ignored:
                continue
            got.add(item["name"])
            # ProgramBench's published scorer materializes a mapping keyed by full test name.
            # Pytest may emit a duplicate testcase after an xdist worker restart; last result wins.
            result_map[f"{branch}/{item['name']}"] = {
                "branch": branch,
                "name": item["name"],
                "status": item["status"],
            }
        for name in expected["active_tests"]:
            if name not in got:
                result_map[f"{branch}/{name}"] = {
                    "branch": branch,
                    "name": name,
                    "status": "not_run",
                }
        if not got <= active | ignored:
            # Official ProgramBench keeps unexpected observed tests in the denominator. They are
            # intentionally retained above; this guard exists only to make the behavior explicit.
            pass
    results = [result_map[key] for key in sorted(result_map)]
    passed = sum(item["status"] == "passed" for item in results)
    not_run = sum(item["status"] == "not_run" for item in results)
    failed = len(results) - passed - not_run
    score = passed / len(results) if results else 0.0
    return {
        "schema_version": 1,
        "instance_id": _INSTANCE,
        "candidate_digest": record.candidate_digest,
        "evaluator_contract": _CONTRACT,
        "executable_sha256": record.executable_digest,
        "compile_error": "",
        "active_branch_count": len(tests),
        "active_test_count": sum(len(value["active_tests"]) for value in tests.values()),
        "passed": passed,
        "failed": failed,
        "not_run": not_run,
        "ignored_branch_count": 0,
        "ignored_test_count": sum(len(value["ignored_tests"]) for value in tests.values()),
        "branch_errors": branch_errors,
        "score": score,
        "resolved": score == 1.0,
        "tests": results,
    }


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ContractError(f"{label} digest is invalid")


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
