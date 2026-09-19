"""Task-semantic adapters selected by the curated catalog."""

from axrun.tasks.programbench import ProgramBenchTaskAdapter
from axrun.tasks.workspace import EmptyWorkspaceTaskAdapter, GitWorktreeTaskAdapter

__all__ = [
    "EmptyWorkspaceTaskAdapter",
    "GitWorktreeTaskAdapter",
    "ProgramBenchTaskAdapter",
]
