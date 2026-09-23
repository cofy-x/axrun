"""Task-semantic adapters selected by the curated catalog."""

from axrun.tasks.programbench import ProgramBenchOfficialTaskAdapter, ProgramBenchTaskAdapter
from axrun.tasks.workspace import EmptyWorkspaceTaskAdapter, GitWorktreeTaskAdapter

__all__ = [
    "EmptyWorkspaceTaskAdapter",
    "GitWorktreeTaskAdapter",
    "ProgramBenchOfficialTaskAdapter",
    "ProgramBenchTaskAdapter",
]
