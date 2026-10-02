# pyright: basic
"""Native linux/amd64, model-free official oracle for django__django-12419.

All inputs must already be prepared. This tool neither downloads nor builds an
image. Each diagnostic candidate executes in a fresh offline Docker container;
only the pinned upstream SWE-bench scorer assigns benchmark verdicts. The empty
candidate is executed for isolation evidence but is officially *unscored*.
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
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import swebench_django_assets as asset_lock

INSTANCE_ID = "django__django-12419"
BASE_COMMIT = "7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
OFFICIAL_SOURCE_IMAGE = (
    "docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419"
    "@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768"
)
SEED_LABELS = {
    "io.axrun.instance-id": INSTANCE_ID,
    "io.axrun.platform-role": "benchmark",
    "io.axrun.repo": "django/django",
    "io.axrun.base-commit": BASE_COMMIT,
}
ALLOWED_STATUSES = frozenset({"PASSED", "FAILED", "SKIPPED", "ERROR", "XFAIL"})
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_AUDIT_BYTES = 1024
MIN_SYSTEM_PYTHON = (3, 8, 0)
APPLY_FAILURE_EXIT = 42
DOCKER_LIMITS = ("--cpus", "2", "--memory", "4g", "--pids-limit", "256", "--log-driver", "none")

RUNNER = """#!/bin/bash
set -uo pipefail
cd /testbed
if [[ -s /tmp/axrun-oracle.patch ]]; then
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
fi
/bin/bash /tmp/axrun-oracle-eval.sh
"""

AUDIT = f"""set -euo pipefail
test "$(uname -m)" = x86_64
export GIT_OPTIONAL_LOCKS=0
head=$(git -C /testbed rev-parse --verify HEAD)
status=$(git -C /testbed status --porcelain=v1 --untracked-files=all)
base_present=false
if git -C /testbed cat-file -e '{BASE_COMMIT}^{{commit}}' 2>/dev/null; then
  base_present=true
