from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).parents[1] / "docker" / "swebench-verified" / "django__django-12419"


def test_arm64_task_image_is_fixed_fail_closed_and_registry_neutral() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    lock = cast(
        dict[str, Any],
        json.loads((ROOT / "artifacts.lock.json").read_text(encoding="utf-8")),
    )
    assert lock["platform"] == "linux/arm64"
    assert lock["role"] == "local-development"
    assert lock["django"]["base_commit"] == ("7fa1a93c6c8109010a6ff3f604fda83b604e0e97")
    assert lock["official_amd64_image"].endswith(
        "@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768"
    )
    assert (
        lock["conda_explicit_lock_sha256"]
        == hashlib.sha256((ROOT / "environment-arm64.lock").read_bytes()).hexdigest()
    )
    required = {
        "FROM ${UBUNTU_ARM64_IMAGE}",
        'ARG APT_MIRROR="http://ports.ubuntu.com/ubuntu-ports"',
        'ARG MINICONDA_BASE_URL="https://repo.anaconda.com/miniconda"',
        'ARG CONDAFORGE_CHANNEL_URL="https://conda.anaconda.org/conda-forge"',
        'RUN test "${TARGETARCH}" = arm64',
        "WORKDIR /testbed",
        'io.axrun.platform-role="local-development"',
    }
    assert all(value in dockerfile for value in required)
    assert "ubuntu:22.04@sha256:" in dockerfile
    assert "        python3 \\" in dockerfile
    assert "MINICONDA_SHA256=" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "--only-binary=:all:" in dockerfile
    mirror_profile = (ROOT / "build-local-cn.sh").read_text(encoding="utf-8")
    assert "http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports" in mirror_profile
    assert "https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda" in mirror_profile
    assert "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge" in mirror_profile
    assert "https://ghproxy.net/https://github.com/django/django.git" in mirror_profile
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in ROOT.iterdir() if path.is_file()
    )
    forbidden = ("cr.aliyuncs.com", "AKIA", "token=", "password=", "_authToken")
    assert all(value not in source for value in forbidden)


def test_arm64_environment_does_not_reuse_x86_builds_or_embed_dataset_answers() -> None:
    environment = (ROOT / "environment-arm64.yml").read_text(encoding="utf-8")
    environment_lock = (ROOT / "environment-arm64.lock").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-case.txt").read_text(encoding="utf-8")
    assert "python=3.6.13" in environment
    assert "nodefaults" in environment
    assert "linux-64" not in environment
    assert environment_lock.startswith("# platform: linux-aarch64\n@EXPLICIT\n")
    assert environment_lock.count("#") == 28
    assert "linux-64" not in environment_lock
    assert "python-3.6.13-h30375ac_2_cpython.tar.bz2#628b6c13687384dd75b99615988c16da" in (
        environment_lock
    )
    assert requirements.count("--hash=sha256:") == 4
    assert "typing-extensions==4.1.1" in requirements
    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in ROOT.iterdir() if path.is_file()
    )
    assert "SECURE_REFERRER_POLICY = 'same-origin'" not in persisted
    assert "Referrer-Policy: same-origin" not in persisted
    qualification = (ROOT / "qualify-image.py").read_text(encoding="utf-8")
    assert '"--network",\n            "none"' in qualification
    assert 'empty["resolved"] is not False' in qualification
    assert 'gold["resolved"] is not True' in qualification
