"""Validate the canonical evaluator before accepting any candidate work."""

import hashlib
import importlib
import importlib.metadata
import re
import sys
from pathlib import Path


def check(expected_digest: str | None = None) -> None:
    lock = Path(__file__).with_name("requirements.lock")
    if (
        expected_digest is not None
        and hashlib.sha256(lock.read_bytes()).hexdigest() != expected_digest
    ):
        raise ValueError("evaluator dependency lock mismatch")
    pins = re.findall(r"^([\w-]+)==([^\s]+)", lock.read_text(), re.MULTILINE)
    if not pins:
        raise ValueError("empty evaluator dependency lock")
    for name, expected in pins:
        if importlib.metadata.version(name) != expected:
            raise ValueError("evaluator dependency version mismatch")
    for module in (
        "pytest",
        "pytest_timeout",
        "xdist",
        "pytest_dependency",
        "pytest_rerunfailures",
        "libtmux",
    ):
        importlib.import_module(module)


if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) == 2 else None)