fi
dirty=false
if [[ -n "$status" ]]; then dirty=true; fi
system_python=$(/usr/bin/python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
source /opt/miniconda3/bin/activate
conda activate testbed
test_python=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
read -r object_count object_store_kib < <(
  git -C /testbed count-objects -v | awk '
    $1 == "count:" {{ loose=$2; saw_loose=1 }}
    $1 == "in-pack:" {{ packed=$2; saw_packed=1 }}
    $1 == "size:" {{ loose_kib=$2; saw_loose_kib=1 }}
    $1 == "size-pack:" {{ packed_kib=$2; saw_packed_kib=1 }}
    END {{
      if (!(saw_loose && saw_packed && saw_loose_kib && saw_packed_kib)) exit 1
      printf "%.0f %.0f\\n", loose+packed, loose_kib+packed_kib
    }}'
)
printf \
  '{{"git_head":"%s","git_dirty":%s,"base_commit_present":%s,'\
'"system_python":"%s","test_python":"%s",'\
'"git_object_count":%s,"git_object_store_kib":%s}}\\n' \
  "$head" "$dirty" "$base_present" "$system_python" "$test_python" \
  "$object_count" "$object_store_kib"
"""

# Passed as code, never with hidden row, patch, or test content in argv. The
# child imports the exact checked-out upstream package and writes only private
# JSON. Upstream scorer exceptions and output are deliberately not relayed.
SCORER_BRIDGE = r"""
import json
import os
import sys
from pathlib import Path

action, source, row_file, patch_file, log_file, output_file = sys.argv[1:]
source = Path(source).resolve()
sys.path.insert(0, str(source))
import swebench
if Path(swebench.__file__).resolve().parent != source / "swebench":
    raise ValueError("official scorer imported from another source")
from swebench.harness.test_spec.test_spec import make_test_spec
row = json.loads(Path(row_file).read_text(encoding="utf-8"))
spec = make_test_spec(row, namespace="swebench")
if (spec.instance_image_key != row["image"] or spec.eval_script != row["eval_script"]
        or spec.FAIL_TO_PASS != row["FAIL_TO_PASS"]
        or spec.PASS_TO_PASS != row["PASS_TO_PASS"]):
    raise ValueError("official TestSpec differs from prepared row")
prediction = {
    "instance_id": row["instance_id"],
    "model_name_or_path": "axrun-django-native-oracle",
    "model_patch": Path(patch_file).read_text(encoding="utf-8"),
}
if action == "grade":
    from swebench.harness.grading import get_eval_report, get_logs_eval
    status_map, found = get_logs_eval(spec, log_file)
    if not found:
        raise ValueError("official scorer did not find complete test output")
    payload = {
        "status_map": status_map,
        "report": get_eval_report(spec, prediction, log_file, include_tests_status=True),
    }
elif action == "empty":
    if Path(patch_file).stat().st_size != 0:
        raise ValueError("empty patch is not zero bytes")
    from swebench.harness.reporting import make_run_report
    old_cwd = Path.cwd()
    try:
        os.chdir(Path(output_file).parent)
        report = make_run_report(
            {row["instance_id"]: prediction}, [row], "axrun-django-native-empty", client=None
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
    finally:
        os.chdir(old_cwd)
else:
    raise ValueError("unknown scorer action")
with Path(output_file).open("x", encoding="utf-8") as stream:
    json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
os.chmod(output_file, 0o600)
"""


class OracleError(Exception):
    """An input lock, infrastructure, cleanup, or official verdict failure."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def child_env(*, source: Path | None = None) -> dict[str, str]:
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "UV_CACHE_DIR", "XDG_CACHE_HOME")
    env = {key: value for key in allowed if (value := os.environ.get(key)) is not None}
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    if source is not None:
        env["PYTHONPATH"] = str(source)
    return env


def _run(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=timeout, env=child_env()
        )
    except subprocess.TimeoutExpired as exc:
        raise OracleError("bounded host-side inspection timed out") from exc


def _private_file(path: Path) -> Path:
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise OracleError("prepared input must be a regular file, not a symlink")
    return path


def _write_private(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    _write_private(temporary, canonical_json(payload) + b"\n")
    temporary.replace(path)


def check_native_docker() -> None:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise OracleError("official oracle requires native linux/amd64")
    context = _run(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"])
    if context.returncode != 0:
        raise OracleError("Docker context cannot be inspected")
    try:
        endpoint = json.loads(context.stdout)
    except json.JSONDecodeError as exc:
        raise OracleError("Docker context endpoint is malformed") from exc
    if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
        raise OracleError("official oracle requires a local Unix-socket Docker daemon")
    info = _run(["docker", "info", "--format", "{{json .}}"])
    if info.returncode != 0:
        raise OracleError("Docker daemon cannot be inspected")
    try:
        payload = json.loads(info.stdout)
    except json.JSONDecodeError as exc:
        raise OracleError("Docker daemon information is malformed") from exc
    if payload.get("OSType") != "linux" or payload.get("Architecture") not in {"x86_64", "amd64"}:
        raise OracleError("Docker daemon is not native linux/amd64")


def check_source(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise OracleError("pinned scorer source is missing or symlinked")
    head = _run(["git", "-C", str(path), "rev-parse", "--verify", "HEAD"])
    if head.returncode != 0 or head.stdout.strip() != asset_lock.HARNESS_COMMIT:
        raise OracleError("official scorer source commit differs from lock")
    status = _run(["git", "-C", str(path), "status", "--porcelain=v1", "--untracked-files=all"])
    if status.returncode != 0 or status.stdout.strip():
        raise OracleError("official scorer source is not clean")


def check_scorer(python: Path, freeze: Path, source: Path) -> str:
    python = python.absolute()  # retain venv symlink, rather than resolving to base Python
    if not python.is_file() or not (python.parent.parent / "pyvenv.cfg").is_file():
        raise OracleError("official scorer Python must be a prepared virtual environment")
    _private_file(freeze)
    frozen = freeze.read_bytes()
    if not frozen or len(frozen) > 256 * 1024:
        raise OracleError("official scorer dependency freeze is missing or oversized")
    current = _run(["uv", "--no-config", "pip", "freeze", "--python", str(python)])
    if current.returncode != 0 or current.stdout.encode() != frozen:
        raise OracleError("official scorer dependencies differ from prepared freeze")
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import pathlib, swebench; print(pathlib.Path(swebench.__file__).resolve().parent)",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=child_env(source=source),
    )
    if probe.returncode != 0 or probe.stdout.strip() != str((source / "swebench").resolve()):
        raise OracleError("official scorer imports a different SWE-bench source")
    return digest(frozen)


def check_assets(assets_dir: Path) -> tuple[dict[str, Any], dict[str, Path], str]:
    if assets_dir.is_symlink() or not assets_dir.is_dir():
        raise OracleError("explicit prepared asset directory is missing or symlinked")
    try:
        manifest = asset_lock.validate_assets(assets_dir)
        paths = {
            name: _private_file(assets_dir / filename)
            for name, filename in (
                ("row", "row.json"),
                ("gold", "gold.patch"),
                ("known_bad", "known_bad.patch"),
                ("empty", "empty.patch"),
                ("eval", "eval.sh"),
                ("test", "test.patch"),
                ("manifest", "assets-manifest.json"),
            )
        }
        row = asset_lock.load_locked_row(paths["row"])
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        raise OracleError("prepared Django asset lock validation failed") from exc
    if row.get("instance_id") != INSTANCE_ID or row.get("base_commit") != BASE_COMMIT:
        raise OracleError("prepared row identity differs from native oracle")
    if paths["gold"].read_bytes() != row["patch"].encode():
        raise OracleError("prepared gold patch differs from locked row")
    if paths["test"].read_bytes() != row["test_patch"].encode():
        raise OracleError("prepared test patch differs from locked row")
    if paths["eval"].read_bytes() != row["eval_script"].encode():
        raise OracleError("prepared eval script differs from locked row")
    known_bad = paths["known_bad"].read_bytes()
    if not known_bad or known_bad == paths["gold"].read_bytes():
        raise OracleError("synthetic known-bad control must be nonempty and distinct")
    if paths["empty"].stat().st_size != 0:
        raise OracleError("empty control must be zero bytes")
    return row, paths, digest(canonical_json(manifest))


def check_private_output_destination(path: Path) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise OracleError("private output must be a new explicit absolute directory")
    if path != path.resolve(strict=False):
        raise OracleError("private output path must not traverse a symlink")
    existing = path.parent
    while not existing.exists():
        existing = existing.parent
    if not existing.is_dir():
        raise OracleError("private output parent is not a directory")
    checkout = _run(["git", "-C", str(existing), "rev-parse", "--show-toplevel"])
    if checkout.returncode != 0:
        return  # Outside Git, the newly created directory is mode 0700.
    root = Path(checkout.stdout.strip()).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OracleError("private output Git root could not be established") from exc
    ignored = _run(
        ["git", "-C", str(root), "check-ignore", "-q", "--no-index", "--", str(relative)]
    )
    if ignored.returncode != 0:
        raise OracleError("private output inside Git must be ignored")


def _inspect_image(image: str) -> dict[str, Any]:
    result = _run(["docker", "image", "inspect", image, "--format", "{{json .}}"])
    if result.returncode != 0:
        raise OracleError("required local amd64 image is unavailable")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OracleError("Docker image inspection is malformed") from exc
    if (
        not isinstance(info, dict)
        or info.get("Os") != "linux"
        or info.get("Architecture") != "amd64"
    ):
        raise OracleError("image is not linux/amd64")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", str(info.get("Id"))) is None:
        raise OracleError("Docker image ID is malformed")
    rootfs = info.get("RootFS")
    if not isinstance(rootfs, dict):
        raise OracleError("Docker image root filesystem identity is malformed")
    layers = rootfs.get("Layers")
    if (
        not isinstance(layers, list)
        or not layers
        or any(re.fullmatch(r"sha256:[0-9a-f]{64}", str(layer)) is None for layer in layers)
    ):
        raise OracleError("Docker image layer identity is malformed")
    return info


def check_images(seed_image_id: str) -> dict[str, Any]:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", seed_image_id) is None:
        raise OracleError("derived seed must be selected by immutable local image ID")
    source = _inspect_image(OFFICIAL_SOURCE_IMAGE)
    repo_digests = source.get("RepoDigests")
    allowed = {OFFICIAL_SOURCE_IMAGE, OFFICIAL_SOURCE_IMAGE.removeprefix("docker.io/")}
    if not isinstance(repo_digests, list) or not allowed.intersection(repo_digests):
        raise OracleError("official source image does not advertise locked platform manifest")
    seed = _inspect_image(seed_image_id)
    if seed["Id"] != seed_image_id or seed_image_id == source["Id"]:
        raise OracleError("derived seed image ID is wrong or aliases the source")
    source_layers = source["RootFS"]["Layers"]
    seed_layers = seed["RootFS"]["Layers"]
    if (
        len(seed_layers) != len(source_layers) + 1
        or seed_layers[: len(source_layers)] != source_layers
    ):
        raise OracleError("derived seed does not have the exact official source layer ancestry")
    config = seed.get("Config")
    if not isinstance(config, dict):
        raise OracleError("derived seed configuration is malformed")
    labels = config.get("Labels")
    if not isinstance(labels, dict) or any(labels.get(k) != v for k, v in SEED_LABELS.items()):
        raise OracleError("derived seed labels differ from Django amd64 contract")
    return {"source_image_id": source["Id"], "seed_image_id": seed_image_id}


def _container_absent(name: str) -> bool:
    result = _run(
        ["docker", "ps", "--all", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"]
    )
    if result.returncode != 0:
        raise OracleError("container cleanup status could not be checked")
    names = result.stdout.splitlines()
    if any(value != name for value in names):
        raise OracleError("container cleanup query returned unexpected identity")
    return not names


def _ensure_removed(name: str) -> None:
    if not _container_absent(name):
        removed = _run(["docker", "rm", "--force", name])
        if removed.returncode != 0 or not _container_absent(name):
            raise OracleError("owned oracle container cleanup is incomplete")


def _limit_log() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_LOG_BYTES, MAX_LOG_BYTES))


def _limit_audit() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_AUDIT_BYTES, MAX_AUDIT_BYTES))


