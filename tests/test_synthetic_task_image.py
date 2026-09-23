import shutil
import subprocess
from pathlib import Path

from axrun.adapters._git import canonical_patch_export


def test_synthetic_task_image_owns_workspace_git_seed() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "code-task-v1"
    dockerfile = (fixture / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim-bookworm@sha256:" in dockerfile
    assert "apt-get install -y --no-install-recommends git ca-certificates" in dockerfile
    assert "COPY repository/ /workspace/" in dockerfile
    assert "git init -q" in dockerfile
    assert "69b31ae17c45d731fd5b6fa43660c05aea4a9027" in dockerfile
    assert "WORKDIR /workspace" in dockerfile
    ignore = (fixture / "repository" / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in ignore
    assert "*.py[cod]" in ignore
    readme = (fixture / "README.md").read_text(encoding="utf-8")
    assert "linux/amd64" in readme
    assert "linux/arm64" in readme


def test_synthetic_seed_ignore_policy_excludes_runtime_cache_not_new_source(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "code-task-v1"
    repository = tmp_path / "repository"
    shutil.copytree(fixture / "repository", repository)
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", "-A", "--", "."], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Axrun Test",
            "-c",
            "user.email=axrun@example.invalid",
            "commit",
            "-q",
            "-m",
            "base",
        ],
        cwd=repository,
        check=True,
    )
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repository / "calculator.py").write_text(
        "def add_one(value: int) -> int:\n    return value + 1\n", encoding="utf-8"
    )
    (repository / "new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "__pycache__").mkdir()
    (repository / "__pycache__" / "calculator.cpython-311.pyc").write_bytes(b"runtime")
    (repository / "tests" / "__pycache__").mkdir()
    (repository / "tests" / "__pycache__" / "test.cpython-311.pyc").write_bytes(b"runtime")
    patch = tmp_path / "candidate.patch"
    subprocess.run(
        ["/bin/sh", "-c", "set -eu\n" + canonical_patch_export(base_commit, str(patch))],
        cwd=repository,
        check=True,
    )

    content = patch.read_text(encoding="utf-8")
    assert "calculator.py" in content
    assert "new_module.py" in content
    assert "__pycache__" not in content
    assert ".pyc" not in content
