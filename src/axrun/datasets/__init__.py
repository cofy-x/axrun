"""Explicit dataset resolvers that produce canonical episodes."""

from axrun.datasets.base import DatasetAdapter
from axrun.datasets.greenfield import SyntheticGreenfieldResolver
from axrun.datasets.swebench_verified import SweBenchVerifiedResolver
from axrun.datasets.synthetic import SyntheticCodeTaskResolver

__all__ = [
    "DatasetAdapter",
    "SweBenchVerifiedResolver",
    "SyntheticCodeTaskResolver",
    "SyntheticGreenfieldResolver",
]