def audit_seed(seed_image_id: str) -> dict[str, Any]:
    name = f"axrun-django-audit-{uuid.uuid4().hex[:16]}"
    if not _container_absent(name):
        raise OracleError("oracle container name already exists")
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
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "root",
        "--workdir",
        "/testbed",
        *DOCKER_LIMITS,
        "--entrypoint",
        "/bin/bash",
        seed_image_id,
        "-c",
        AUDIT,
    ]
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                command,
                stdout=output,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=60,
                env=child_env(),
                preexec_fn=_limit_audit,
            )
            output.seek(0)
            payload = output.read(MAX_AUDIT_BYTES + 1)
    except subprocess.TimeoutExpired as exc:
        raise OracleError("derived seed audit timed out") from exc
    finally:
        _ensure_removed(name)
    if result.returncode != 0 or len(payload) > MAX_AUDIT_BYTES:
        raise OracleError("derived seed audit failed or exceeded its output bound")
    try:
        contract = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OracleError("derived seed audit output is malformed") from exc
    if (
        not isinstance(contract, dict)
        or set(contract)
        != {
            "git_head",
            "git_dirty",
            "base_commit_present",
            "system_python",
            "test_python",
            "git_object_count",
            "git_object_store_kib",
        }
        or contract["git_head"] != BASE_COMMIT
        or contract["git_dirty"] is not False
        or contract["base_commit_present"] is not True
        or not isinstance(contract["system_python"], str)
        or re.fullmatch(r"3\.\d+\.\d+", contract["system_python"]) is None
        or tuple(map(int, contract["system_python"].split("."))) < MIN_SYSTEM_PYTHON
        or not isinstance(contract["test_python"], str)
        or re.fullmatch(r"3\.\d+\.\d+", contract["test_python"]) is None
        or type(contract["git_object_count"]) is not int
        or contract["git_object_count"] < 1
        or type(contract["git_object_store_kib"]) is not int
        or contract["git_object_store_kib"] < 1
    ):
        raise OracleError(
            "derived seed audit violates clean base, Python, or Git aggregate contract"
        )
    return contract


