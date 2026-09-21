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
_OFFICIAL_INSTANCE = "xorg62__tty-clock.f2f847c"
_OFFICIAL_CONFIG = {
    "instance_id": _OFFICIAL_INSTANCE,
    "repository": "xorg62/tty-clock",
    "commit": "f2f847cf2cc2949c8a8b7779a778f366d3743474",
    "language": "c",
    "difficulty": "easy",
    "programbench_version": "1.2.4",
    "programbench_git_sha": "963063c9271cc40fa179977356782ea4582e0b0c",
    "official_image_digest": (
        "sha256:7c070e64a44e0b7dc2a032acf02159da43a0a4993a154b5fd98c4ab997726272"
    ),
    "test_blob_revision": "de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5",
    "active_branch_count": 6,
    "active_test_count": 281,
    "ignored_test_count": 38,
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


@dataclass(frozen=True, slots=True)
class ProgramBenchOfficialTaskAdapter:
    version: str = "1"
    name: str = "programbench-official-single"

    def qualification_requirements(
        self, episode: ResolvedEpisode, role: str
    ) -> TaskQualificationRequirements:
        if (episode.task.identity, episode.task.version) != (self.name, self.version):
            raise ContractError(
                "ProgramBench official task adapter requires programbench-official-single@1"
            )
        if episode.task_id != _OFFICIAL_INSTANCE or episode.task.config != _OFFICIAL_CONFIG:
            raise ContractError("ProgramBench official task contract changed")
        if role not in {"inference", "verification"}:
            raise ContractError("task qualification role is invalid")
        return TaskQualificationRequirements(
            mode="prepared",
            workspace_files=(WorkspaceFileRequirement("executable", 0o111),),
        )
