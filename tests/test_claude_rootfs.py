from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).parents[1] / "docker" / "claude-code-rootfs"
BASE_IMAGE = "ubuntu:24.04@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea"


def _resolve(architecture: str, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "resolve-architecture.py"),
            str(ROOT / "artifacts.lock.json"),
            architecture,
            str(output),
            "--ubuntu-base-image",
            BASE_IMAGE,
            "--claude-code-version",
            "2.1.205",
            "--claude-runtime-version",
            "2.1.205-20260812-234142",
            "--node-version",
            "22.23.2",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_claude_205_artifact_lock_is_fixed_dual_arch_and_registry_neutral(
    tmp_path: Path,
) -> None:
    raw: object = json.loads((ROOT / "artifacts.lock.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    lock = cast(dict[str, Any], raw)
    assert lock["schema_version"] == 1
    assert lock["ubuntu_base_image"] == BASE_IMAGE
    assert lock["claude_code"] == {
        "version": "2.1.205",
        "runtime_version": "2.1.205-20260812-234142",
        "package_sha256": "287e5ef2ec39e653cd78c356fb80a5c206241879bc17cefa42df5605b806db91",
    }
    assert lock["node"] == {"version": "22.23.2"}
    platforms = cast(dict[str, dict[str, str]], lock["platforms"])
    assert set(platforms) == {"amd64", "arm64"}
    assert platforms["amd64"]["node_sha256"] == (
        "d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307"
    )
    assert platforms["arm64"]["node_sha256"] == (
        "fff4078c5def658577f92c88db7db3bc0072924bfb93fe52c1e744a54e94abb8"
    )
    assert platforms["amd64"]["claude_native_sha256"] == (
        "d3dadfa9cde294ac82c755eb6d889291228849180bac5d677ad1a4027aca1bc4"
    )
    assert platforms["arm64"]["claude_native_sha256"] == (
        "b9bee2e92869637ccf2d154ae09baaba561b7354b32f15ab8549a9b731b53847"
    )
    for architecture in ("amd64", "arm64"):
        output = tmp_path / f"{architecture}.env"
        result = _resolve(architecture, output)
        assert result.returncode == 0, result.stderr
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
        assert values["TARGETARCH"] == architecture
        assert values["CLAUDE_CODE_VERSION"] == "2.1.205"
        assert values["NODE_VERSION"] == "22.23.2"
        assert values["SOURCE_INTERP"].startswith("/lib")
    rejected = _resolve("ppc64le", tmp_path / "unknown.env")
    assert rejected.returncode != 0
    assert "unsupported TARGETARCH" in rejected.stderr


def test_claude_rootfs_dockerfile_keeps_visible_abi_and_uses_copied_scripts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    required = {
        f"ARG UBUNTU_BASE_IMAGE={BASE_IMAGE}",
        "ARG CLAUDE_CODE_VERSION=2.1.205",
        "ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142",
        "ARG NODE_VERSION=22.23.2",
        "ARG NODE_DIST_BASE_URL=https://nodejs.org/dist",
        "ARG NPM_REGISTRY_URL=https://registry.npmjs.org",
        "COPY artifacts.lock.json /opt/axrun-build/artifacts.lock.json",
        "COPY scripts/resolve-architecture.py /opt/axrun-build/scripts/resolve-architecture.py",
        "COPY scripts/claude-launcher.sh /usr/local/bin/claude",
        'io.axrun.claude-code.mount-target="/__claude_code"',
        'io.axrun.claude-code.entry="/__claude_code/usr/local/bin/claude"',
    }
    assert all(value in dockerfile for value in required)
    assert "ADD " not in dockerfile
    assert "RUN cat >" not in dockerfile
    assert "ENV LD_LIBRARY_PATH" not in dockerfile
    launcher = (ROOT / "scripts" / "claude-launcher.sh").read_text(encoding="utf-8")
    assert "unset LD_LIBRARY_PATH" in launcher
    assert "root=/__claude_code" in launcher
    patcher = (ROOT / "scripts" / "patch-bun-interp.py").read_text(encoding="utf-8")
    assert 'new = b"/__claude_code/l\\0"' in patcher
    manifest = (ROOT / "scripts" / "write-manifest.sh").read_text(encoding="utf-8")
    assert "canonical_mount_target /__claude_code" in manifest
    assert "canonical_entry /__claude_code/usr/local/bin/claude" in manifest
    audited_paths = [ROOT / "Dockerfile", ROOT / "artifacts.lock.json"]
    audited_paths.extend(path for path in (ROOT / "scripts").rglob("*") if path.is_file())
    source = "\n".join(path.read_text(encoding="utf-8") for path in audited_paths)
    forbidden = ("cr.aliyuncs.com", "AKIA", "token=", "password=", "_authToken")
    assert all(value not in source for value in forbidden)