def _mount(source: Path, target: str) -> str:
    if "," in str(source):
        raise OracleError("oracle input path cannot contain a comma")
    return f"type=bind,source={source},target={target},readonly"


def run_case(
    name: str,
    patch: Path,
    eval_script: Path,
    output_dir: Path,
    seed_image_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    case_dir = output_dir / name
    case_dir.mkdir(mode=0o700)
    runner = case_dir / "runner.sh"
    log_path = case_dir / "test_output.txt"
    _write_private(runner, RUNNER.encode())
    container = f"axrun-django-oracle-{uuid.uuid4().hex[:16]}"
    if not _container_absent(container):
        raise OracleError("oracle container name already exists")
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container,
        "--network",
        "none",
        "--pull",
        "never",
        "--platform",
        "linux/amd64",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "root",
        "--workdir",
        "/testbed",
        *DOCKER_LIMITS,
        "--env",
        "PIP_NO_INDEX=1",
        "--env",
        "PIP_DISABLE_PIP_VERSION_CHECK=1",
        "--mount",
        _mount(patch, "/tmp/axrun-oracle.patch"),
        "--mount",
        _mount(eval_script, "/tmp/axrun-oracle-eval.sh"),
        "--mount",
        _mount(runner, "/tmp/axrun-oracle-runner.sh"),
        "--entrypoint",
        "/bin/bash",
        seed_image_id,
        "/tmp/axrun-oracle-runner.sh",
    ]
    started = time.monotonic()
    timed_out = False
    exit_code: int | None = None
    try:
        with log_path.open("xb") as stream:
            os.chmod(log_path, 0o600)
            try:
                result = subprocess.run(
                    command,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=timeout_seconds,
                    env=child_env(),
                    preexec_fn=_limit_log,
                )
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        _ensure_removed(container)
    log = log_path.read_bytes()
    if timed_out:
        raise OracleError(f"{name} container timed out; no benchmark verdict")
    if len(log) >= MAX_LOG_BYTES:
        raise OracleError(f"{name} container output reached its size bound")
    if exit_code == APPLY_FAILURE_EXIT:
        raise OracleError(f"{name} patch application failed; no benchmark verdict")
    if b">>>>> Start Test Output" not in log or b">>>>> End Test Output" not in log:
        raise OracleError(f"{name} official test output markers are incomplete")
    return {
        "container_removed": True,
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": exit_code,
        "test_output_bytes": len(log),
        "test_output_sha256": digest(log),
        "patch_sha256": digest(patch.read_bytes()),
        "classification": "test_completed" if exit_code == 0 else "test_completed_nonzero_exit",
    }


