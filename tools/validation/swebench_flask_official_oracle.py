"""Bounded, offline official-script oracle for one SWE-bench Verified Flask instance.

This is a stage-zero validation tool, not a registered Axrun adapter. Its default
``all`` action prepares pinned public assets on the Linux host and then evaluates
with Docker networking disabled. Docker evaluation never downloads data, images,
packages, or source; preparation is explicit in the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import resource
import stat
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, NamedTuple

INSTANCE_ID = "pallets__flask-5014"
DATASET_COMMIT = "78f471bf655a3137b2e8a75af1501690ec009ec3"
HARNESS_COMMIT = "f7bbbb2ccdf479001d6467c9e34af59e44a840f9"
ROW_SHA256 = "36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e"
PARQUET_SHA256 = "030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25"
PARQUET_BYTES = 6_304_616
PARQUET_URL = (
    "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified/resolve/"
    f"{DATASET_COMMIT}/data/test-00000-of-00001.parquet"
)
SETUPTOOLS_WHEEL_NAME = "setuptools-70.0.0-py3-none-any.whl"
SETUPTOOLS_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/de/88/"
    "70c5767a0e43eb4451c2200f07d042a4bcd7639276003a9c54a68cfcc1f8/" + SETUPTOOLS_WHEEL_NAME
)
SETUPTOOLS_WHEEL_BYTES = 863_432
SETUPTOOLS_WHEEL_SHA256 = "54faa7f2e8d2d11bcd2c07bed282eef1046b5c080d1c32add737d7b5817b1ad4"
WHEEL_DIST_NAME = "wheel-0.45.1-py3-none-any.whl"
WHEEL_DIST_URL = (
    "https://files.pythonhosted.org/packages/0b/2c/"
    "87f3254fd8ffd29e4c02732eee68a83a1d3c346ae39bc6822dcbcb697f2b/" + WHEEL_DIST_NAME
)
WHEEL_DIST_BYTES = 72_494
WHEEL_DIST_SHA256 = "708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248"
WHEELHOUSE_MOUNT = "/opt/axrun-wheelhouse"
OFFLINE_PIP_ENV = ("PIP_NO_INDEX=1", f"PIP_FIND_LINKS={WHEELHOUSE_MOUNT}")
HARNESS_URL = "https://github.com/SWE-bench/SWE-bench.git"
IMAGE = (
    "docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014"
    "@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4"
)
BASE_COMMIT = "7ee9ceb71e868944a46e1ff00b506772a53a4f1d"
DEFAULT_ASSETS = Path(".axrun/validation-inputs/swebench-flask-5014")
DEFAULT_EVIDENCE = Path(".axrun/validation/swebench-flask-5014")
KNOWN_BAD_PATCH = b"""diff --git a/axrun-oracle-known-bad.txt b/axrun-oracle-known-bad.txt
new file mode 100644
--- /dev/null
+++ b/axrun-oracle-known-bad.txt
@@ -0,0 +1 @@
+Unrelated candidate change for an official unresolved control.
"""
ROW_FIELDS = frozenset(
    {
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "base_commit",
        "created_at",
        "difficulty",
        "environment_setup_commit",
        "eval_script",
        "eval_type",
        "hints_text",
        "image",
        "instance_id",
        "log_parser",
        "patch",
        "problem_statement",
        "repo",
        "test_patch",
        "version",
    }
)
ALLOWED_TEST_STATUSES = frozenset({"PASSED", "FAILED", "SKIPPED", "ERROR", "XFAIL"})
APPLY_FAILURE_EXIT = 42
MAX_LOG_BYTES = 16 * 1024 * 1024
DOCKER_LIMITS = [
    "--cpus",
    "2",
    "--memory",
    "4g",
    "--pids-limit",
    "256",
    "--log-driver",
    "none",
]

# The upstream run_instance apply sequence, without its Docker client lifecycle.
# The official eval script and scorer are loaded from the pinned upstream source.
RUNNER = """#!/bin/bash
set -uo pipefail
cd /testbed
if git apply --verbose /tmp/axrun-oracle.patch; then
  :
elif git apply --verbose --reject /tmp/axrun-oracle.patch; then
  :
elif patch --batch --fuzz=5 -p1 -i /tmp/axrun-oracle.patch; then
  :
else
  echo '>>>>> Patch Apply Failed'
  exit 42
