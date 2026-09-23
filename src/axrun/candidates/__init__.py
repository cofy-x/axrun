"""Candidate artifact adapters."""

from axrun.candidates.git_patch import GitPatchCandidateAdapter
from axrun.candidates.workspace_archive import WorkspaceArchiveCandidateAdapter

__all__ = ["GitPatchCandidateAdapter", "WorkspaceArchiveCandidateAdapter"]
