"""Task contract for the deliberately closed ProgramBench compatibility fixture."""

from __future__ import annotations

from dataclasses import dataclass

from axrun.adapters.base import TaskQualificationRequirements, WorkspaceFileRequirement
from axrun.errors import ContractError
from axrun.models import ResolvedEpisode

_INSTANCE = "testorg__calculator.abc1234"
_TASK_CONFIG = {
    "instance_id": _INSTANCE,
    "repository": "testorg/calculator",
    "commit": "abc1234567890abcdef1234567890abcdef123456",
}


@dataclass(frozen=True, slots=True)
class ProgramBenchTaskAdapter:
    version: str = "1"
    name: str = "programbench"

    def qualification_requirements(
        self, episode: ResolvedEpisode, role: str
    ) -> TaskQualificationRequirements:
        if (episode.task.identity, episode.task.version) != (self.name, self.version):
            raise ContractError("ProgramBench task adapter requires programbench@1")
        if episode.task_id != _INSTANCE or episode.task.config != _TASK_CONFIG:
            raise ContractError("ProgramBench task adapter supports only the calculator fixture")
        if role == "inference":
            return TaskQualificationRequirements(
                mode="prepared",
                workspace_files=(WorkspaceFileRequirement("executable", 0o111),),
            )
        if role == "verification":
            return TaskQualificationRequirements(mode="empty")
        raise ContractError("task qualification role is invalid")