fi
/bin/bash /tmp/axrun-oracle-eval.sh
"""
OFFLINE_INSTALL = """set -euo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
python -m pip install -e .
"""


class OracleError(Exception):
    """A failed lock, incomplete oracle result, or infrastructure error."""


class LockedBuildWheel(NamedTuple):
    filename: str
    url: str
    size: int
    sha256: str


def locked_build_wheels() -> tuple[LockedBuildWheel, ...]:
    return (
        LockedBuildWheel(
            SETUPTOOLS_WHEEL_NAME,
            SETUPTOOLS_WHEEL_URL,
            SETUPTOOLS_WHEEL_BYTES,
            SETUPTOOLS_WHEEL_SHA256,
        ),
        LockedBuildWheel(
            WHEEL_DIST_NAME,
            WHEEL_DIST_URL,
            WHEEL_DIST_BYTES,
            WHEEL_DIST_SHA256,
        ),
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def safe_subprocess_env(*, pythonpath: str | None = None) -> dict[str, str]:
    # This oracle has no model connection. Never propagate caller credentials to
    # host-side scorer, Git, uv, or Docker CLI child processes.
    allowed = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SSL_CERT_FILE",
        "UV_CACHE_DIR",
        "XDG_CACHE_HOME",
    )
    env = {key: value for key in allowed if (value := os.environ.get(key)) is not None}
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def scorer_venv_python(path: Path) -> Path:
    # `bin/python` is commonly a symlink. Resolving it changes the interpreter
    # identity to the base Python and makes `uv pip freeze --python` inspect the
    # wrong environment.
    absolute = path.absolute()
    if not absolute.is_file() or not (absolute.parent.parent / "pyvenv.cfg").is_file():
        raise OracleError("official scorer Python must be a prepared virtual environment")
    return absolute


def load_locked_row(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict) or set(row) != ROW_FIELDS:
        raise OracleError("official enriched row has an unknown or missing field")
    if sha256(canonical_json(row)) != ROW_SHA256:
        raise OracleError("official enriched row digest mismatch")
    expected = {
        "instance_id": INSTANCE_ID,
        "repo": "pallets/flask",
        "base_commit": BASE_COMMIT,
        "version": "2.3",
        "image": "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest",
        "log_parser": "parse_log_flask",
        "eval_type": "pass_and_fail",
    }
    for key, value in expected.items():
        if row[key] != value:
            raise OracleError(f"official enriched row {key} differs from lock")
    if not isinstance(row["patch"], str) or not row["patch"].strip():
        raise OracleError("gold patch is missing")
    if not isinstance(row["eval_script"], str) or not row["eval_script"].strip():
        raise OracleError("official eval script is missing")
    for key in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        cases = row[key]
        if (
            not isinstance(cases, list)
            or not cases
            or any(not isinstance(case, str) or not case for case in cases)
        ):
            raise OracleError(f"{key} must be a nonempty test list")
        if len(cases) != len(set(cases)):
            raise OracleError(f"{key} contains duplicate tests")
    if set(row["FAIL_TO_PASS"]) & set(row["PASS_TO_PASS"]):
        raise OracleError("expected test classes overlap")
    return row


def _run(
    args: list[str], *, env: dict[str, str] | None = None, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env=env or safe_subprocess_env(),
        timeout=timeout,
    )


def check_source(path: Path, expected: str, label: str) -> None:
    if not path.is_dir():
        raise OracleError(f"{label} source directory is missing")
    head = _run(["git", "-C", str(path), "rev-parse", "HEAD"])
    if head.returncode != 0 or head.stdout.strip() != expected:
        raise OracleError(f"{label} source commit differs from lock")
    dirty = _run(["git", "-C", str(path), "status", "--porcelain"])
    if dirty.returncode != 0 or dirty.stdout.strip():
        raise OracleError(f"{label} source has modifications or untracked files")


def check_native_linux() -> None:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise OracleError("official oracle requires native linux/amd64; emulation is not accepted")


def _download_parquet(path: Path) -> None:
    if path.exists():
        data = path.read_bytes()
        if len(data) != PARQUET_BYTES or sha256(data) != PARQUET_SHA256:
            raise OracleError("existing official Parquet differs from pinned bytes")
        return
    request = urllib.request.Request(PARQUET_URL, headers={"User-Agent": "axrun-stage-zero/1"})
    temp = path.with_suffix(".download")
    if temp.exists():
        raise OracleError("incomplete Parquet download exists; inspect before retrying")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temp.open("xb") as stream:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) != PARQUET_BYTES:
                raise OracleError("official Parquet response length differs from lock")
            remaining = PARQUET_BYTES + 1
            while remaining:
                block = response.read(min(1024 * 1024, remaining))
                if not block:
                    break
                stream.write(block)
                remaining -= len(block)
        data = temp.read_bytes()
        if len(data) != PARQUET_BYTES or sha256(data) != PARQUET_SHA256:
            raise OracleError("downloaded official Parquet bytes differ from lock")
        temp.chmod(0o600)
        temp.rename(path)
    except Exception:
        if temp.exists():
            temp.unlink()
        raise


def _check_locked_wheel(wheel: Path, artifact: LockedBuildWheel) -> None:
    if wheel.is_symlink() or not stat.S_ISREG(wheel.lstat().st_mode):
        raise OracleError(f"locked {artifact.filename} is not a regular file")
    data = wheel.read_bytes()
    if len(data) != artifact.size or sha256(data) != artifact.sha256:
        raise OracleError(f"locked {artifact.filename} size or SHA-256 differs")


def check_locked_wheelhouse(wheelhouse: Path) -> dict[str, Path]:
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise OracleError("locked wheelhouse directory is missing or is a symlink")
    artifacts = locked_build_wheels()
    entries = {entry.name: entry for entry in wheelhouse.iterdir()}
    if set(entries) != {artifact.filename for artifact in artifacts}:
        raise OracleError("locked wheelhouse contains missing or unknown artifacts")
    for artifact in artifacts:
        _check_locked_wheel(entries[artifact.filename], artifact)
    return entries


def _download_locked_wheel(wheelhouse: Path, artifact: LockedBuildWheel) -> Path:
    if wheelhouse.is_symlink():
        raise OracleError("locked wheelhouse cannot be a symlink")
    wheelhouse.mkdir(mode=0o700, exist_ok=True)
    wheel = wheelhouse / artifact.filename
    allowed = {item.filename for item in locked_build_wheels()}
    if any(entry.name not in allowed for entry in wheelhouse.iterdir()):
        raise OracleError("locked wheelhouse contains unknown artifacts")
    if wheel.exists() or wheel.is_symlink():
        _check_locked_wheel(wheel, artifact)
        return wheel
    temporary = wheelhouse / f".{artifact.filename}.download"
    request = urllib.request.Request(artifact.url, headers={"User-Agent": "axrun-stage-zero/1"})
    try:
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            temporary.open("xb") as stream,
        ):
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) != artifact.size:
                raise OracleError(f"{artifact.filename} response length differs from lock")
            remaining = artifact.size + 1
            while remaining:
                block = response.read(min(1024 * 1024, remaining))
                if not block:
                    break
                stream.write(block)
                remaining -= len(block)
        data = temporary.read_bytes()
        if len(data) != artifact.size or sha256(data) != artifact.sha256:
            raise OracleError(f"downloaded {artifact.filename} size or SHA-256 differs")
        temporary.chmod(0o600)
        temporary.replace(wheel)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    _check_locked_wheel(wheel, artifact)
    return wheel


def _prepare_harness(path: Path) -> None:
    if path.exists():
        check_source(path, HARNESS_COMMIT, "harness")
        return
    path.mkdir(mode=0o700)
    for command in (
        ["git", "-C", str(path), "init", "--quiet"],
        ["git", "-C", str(path), "remote", "add", "origin", HARNESS_URL],
        ["git", "-C", str(path), "fetch", "--depth", "1", "origin", HARNESS_COMMIT],
        ["git", "-C", str(path), "checkout", "--detach", "--quiet", "FETCH_HEAD"],
    ):
        result = _run(command, timeout=300)
        if result.returncode != 0:
            raise OracleError("pinned official harness source preparation failed")
    check_source(path, HARNESS_COMMIT, "harness")


def _prepare_scorer(path: Path, harness_source: Path) -> None:
    python = path / "bin/python"
    if python.is_file():
        result = _run([str(python), "-c", "import pyarrow; import swebench"], timeout=60)
        if result.returncode != 0:
            raise OracleError("existing official scorer environment is unusable")
        return
    result = _run(["uv", "--no-config", "venv", "--python", "3.11", str(path)], timeout=120)
    if result.returncode != 0:
        raise OracleError("official scorer environment creation failed")
    result = _run(
        [
            "uv",
            "--no-config",
            "pip",
            "install",
            "--index-url",
            "https://pypi.org/simple",
            "--python",
            str(python),
            "pyarrow==24.0.0",
            "-e",
            str(harness_source),
        ],
        timeout=1200,
    )
    if result.returncode != 0:
        raise OracleError("official scorer dependencies installation failed")
    result = _run([str(python), "-c", "import pyarrow; import swebench"], timeout=60)
    if result.returncode != 0:
        raise OracleError("prepared official scorer environment cannot import dependencies")


def prepare_assets(assets: Path) -> dict[str, Any]:
    assets.mkdir(mode=0o700, parents=True, exist_ok=True)
    parquet = assets / "test-00000-of-00001.parquet"
    harness = assets / "SWE-bench"
    scorer = assets / "scorer-venv"
    wheelhouse = assets / "wheelhouse"
    _download_parquet(parquet)
    for artifact in locked_build_wheels():
        _download_locked_wheel(wheelhouse, artifact)
    check_locked_wheelhouse(wheelhouse)
    _prepare_harness(harness)
    _prepare_scorer(scorer, harness)
    freeze = _run(
        ["uv", "--no-config", "pip", "freeze", "--python", str(scorer / "bin/python")],
        timeout=60,
    )
    if freeze.returncode != 0:
        raise OracleError("official scorer dependency freeze failed")
    freeze_path = assets / "scorer-packages.txt"
    if freeze_path.exists():
        if freeze_path.read_text(encoding="utf-8") != freeze.stdout:
            raise OracleError("prepared scorer dependencies changed from original frozen set")
    else:
        freeze_path.write_text(freeze.stdout, encoding="utf-8")
        freeze_path.chmod(0o600)
    try:
        image_id = check_local_image(IMAGE)
    except OracleError:
        pull = _run(["docker", "pull", "--platform", "linux/amd64", IMAGE], timeout=1200)
        if pull.returncode != 0:
            raise OracleError("locked official image pull failed") from None
        image_id = check_local_image(IMAGE)
    return {
        "parquet": str(parquet.resolve()),
        "parquet_sha256": PARQUET_SHA256,
        "harness_source": str(harness.resolve()),
        "harness_commit": HARNESS_COMMIT,
        "scorer_python": str(scorer_venv_python(scorer / "bin/python")),
        "scorer_packages_sha256": sha256(freeze.stdout.encode()),
        "image": IMAGE,
        "image_id": image_id,
        "setuptools_wheel_sha256": SETUPTOOLS_WHEEL_SHA256,
        "wheel_distribution_sha256": WHEEL_DIST_SHA256,
    }


def check_local_image(image: str) -> str:
    if image != IMAGE:
        raise OracleError("image must be the locked linux/amd64 platform manifest digest")
    result = _run(["docker", "image", "inspect", image, "--format", "{{json .}}"])
    if result.returncode != 0:
        raise OracleError("locked official image is not locally available; prepare it first")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OracleError("Docker image inspection was malformed") from exc
    if info.get("Os") != "linux" or info.get("Architecture") != "amd64":
        raise OracleError("local official image is not linux/amd64")
    docker_hub_short = image.removeprefix("docker.io/")
    if not {image, docker_hub_short} & set(info.get("RepoDigests", [])):
        raise OracleError("Docker image does not advertise the locked platform digest")
    image_id = info.get("Id")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise OracleError("Docker image ID is missing or malformed")
    return image_id


def _helper(
    *,
    scorer_python: Path,
    harness_source: Path,
    parquet: Path,
    row_path: Path,
    action: str,
    output_path: Path,
    test_log: Path | None = None,
    patch_path: Path | None = None,
) -> dict[str, Any]:
    helper = Path(__file__).with_name("swebench_flask_official_helper.py")
    if not helper.is_file():
        raise OracleError("official scorer helper is missing")
    env = safe_subprocess_env(pythonpath=str(harness_source))
    args = [
        str(scorer_python),
        str(helper),
        action,
        "--harness-source",
        str(harness_source),
        "--parquet",
        str(parquet),
        "--row",
        str(row_path),
        "--output",
        str(output_path),
    ]
    if test_log is not None:
        args.extend(["--test-log", str(test_log)])
    if patch_path is not None:
        args.extend(["--patch", str(patch_path)])
    result = _run(args, env=env, timeout=120)
    if result.returncode != 0:
        # The pinned scorer may print hidden test content on failure. Keep it private.
        error_path = output_path.with_suffix(".helper.stderr.txt")
        _write_private(error_path, (result.stderr + result.stdout).encode("utf-8"))
        raise OracleError(f"official {action} failed; see private helper stderr")
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OracleError(f"official {action} produced no valid JSON") from exc
    if not isinstance(payload, dict):
        raise OracleError(f"official {action} JSON is not an object")
    return payload


def _write_private(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
    path.chmod(0o600)


def _container_absent(name: str) -> bool:
    result = _run(
        ["docker", "ps", "--all", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"]
    )
    if result.returncode != 0:
        raise OracleError("Docker container cleanup status could not be checked")
    return not result.stdout.strip()


def _ensure_removed(name: str) -> None:
    if not _container_absent(name):
        result = _run(["docker", "rm", "--force", name])
        if result.returncode != 0 or not _container_absent(name):
            raise OracleError("owned oracle container cleanup failed")


def _limit_log() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_LOG_BYTES, MAX_LOG_BYTES))


def _wheelhouse_docker_args(wheelhouse: Path) -> list[str]:
    check_locked_wheelhouse(wheelhouse)
    if "," in str(wheelhouse):
        raise OracleError("oracle wheelhouse path cannot contain a comma")
    return [
        "--mount",
        f"type=bind,source={wheelhouse},target={WHEELHOUSE_MOUNT},readonly",
        "--env",
        OFFLINE_PIP_ENV[0],
        "--env",
        OFFLINE_PIP_ENV[1],
    ]


def check_offline_install(
    output_dir: Path, timeout_seconds: int, wheelhouse: Path
) -> dict[str, Any]:
    """Prove the official eval-script installation command works without egress."""
    name = f"axrun-sweb-flask-install-{uuid.uuid4().hex[:16]}"
    path = output_dir / "offline_install.txt"
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--pull",
        "never",
        "--platform",
        "linux/amd64",
        "--user",
        "root",
        "--workdir",
        "/testbed",
        *DOCKER_LIMITS,
        *_wheelhouse_docker_args(wheelhouse),
        "--entrypoint",
        "/bin/bash",
        IMAGE,
        "-c",
        OFFLINE_INSTALL,
    ]
    try:
        with path.open("xb") as stream:
            result = subprocess.run(
                command,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=min(timeout_seconds, 600),
                env=safe_subprocess_env(),
                preexec_fn=_limit_log,
            )
    except subprocess.TimeoutExpired:
        raise OracleError("official offline install timed out") from None
    finally:
        _ensure_removed(name)
    path.chmod(0o600)
    if result.returncode != 0:
        raise OracleError("official eval-script install command failed offline")
    data = path.read_bytes()
    return {
        "command": "python -m pip install -e .",
        "network": "none",
        "exit_code": 0,
        "container_removed": True,
        "output_bytes": len(data),
        "output_sha256": sha256(data),
    }


def run_case(
    *,
    name: str,
    patch: bytes,
    eval_script: bytes,
    output_dir: Path,
    timeout_seconds: int,
    wheelhouse: Path,
) -> dict[str, Any]:
    case_dir = output_dir / name
    case_dir.mkdir(mode=0o700)
    patch_path = case_dir / "patch.diff"
    eval_path = case_dir / "eval.sh"
    runner_path = case_dir / "runner.sh"
    log_path = case_dir / "test_output.txt"
    _write_private(patch_path, patch)
    _write_private(eval_path, eval_script)
    _write_private(runner_path, RUNNER.encode("utf-8"))
    container_name = f"axrun-sweb-flask-oracle-{uuid.uuid4().hex[:16]}"
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--pull",
        "never",
        "--platform",
        "linux/amd64",
        "--user",
        "root",
        "--workdir",
        "/testbed",
        *DOCKER_LIMITS,
        *_wheelhouse_docker_args(wheelhouse),
        "--entrypoint",
        "/bin/bash",
    ]
    for source, target in (
        (patch_path, "/tmp/axrun-oracle.patch"),
        (eval_path, "/tmp/axrun-oracle-eval.sh"),
        (runner_path, "/tmp/axrun-oracle-runner.sh"),
    ):
        if "," in str(source):
            raise OracleError("oracle output path cannot contain a comma")
        command.extend(["--mount", f"type=bind,source={source},target={target},readonly"])
    command.extend([IMAGE, "/tmp/axrun-oracle-runner.sh"])
    started = time.monotonic()
    timed_out = False
    try:
        with log_path.open("xb") as stream:
            result = subprocess.run(
                command,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout_seconds,
                env=safe_subprocess_env(),
                preexec_fn=_limit_log,
            )
            exit_code = result.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = None
    finally:
        _ensure_removed(container_name)
    log_path.chmod(0o600)
    log = log_path.read_bytes()
    return {
        "container_name": container_name,
        "container_removed": True,
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "test_output_bytes": len(log),
        "test_output_sha256": sha256(log),
        "patch_sha256": sha256(patch),
        "eval_script_sha256": sha256(eval_script),
    }


def classify_case(name: str, result: dict[str, Any], log_path: Path) -> str:
    if result["timed_out"]:
        raise OracleError(f"{name} oracle timed out; no benchmark verdict")
    if result["exit_code"] == APPLY_FAILURE_EXIT:
        if b">>>>> Patch Apply Failed" not in log_path.read_bytes():
            raise OracleError(f"{name} patch exit lacked apply-failure marker")
        raise OracleError(f"{name} patch could not apply; no benchmark verdict")
    log = log_path.read_bytes()
    complete_markers = b">>>>> Start Test Output" in log and b">>>>> End Test Output" in log
    if not complete_markers:
        raise OracleError(f"{name} oracle test markers are incomplete; no benchmark verdict")
    # Pinned upstream run_instance grades complete test output even when the eval
    # command exits nonzero; the official grader remains authoritative below.
    return "test_completed" if result["exit_code"] == 0 else "test_completed_nonzero_exit"


def validate_official_grade(row: dict[str, Any], grade: dict[str, Any]) -> dict[str, int | bool]:
    status_map = grade.get("status_map")
    report = grade.get("report")
    if not isinstance(status_map, dict) or not isinstance(report, dict):
        raise OracleError("official scorer result is incomplete")
    if any(not isinstance(k, str) or v not in ALLOWED_TEST_STATUSES for k, v in status_map.items()):
        raise OracleError("official scorer returned an unknown test status")
    expected = set(row["FAIL_TO_PASS"]) | set(row["PASS_TO_PASS"])
    if not expected <= status_map.keys():
        raise OracleError("official test output is incomplete; expected tests are missing")
    if any(status_map[case] == "SKIPPED" for case in expected):
        raise OracleError(
            "official scorer excludes a skipped expected test; parity is inconclusive"
        )
    instance_report = report.get(INSTANCE_ID)
    if not isinstance(instance_report, dict):
        raise OracleError("official scorer omitted instance report")
    if (
        instance_report.get("patch_is_None") is not False
        or instance_report.get("patch_exists") is not True
        or instance_report.get("patch_successfully_applied") is not True
        or not isinstance(instance_report.get("resolved"), bool)
    ):
        raise OracleError("official scorer patch or resolution fields are incomplete")
    tests_status = instance_report.get("tests_status")
    if not isinstance(tests_status, dict):
        raise OracleError("official scorer omitted per-test report")
    for category in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        section = tests_status.get(category)
        if not isinstance(section, dict):
            raise OracleError(f"official scorer omitted {category}")
        success, failure = section.get("success"), section.get("failure")
        if not isinstance(success, list) or not isinstance(failure, list):
            raise OracleError(f"official scorer {category} status is malformed")
        if any(not isinstance(case, str) for case in success + failure):
            raise OracleError(f"official scorer {category} status is malformed")
        if (
            set(success) | set(failure) != set(row[category])
            or set(success) & set(failure)
            or len(success) + len(failure) != len(row[category])
        ):
            raise OracleError(f"official scorer {category} denominator differs from lock")
    return {
        "expected_tests": len(expected),
        "observed_tests": len(status_map),
        "fail_to_pass_success": len(tests_status["FAIL_TO_PASS"]["success"]),
        "fail_to_pass_failure": len(tests_status["FAIL_TO_PASS"]["failure"]),
        "pass_to_pass_success": len(tests_status["PASS_TO_PASS"]["success"]),
        "pass_to_pass_failure": len(tests_status["PASS_TO_PASS"]["failure"]),
        "resolved": instance_report.get("resolved") is True,
    }


def _validate_empty(report: dict[str, Any]) -> dict[str, Any]:
    if (
        report.get("schema_version") != 2
        or report.get("submitted_instances") != 1
        or report.get("empty_patch_instances") != 1
        or report.get("empty_patch_ids") != [INSTANCE_ID]
    ):
        raise OracleError("official scorer did not classify empty patch")
    if (
        report.get("completed_instances") != 0
        or report.get("resolved_instances") != 0
        or report.get("error_instances") != 0
    ):
        raise OracleError("official scorer assigned an invalid empty-patch test verdict")
    return {
        "classification": "official_empty_patch_unscored",
        "official_report_schema": report.get("schema_version"),
        "test_statuses": None,
        "resolved": None,
    }


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(canonical_json(receipt) + b"\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("all", "prepare", "run"), default="all")
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--row", type=Path, help="optional pre-prepared enriched row JSON")
    parser.add_argument("--parquet", type=Path, help="optional prepared pinned Parquet")
    parser.add_argument("--harness-source", type=Path, help="optional pinned harness checkout")
    parser.add_argument("--scorer-python", type=Path, help="optional prepared scorer Python")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    try:
        check_native_linux()
        if not 60 <= args.timeout_seconds <= 3600:
            raise OracleError("timeout must be between 60 and 3600 seconds")
        assets = args.assets_dir.resolve()
        wheelhouse = assets / "wheelhouse"
        if args.action in {"all", "prepare"}:
            prepared = prepare_assets(assets)
            if args.action == "prepare":
                print(
                    json.dumps(
                        {
                            "dataset_commit": DATASET_COMMIT,
                            "parquet_sha256": prepared["parquet_sha256"],
                            "harness_commit": HARNESS_COMMIT,
                            "scorer_packages_sha256": prepared["scorer_packages_sha256"],
                            "image_id": prepared["image_id"],
                            "setuptools_wheel_sha256": prepared["setuptools_wheel_sha256"],
                            "wheel_distribution_sha256": prepared["wheel_distribution_sha256"],
                        },
                        sort_keys=True,
                    )
                )
                return 0
        parquet = (args.parquet or assets / "test-00000-of-00001.parquet").resolve()
        harness_source = (args.harness_source or assets / "SWE-bench").resolve()
        scorer_python = scorer_venv_python(args.scorer_python or assets / "scorer-venv/bin/python")
        check_source(harness_source, HARNESS_COMMIT, "harness")
        freeze_path = assets / "scorer-packages.txt"
        if not freeze_path.is_file():
            raise OracleError("prepared official scorer package freeze is missing")
        current_freeze = _run(
            ["uv", "--no-config", "pip", "freeze", "--python", str(scorer_python)],
            timeout=60,
        )
        if current_freeze.returncode != 0:
            raise OracleError("official scorer dependency inspection failed")
        expected_freeze = freeze_path.read_text(encoding="utf-8")
        if current_freeze.stdout != expected_freeze:
            observed_path = assets / f"scorer-packages-observed-{uuid.uuid4().hex[:8]}.txt"
            _write_private(observed_path, current_freeze.stdout.encode("utf-8"))
            raise OracleError(
                "official scorer dependencies differ from frozen preparation "
                f"(expected_sha256={sha256(expected_freeze.encode())}, "
                f"actual_sha256={sha256(current_freeze.stdout.encode())}; "
                "see private observed scorer package artifact)"
            )
        image_id = check_local_image(args.image)
        check_locked_wheelhouse(wheelhouse)
        output_dir = (
            args.output_dir
            or DEFAULT_EVIDENCE / f"oracle-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        ).resolve()
        if output_dir.exists():
            raise OracleError("private output directory already exists")
        output_dir.mkdir(mode=0o700, parents=True)
        row_path = (args.row or output_dir / "official_row.json").resolve()
        prepared_path = output_dir / "official_preparation.json"
        preparation = _helper(
            scorer_python=scorer_python,
            harness_source=harness_source,
            parquet=parquet,
            row_path=row_path,
            action="prepare",
            output_path=prepared_path,
        )
        row = load_locked_row(row_path)
        if preparation.get("raw_row_match") is not True:
            raise OracleError("enriched row does not match pinned raw dataset row")
        if preparation.get("eval_script_sha256") != sha256(row["eval_script"].encode()):
            raise OracleError("enriched eval script differs from pinned official harness")
        receipt: dict[str, Any] = {
            "schema_version": "axrun.swebench-flask-official-oracle@1",
            "instance_id": INSTANCE_ID,
            "dataset_commit": DATASET_COMMIT,
            "parquet_sha256": PARQUET_SHA256,
            "harness_commit": HARNESS_COMMIT,
            "scorer_packages_sha256": sha256(freeze_path.read_bytes()),
            "scorer_dependency_lock_scope": (
                "first host-side preparation freezes installed packages for subsequent local runs; "
                "transitive package versions were not predeclared"
            ),
            "row_sha256": ROW_SHA256,
            "eval_script_sha256": preparation["eval_script_sha256"],
            "image": IMAGE,
            "image_id": image_id,
            "platform": "linux/amd64",
            "network": "none",
            "offline_build_wheels": [
                {
                    "filename": artifact.filename,
                    "bytes": artifact.size,
                    "sha256": artifact.sha256,
                    "source": artifact.url,
                }
                for artifact in locked_build_wheels()
            ],
            "offline_build_wheelhouse_mount": WHEELHOUSE_MOUNT,
            "offline_build_wheelhouse_readonly": True,
            "offline_pip_environment": {
                "PIP_NO_INDEX": "1",
                "PIP_FIND_LINKS": WHEELHOUSE_MOUNT,
            },
            "docker_limits": {"cpus": 2, "memory": "4g", "pids": 256, "log_driver": "none"},
            "case_timeout_seconds": args.timeout_seconds,
            "max_caller_log_bytes": MAX_LOG_BYTES,
            "official_run_instance_used": False,
            "official_test_spec_eval_script_and_grader_used": True,
            "harness_divergence": (
                "Docker --network none and pinned platform digest are imposed by this tool; "
                "the content-verified setuptools and wheel distributions are mounted read-only "
                "and PIP_NO_INDEX/"
                "PIP_FIND_LINKS are fixed to make the official install command offline; "
                "upstream run_instance does not expose these settings"
            ),
            "cases": {},
        }
        receipt["offline_install"] = check_offline_install(
            output_dir, args.timeout_seconds, wheelhouse
        )
        _write_receipt(output_dir / "receipt.json", receipt)
        for name, patch in (("gold", row["patch"].encode()), ("known_bad", KNOWN_BAD_PATCH)):
            result = run_case(
                name=name,
                patch=patch,
                eval_script=row["eval_script"].encode(),
                output_dir=output_dir,
                timeout_seconds=args.timeout_seconds,
                wheelhouse=wheelhouse,
            )
            log_path = output_dir / name / "test_output.txt"
            result["classification"] = classify_case(name, result, log_path)
            grade = _helper(
                scorer_python=scorer_python,
                harness_source=harness_source,
                parquet=parquet,
                row_path=row_path,
                action="grade",
                output_path=output_dir / name / "official_grade.json",
                test_log=log_path,
                patch_path=output_dir / name / "patch.diff",
            )
            result["official_summary"] = validate_official_grade(row, grade)
            if result["official_summary"]["resolved"] is not (name == "gold"):
                raise OracleError(f"{name} official resolution differs from stage-zero control")
            receipt["cases"][name] = result
            _write_receipt(output_dir / "receipt.json", receipt)
        empty_report = _helper(
            scorer_python=scorer_python,
            harness_source=harness_source,
            parquet=parquet,
            row_path=row_path,
            action="empty",
            output_path=output_dir / "official_empty_report.json",
        )
        receipt["cases"]["empty"] = _validate_empty(empty_report)
        _write_receipt(output_dir / "receipt.json", receipt)
        print(
            json.dumps(
                {
                    "instance_id": INSTANCE_ID,
                    "gold": receipt["cases"]["gold"]["official_summary"],
                    "known_bad": receipt["cases"]["known_bad"]["official_summary"],
                    "empty": "official_empty_patch_unscored",
                    "receipt_sha256": sha256((output_dir / "receipt.json").read_bytes()),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OracleError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"oracle failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
