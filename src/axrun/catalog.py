"""Curated, fail-closed adapter catalog.

The catalog is code, not a plugin mechanism.  Every supported identity and exact version is
reviewable here; no entry point, import string, or runtime download participates in resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from axrun.adapters import (
    CommandVerifierAdapter,
    GreenfieldVerifierAdapter,
    StaticCandidateHarness,
    SweBenchVerifiedVerifierAdapter,
    SyntheticVerifierAdapter,
)
from axrun.adapters.base import (
    CandidateAdapter,
    InferenceAdapter,
    TaskAdapter,
    TrajectoryAdapter,
    VerifierAdapter,
)
from axrun.candidates import GitPatchCandidateAdapter, WorkspaceArchiveCandidateAdapter
from axrun.errors import ContractError
from axrun.harnesses import ClaudeCodeHarness
from axrun.models import HarnessRuntimeRequirements, ResolvedEpisode
from axrun.proxy.base import ModelProtocol
from axrun.proxy.protocols import AnthropicProtocol
from axrun.tasks import EmptyWorkspaceTaskAdapter, GitWorktreeTaskAdapter
from axrun.trajectories.adapters import ClaudeCodeTrajectoryAdapter


@dataclass(frozen=True, slots=True)
class AdapterSelection:
    task: TaskAdapter
    inference: InferenceAdapter
    candidate: CandidateAdapter
    verifier: VerifierAdapter
    trajectory: TrajectoryAdapter | None
    runtime: HarnessRuntimeRequirements


@dataclass(frozen=True, slots=True)
class QualificationRequirements:
    task_mode: str
    base_commit: str = ""
    archive_finalizer: bool = False
    verifier_file: str = ""
    claude_mount_image: str = ""

    def __post_init__(self) -> None:
        if self.task_mode not in {"git", "empty"}:
            raise ContractError("unsupported task qualification mode")
        if (self.task_mode == "git") != bool(self.base_commit):
            raise ContractError("Git qualification requires exactly one base commit")


def resolve_adapters(episode: ResolvedEpisode) -> AdapterSelection:
    task = resolve_task(episode)
    inference, runtime = resolve_harness(episode)
    candidate = resolve_candidate(episode)
    verifier = resolve_verifier(episode)
    trajectory = resolve_trajectory(runtime, episode.harness.version)
    return AdapterSelection(task, inference, candidate, verifier, trajectory, runtime)


def resolve_qualification_requirements(episode: ResolvedEpisode) -> QualificationRequirements:
    selection = resolve_adapters(episode)
    task = selection.task.qualification_requirements(episode)
    harness = selection.inference.qualification_requirements(episode)
    candidate = selection.candidate.qualification_requirements(episode)
    verifier = selection.verifier.qualification_requirements(episode)
    return QualificationRequirements(
        task_mode=task.mode,
        base_commit=task.base_commit,
        archive_finalizer=candidate.archive_finalizer,
        verifier_file=verifier.verifier_file,
        claude_mount_image=harness.claude_mount_image,
    )


def resolve_task(episode: ResolvedEpisode) -> TaskAdapter:
    key = (episode.task.identity, episode.task.version)
    if key in {
        ("git-worktree", "1"),
        ("axrun.synthetic.code-task", "1"),
        ("swebench-verified", "1"),
    }:
        return GitWorktreeTaskAdapter(name=key[0])
    if key == ("axrun.synthetic.greenfield-task", "1"):
        return EmptyWorkspaceTaskAdapter(name=key[0])
    raise ContractError(f"unsupported task adapter: {key[0]}@{key[1]}")


def resolve_harness(
    episode: ResolvedEpisode,
) -> tuple[InferenceAdapter, HarnessRuntimeRequirements]:
    key = (episode.harness.identity, episode.harness.version)
    if key == ("static-candidate", "1"):
        adapter = StaticCandidateHarness()
        return adapter, adapter.runtime_requirements
    if key == ("claude-code", "2.1.205"):
        adapter = ClaudeCodeHarness()
        return adapter, adapter.runtime_requirements
    raise ContractError(f"unsupported harness adapter: {key[0]}@{key[1]}")


def resolve_candidate(episode: ResolvedEpisode) -> CandidateAdapter:
    key = (episode.candidate.identity, episode.candidate.version)
    if key == ("git-patch", "1"):
        return GitPatchCandidateAdapter()
    if key == ("workspace-archive", "1"):
        return WorkspaceArchiveCandidateAdapter()
    raise ContractError(f"unsupported candidate adapter: {key[0]}@{key[1]}")


def resolve_verifier(episode: ResolvedEpisode) -> VerifierAdapter:
    key = (episode.verifier.identity, episode.verifier.version)
    if key == ("synthetic-code-task", "1"):
        return SyntheticVerifierAdapter(timeout_seconds=episode.verifier.timeout_seconds)
    if key == ("swebench-verified", "1"):
        return SweBenchVerifiedVerifierAdapter(timeout_seconds=episode.verifier.timeout_seconds)
    if key == ("synthetic-greenfield", "1"):
        return GreenfieldVerifierAdapter(timeout_seconds=episode.verifier.timeout_seconds)
    if key == ("command-verifier", "1"):
        value = episode.verifier.config.get("command", ["/opt/axrun/run-verifier"])
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item for item in cast(list[object], value))
        ):
            raise ContractError("verifier command must be a non-empty string array")
        return CommandVerifierAdapter(
            command=tuple(cast(list[str], value)),
            timeout_seconds=episode.verifier.timeout_seconds,
        )
    raise ContractError(f"unsupported verifier adapter: {key[0]}@{key[1]}")


def resolve_trajectory(
    requirements: HarnessRuntimeRequirements, harness_version: str
) -> TrajectoryAdapter | None:
    if not requirements.trajectory_adapter:
        return None
    if requirements.trajectory_adapter == "claude-code" and harness_version == "2.1.205":
        return ClaudeCodeTrajectoryAdapter()
    raise ContractError(
        f"unsupported trajectory adapter: {requirements.trajectory_adapter}@{harness_version}"
    )


def resolve_model_protocol(requirements: HarnessRuntimeRequirements) -> ModelProtocol | None:
    if not requirements.requires_model_tunnel:
        return None
    if requirements.model_protocol == "anthropic-compatible":
        return AnthropicProtocol()
    raise ContractError(f"unsupported model protocol: {requirements.model_protocol}")
