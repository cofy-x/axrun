from pathlib import Path


def test_synthetic_task_image_owns_workspace_git_seed() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "code-task-v1"
    dockerfile = (fixture / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim-bookworm@sha256:" in dockerfile
    assert "apt-get install -y --no-install-recommends git ca-certificates" in dockerfile
    assert "COPY repository/ /workspace/" in dockerfile
    assert "git init -q" in dockerfile
    assert "60dd887fd78561f03d8ca215e97de77048e93627" in dockerfile
    assert "WORKDIR /workspace" in dockerfile
    readme = (fixture / "README.md").read_text(encoding="utf-8")
    assert "linux/amd64" in readme
    assert "linux/arm64" in readme
