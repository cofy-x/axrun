"""Qualification contracts for the current workspace task families."""

from __future__ import annotations

from dataclasses import dataclass

from axrun.adapters.base import TaskQualificationRequirements
from axrun.errors import ContractError
from axrun.models import ResolvedEpisode, task_config_string


@dataclass(frozen=True, slots=True)
class GitWorktreeTaskAdapter:
    """A task whose immutable image owns a clean Git worktree."""

    name: str
    version: str = "1"

    def qualification_requirements(
        self, episode: ResolvedEpisode, role: str
    ) -> TaskQualificationRequirements:
        self._validate(episode)
        _validate_role(role)
        return TaskQualificationRequirements(
            mode="git", base_commit=task_config_string(episode, "base_commit")
        )

    def _validate(self, episode: ResolvedEpisode) -> None:
        if (episode.task.identity, episode.task.version) != (self.name, self.version):
            raise ContractError(f"task adapter requires {self.name}@{self.version}")


@dataclass(frozen=True, slots=True)
class EmptyWorkspaceTaskAdapter:
    """A task whose immutable inference workspace must initially be empty."""

    name: str
    version: str = "1"

    def qualification_requirements(
        self, episode: ResolvedEpisode, role: str
    ) -> TaskQualificationRequirements:
        if (episode.task.identity, episode.task.version) != (self.name, self.version):
            raise ContractError(f"task adapter requires {self.name}@{self.version}")
        _validate_role(role)
        return TaskQualificationRequirements(mode="empty")


def _validate_role(role: str) -> None:
    if role not in {"inference", "verification"}:
        raise ContractError("task qualification role is invalid")