def official_scorer(
    action: str,
    scorer_python: Path,
    source: Path,
    row: Path,
    patch: Path,
    log: Path,
    output: Path,
) -> dict[str, Any]:
    if action not in {"grade", "empty"}:
        raise OracleError("unknown official scorer action")
    result = subprocess.run(
        [
            str(scorer_python),
            "-c",
            SCORER_BRIDGE,
            action,
            str(source),
            str(row),
            str(patch),
            str(log),
            str(output),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=180,
        env=child_env(source=source),
    )
    if result.returncode != 0:
        raise OracleError(f"official {action} scorer failed")
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OracleError(f"official {action} scorer output is malformed") from exc
    if not isinstance(payload, dict):
        raise OracleError(f"official {action} scorer output is not an object")
    return payload


def validate_grade(row: dict[str, Any], grade: dict[str, Any], name: str) -> dict[str, Any]:
    status_map, report = grade.get("status_map"), grade.get("report")
    if not isinstance(status_map, dict) or not isinstance(report, dict):
        raise OracleError("official scorer result is incomplete")
    if any(
        not isinstance(key, str) or not isinstance(value, str) or value not in ALLOWED_STATUSES
        for key, value in status_map.items()
    ):
        raise OracleError("official scorer returned an unknown test status")
    expected = set(row["FAIL_TO_PASS"]) | set(row["PASS_TO_PASS"])
    if not expected <= status_map.keys():
        raise OracleError("official test output is incomplete; expected status is missing")
    if any(status_map[case] in {"SKIPPED", "XFAIL"} for case in expected):
        raise OracleError("official expected test status is inconclusive")
    instance = report.get(INSTANCE_ID)
    if not isinstance(instance, dict) or (
        instance.get("patch_is_None") is not False
        or instance.get("patch_exists") is not True
        or instance.get("patch_successfully_applied") is not True
        or not isinstance(instance.get("resolved"), bool)
    ):
        raise OracleError("official scorer patch or resolution fields are incomplete")
    sections = instance.get("tests_status")
    if not isinstance(sections, dict) or set(sections) != {
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "FAIL_TO_FAIL",
        "PASS_TO_FAIL",
    }:
        raise OracleError("official scorer per-test status is missing")
    for extra in ("FAIL_TO_FAIL", "PASS_TO_FAIL"):
        section = sections[extra]
        if not isinstance(section, dict) or section != {"success": [], "failure": []}:
            raise OracleError(f"official scorer {extra} control must be empty")
    counts: dict[str, int] = {}
    for category in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        section = sections[category]
        if not isinstance(section, dict) or set(section) != {"success", "failure"}:
            raise OracleError(f"official {category} status is malformed")
        success, failure = section["success"], section["failure"]
        if (
            not isinstance(success, list)
            or not isinstance(failure, list)
            or any(not isinstance(case, str) for case in success + failure)
        ):
            raise OracleError(f"official {category} status is malformed")
        expected_cases = set(row[category])
        if (
            set(success) | set(failure) != expected_cases
            or set(success) & set(failure)
            or len(success) + len(failure) != len(expected_cases)
        ):
            raise OracleError(f"official {category} denominator differs from lock")
        if any(status_map[case] != "PASSED" for case in success) or any(
            status_map[case] == "PASSED" for case in failure
        ):
            raise OracleError(f"official {category} status disagrees with scorer log parse")
        counts[f"{category.lower()}_success"] = len(success)
        counts[f"{category.lower()}_failure"] = len(failure)
    resolved = instance["resolved"]
    if name == "gold" and (
        resolved is not True
        or counts["fail_to_pass_failure"] != 0
        or counts["pass_to_pass_failure"] != 0
    ):
        raise OracleError("gold official resolution differs from positive control")
    if name == "known_bad" and (resolved is not False or counts["fail_to_pass_failure"] < 1):
        raise OracleError("known-bad official resolution differs from negative control")
    return {
        "expected_tests": len(expected),
        "observed_tests": len(status_map),
        "resolved": resolved,
        **counts,
    }


def validate_empty(report: dict[str, Any]) -> dict[str, Any]:
    if (
        report.get("schema_version") != 2
        or report.get("submitted_instances") != 1
        or report.get("empty_patch_instances") != 1
        or report.get("empty_patch_ids") != [INSTANCE_ID]
        or report.get("completed_instances") != 0
        or report.get("resolved_instances") != 0
        or report.get("error_instances") != 0
    ):
        raise OracleError("official scorer did not classify empty patch as unscored")
    return {
        "classification": "official_empty_patch_unscored",
        "test_statuses": None,
        "resolved": None,
        "official_report_schema": 2,
    }


def run_oracle(
    *,
    assets_dir: Path,
    scorer_source: Path,
    scorer_python: Path,
    scorer_freeze: Path,
    seed_image_id: str,
    output_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not 60 <= timeout_seconds <= 3600:
        raise OracleError("case timeout must be between 60 and 3600 seconds")
    check_private_output_destination(output_dir)
    check_native_docker()
    row, paths, assets_manifest_sha256 = check_assets(assets_dir)
    check_source(scorer_source)
    scorer_freeze_sha256 = check_scorer(scorer_python, scorer_freeze, scorer_source)
    image_identity = check_images(seed_image_id)
    output_dir.mkdir(mode=0o700, parents=True)
    receipt: dict[str, Any] = {
        "schema_version": "axrun.swebench-django-native-oracle@1",
        "status": "incomplete",
        "instance_id": INSTANCE_ID,
        "dataset_commit": asset_lock.DATASET_COMMIT,
        "harness_commit": asset_lock.HARNESS_COMMIT,
        "row_sha256": asset_lock.ROW_SHA256,
        "assets_manifest_sha256": assets_manifest_sha256,
        "scorer_freeze_sha256": scorer_freeze_sha256,
        "official_source_image": OFFICIAL_SOURCE_IMAGE,
        **image_identity,
        "platform": "linux/amd64",
        "network": "none",
        "minimum_system_python": ".".join(map(str, MIN_SYSTEM_PYTHON)),
        "offline_pip_environment": {
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        },
        "docker_limits": {"cpus": 2, "memory": "4g", "pids": 256, "log_driver": "none"},
        "case_timeout_seconds": timeout_seconds,
        "official_run_instance_used": False,
        "official_test_spec_and_scorer_used": True,
        "empty_container_run_is_diagnostic_only": True,
        "cases": {},
    }
    receipt_path = output_dir / "receipt.json"
    receipt["seed_audit"] = audit_seed(seed_image_id)
    _write_receipt(receipt_path, receipt)
    for name in ("gold", "known_bad", "empty"):
        result = run_case(
            name, paths[name], paths["eval"], output_dir, seed_image_id, timeout_seconds
        )
        case_dir = output_dir / name
        scored = official_scorer(
            "empty" if name == "empty" else "grade",
            scorer_python,
            scorer_source,
            paths["row"],
            paths[name],
            case_dir / "test_output.txt",
            case_dir / "official_report.json",
        )
        result["official_summary"] = (
            validate_empty(scored) if name == "empty" else validate_grade(row, scored, name)
        )
        receipt["cases"][name] = result
        _write_receipt(receipt_path, receipt)
    receipt["status"] = "completed"
    _write_receipt(receipt_path, receipt)
    return {
        "instance_id": INSTANCE_ID,
        "status": "completed",
        "gold_resolved": True,
        "known_bad_resolved": False,
        "empty": "official_empty_patch_unscored",
        "receipt_sha256": digest(receipt_path.read_bytes()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--scorer-source", type=Path, required=True)
    parser.add_argument("--scorer-python", type=Path, required=True)
    parser.add_argument("--scorer-freeze", type=Path, required=True)
    parser.add_argument("--seed-image-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        result = run_oracle(
            assets_dir=args.assets_dir.absolute(),
            scorer_source=args.scorer_source.absolute(),
            scorer_python=args.scorer_python.absolute(),
            scorer_freeze=args.scorer_freeze.absolute(),
            seed_image_id=args.seed_image_id,
            output_dir=args.output_dir.absolute(),
            timeout_seconds=args.timeout_seconds,
        )
    except (OracleError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"oracle failed closed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
