"""Explicit dataset resolvers that produce canonical episodes."""

from axrun.datasets.base import DatasetAdapter
from axrun.datasets.synthetic import SyntheticCodeTaskResolver

__all__ = ["DatasetAdapter", "SyntheticCodeTaskResolver"]
