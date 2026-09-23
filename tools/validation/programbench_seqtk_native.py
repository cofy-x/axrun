"""Bounded native qualification; never substitutes for public-SDK acceptance.

Run only through the registered Forge Linux profile. Official assets stay private
in the evidence directory. Two repetitions are declared before execution; every
result is retained and any discrepancy fails qualification.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

INSTANCE = "lh3__seqtk.94e7070"
BASE = (
    "docker.io/programbench/lh3_1776_seqtk.94e7070@"
    "sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0"
)
TEST_REV = "de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5"
PROGRAMBENCH_SHA = "963063c9271cc40fa179977356782ea4582e0b0c"
SOURCE_SHA = "94e707082d39b0a038f234df676e32d9802c0dc7"
SUBMISSION_SHA = "f43ff067bfcf052c8d3fa37cf7a580d65fde4d17"
BRANCHES = {
    "e592c32aec70": "3a9ba4e29bf1eed9cc80b8c8eab537af092fc0b559f8f05eac326b8f5a7943a0",
    "5d974fdda794": "b908e8eda5bdbb72b338c20a80ec7f18a086a92ee4f5e34a56b72303cb650d11",
}
CPU = "10"
MEMORY = "8g"
REPETITIONS = 2


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str, expected: str | None, target: Path) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024 or (expected and digest(data) != expected):
        raise ValueError(f"input integrity failure: {target.name}")
    target.write_bytes(data)
    return data


def run(args: list[str], log: Path, *, timeout: int = 900) -> str:
    started = time.monotonic()
    with log.open("wb") as stream:
        result = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    log.with_suffix(log.suffix + ".timing.json").write_text(
        json.dumps({"seconds": time.monotonic() - started, "exit_code": result.returncode})
    )
    if result.returncode:
        raise RuntimeError(f"command failed: {args[0]}; evidence: {log}")
    return log.read_text().strip()


def parse_tests(xml: bytes) -> dict[str, str]:
    result = {}
    for case in ET.fromstring(xml).iter("testcase"):
        name = ".".join(filter(None, [case.get("classname", ""), case.get("name", "")]))
        outcomes = {child.tag for child in case if child.tag in {"failure", "error", "skipped"}}
        if not name or len(outcomes) > 1:
            raise ValueError("invalid test result")
        result[name] = next(iter(outcomes), "passed")
    if not result:
        raise ValueError("empty test results")
    return result


def main() -> None:
    if os.uname().sysname != "Linux" or os.uname().machine != "x86_64":
        raise RuntimeError("native Linux amd64 required")
    os.umask(0o077)
    root = Path(__file__).resolve().parents[2]
    out = Path(tempfile.mkdtemp(prefix="seqtk-native.", dir="/data/forge-artifacts"))
    print(f"evidence={out}", flush=True)
    identity = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    receipt = {
        "axrun_sha": identity,
        "base": BASE,
        "cpu": CPU,
        "memory": MEMORY,
        "platform": "linux/amd64",
        "repetitions": REPETITIONS,
        "network": "none",
        "test_revision": TEST_REV,
        "programbench_sha": PROGRAMBENCH_SHA,
        "environment": {
            "PYTEST_XDIST_AUTO_NUM_WORKERS": CPU,
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTEST_ADDOPTS": "--max-worker-restart=4 --reruns=2 --reruns-delay=1",
        },
        "status": "started",
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2))
    inputs = out / "inputs"
    inputs.mkdir()
    tests = json.loads(
        download(
            f"https://raw.githubusercontent.com/facebookresearch/programbench/{PROGRAMBENCH_SHA}/"
            f"src/programbench/data/tasks/{INSTANCE}/tests.json",
            None,
            inputs / "tests.json",
        )
    )
    if set(tests["branches"]) != set(BRANCHES):
        raise ValueError("metadata branch drift")
    for branch, sha in BRANCHES.items():
        download(
            f"https://huggingface.co/datasets/programbench/ProgramBench-Tests/resolve/"
            f"{TEST_REV}/{INSTANCE}/tests/{branch}.tar.gz",
            sha,
            inputs / f"{branch}.tar.gz",
        )
    source = download(
        f"https://api.github.com/repos/lh3/seqtk/tarball/{SOURCE_SHA}",
        "db2126519e0f1a8ff7a924c11a575a5719e86690919238281736109410004157",
        inputs / "source.tar.gz",
    )
    reference = inputs / "reference-build"
    reference.mkdir()
    with tarfile.open(fileobj=io.BytesIO(source)) as archive:
        for member in archive:
            relative = Path(*Path(member.name).parts[1:])
            if relative == Path("."):
                continue
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("unsafe source archive")
            target = reference / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
                target.chmod(member.mode & 0o777)
    (reference / "compile.sh").write_text("#!/bin/sh\nset -eu\nmake\ncp seqtk executable\n")
    (reference / "compile.sh").chmod(0o755)
    partial = inputs / "partial.tar.gz"
    download(
        "https://huggingface.co/datasets/programbench/20260429_mini-v2.2.6_gpt-5-4/resolve/"
        f"23f521694f9f5f6310d736ff9a7af16cd4cb49ce/{INSTANCE}/submission.tar.gz",
        "e13533d16886d84814f3fe45975c8d255a7333f17028ca606da1e011e231cdaa",
        partial,
    )
    download(
        "https://raw.githubusercontent.com/ProgramBench/20260429_mini-v2.2.6_gpt-5-4/"
        f"{SUBMISSION_SHA}/{INSTANCE}/{INSTANCE}.eval.json",
        "d0e7b65c16e5709208d1cd1ae73b33f0d7475eb9cbc07c0d89d06c240bb782a5",
        inputs / "published-partial.json",
    )
    failure = inputs / "compile-failure"
    failure.mkdir()
    (failure / "compile.sh").write_text("#!/bin/sh\nexit 42\n")
    (failure / "compile.sh").chmod(0o755)
    for variant, directory in (("reference-build", reference), ("compile-failure", failure)):
        with tarfile.open(inputs / f"{variant}.tar.gz", "w:gz") as archive:
            for path in sorted(directory.rglob("*")):
                archive.add(path, arcname=str(path.relative_to(directory)), recursive=False)
    (out / "input-digests.json").write_text(
        json.dumps(
            {
                str(p.relative_to(inputs)): digest(p.read_bytes())
                for p in sorted(inputs.rglob("*"))
                if p.is_file()
            },
            indent=2,
        )
    )
    # The locked dependency closure is shared with the already qualified 1.2.4
    # evaluator. No packages are installed from the network during execution.
    build = out / "image"
    shutil.copytree(
        root / "fixtures/programbench/tty-clock-1.2.4-official/verifier", build / "verifier"
    )
    (build / "Dockerfile").write_text(
        f"FROM {BASE}\n"
        "COPY verifier/requirements.lock /opt/axrun-programbench/requirements.lock\n"
        "RUN python3 -m pip install --disable-pip-version-check --no-cache-dir --require-hashes "
        "-r /opt/axrun-programbench/requirements.lock\n"
        "COPY verifier/check_environment.py /opt/axrun-programbench/check_environment.py\n"
        "RUN python3 /opt/axrun-programbench/check_environment.py\n"
    )
    tag = "axrun/seqtk-native:" + out.name.split(".")[-1]
    run(
        ["docker", "build", "--platform", "linux/amd64", "-t", tag, str(build)],
        out / "build.log",
        timeout=1800,
    )
    receipt["image_inspect"] = json.loads(
        run(["docker", "image", "inspect", tag], out / "image.json")
    )
    all_results = {}
    owned = set()
    compiled_images = []
    try:
        for repeat in range(1, REPETITIONS + 1):
            for variant in ("reference-build", "partial", "compile-failure"):
                result_dir = out / f"{variant}-{repeat}"
                result_dir.mkdir()
                name = f"{out.name}-{variant}-{repeat}"
                options = [
                    "--platform",
                    "linux/amd64",
                    "--network",
                    "none",
                    "--cpus",
                    CPU,
                    "--memory",
                    MEMORY,
                    "--workdir",
                    "/workspace",
                ]
                for key, value in receipt["environment"].items():
                    options.extend(["--env", f"{key}={value}"])
                compile_cmd = (
                    "find /workspace -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; "
                    "tar -xzf /input.tar.gz -C /workspace; rm -f /workspace/executable; "
                    "git -c init.defaultBranch=gold init -q; git add -A; "
                    "GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z "
                    "git -c user.email=gold@local -c user.name=gold -c commit.gpgsign=false "
                    "commit -q --allow-empty -m gold; chmod +x compile.sh; ./compile.sh; "
                    "test -f executable; test -x executable; "
                    "mv executable /opt/programbench-stashed-executable-do-not-modify; "
                    "sha256sum /opt/programbench-stashed-executable-do-not-modify"
                )
                run(
                    [
                        "docker",
                        "create",
                        "--name",
                        name,
                        *options,
                        "--entrypoint",
                        "/bin/sh",
                        tag,
                        "-ec",
                        compile_cmd,
                    ],
                    result_dir / "create.log",
                )
                owned.add(name)
                run(
                    ["docker", "cp", str(inputs / f"{variant}.tar.gz"), name + ":/input.tar.gz"],
                    result_dir / "copy.log",
                )
                # Start detached, then a bounded wait; timeout cleanup removes only owned names.
                run(["docker", "start", name], result_dir / "start.log")
                code = int(run(["docker", "wait", name], result_dir / "wait.log"))
                run(["docker", "logs", name], result_dir / "compile.log")
                if variant == "compile-failure":
                    if code != 42:
                        raise ValueError("compile-failure fixture did not fail with 42")
                    all_results[f"{variant}-{repeat}"] = {"compile_exit": code, "tests": {}}
                    run(["docker", "rm", name], result_dir / "remove.log")
                    owned.remove(name)
                    continue
                if code:
                    raise ValueError(f"unexpected compile failure: {variant}")
                compiled = run(["docker", "commit", name], result_dir / "compiled-image.log")
                compiled_images.append(compiled)
                run(["docker", "rm", name], result_dir / "remove.log")
                owned.remove(name)
                result_map = {}
                for branch in BRANCHES:
                    branch_name = name + "-" + branch
                    command = (
                        "tar -xzf /tests.tar.gz -C /workspace; "
                        "mv /opt/programbench-stashed-executable-do-not-modify executable; "
                        "rm -f eval/results.xml; "
                        # Exactly the timeout-method adaptation in official 1.2.4 eval.py.
                        "sed -i 's/--timeout-method=thread/--timeout-method=signal/g' eval/run.sh; "
                        "chmod +x eval/run.sh; ./eval/run.sh"
                    )
                    run(
                        [
                            "docker",
                            "create",
                            "--name",
                            branch_name,
                            *options,
                            "--entrypoint",
                            "/bin/sh",
                            compiled,
                            "-ec",
                            command,
                        ],
                        result_dir / f"{branch}-create.log",
                    )
                    owned.add(branch_name)
                    run(
                        [
                            "docker",
                            "cp",
                            str(inputs / f"{branch}.tar.gz"),
                            branch_name + ":/tests.tar.gz",
                        ],
                        result_dir / f"{branch}-copy.log",
                    )
                    run(["docker", "start", branch_name], result_dir / f"{branch}-start.log")
                    code = int(
                        run(
                            ["docker", "wait", branch_name],
                            result_dir / f"{branch}-wait.log",
                            timeout=3600,
                        )
                    )
                    run(["docker", "logs", branch_name], result_dir / f"{branch}.log")
                    if code not in (0, 1):
                        raise ValueError("evaluator invocation failed")
                    xml = result_dir / f"{branch}.xml"
                    run(
                        ["docker", "cp", branch_name + ":/workspace/eval/results.xml", str(xml)],
                        result_dir / f"{branch}-result.log",
                    )
                    observed = parse_tests(xml.read_bytes())
                    metadata = tests["branches"][branch]
                    ignored = {item["name"] for item in metadata["ignored_tests"]}
                    expected = set(metadata["tests"])
                    if not expected <= observed.keys() or not observed.keys() <= expected:
                        raise ValueError("test inventory mismatch; not a candidate score")
                    result_map.update(
                        {
                            f"{branch}/{key}": value
                            for key, value in observed.items()
                            if key not in ignored
                        }
                    )
                    run(["docker", "rm", branch_name], result_dir / f"{branch}-remove.log")
                    owned.remove(branch_name)
                value = {
                    "compile_exit": 0,
                    "executable": (result_dir / "compile.log").read_text().splitlines()[-1],
                    "tests": result_map,
                }
                (result_dir / "result.json").write_text(json.dumps(value, indent=2))
                all_results[f"{variant}-{repeat}"] = value
                print(
                    f"completed={variant}-{repeat} "
                    f"passed={sum(v == 'passed' for v in result_map.values())} "
                    f"total={len(result_map)}",
                    flush=True,
                )
        for variant in ("reference-build", "partial", "compile-failure"):
            if all_results[f"{variant}-1"] != all_results[f"{variant}-2"]:
                raise ValueError(f"native repeatability mismatch: {variant}")
        if any(v != "passed" for v in all_results["reference-build-1"]["tests"].values()):
            raise ValueError("reference build does not pass all active tests")
        published = json.loads((inputs / "published-partial.json").read_text())
        historical = {f"{r['branch']}/{r['name']}": r["status"] for r in published["test_results"]}
        current = all_results["partial-1"]["tests"]
        differences = {
            k: {"published": historical.get(k), "native": v}
            for k, v in current.items()
            if historical.get(k) != v
        }
        (out / "published-comparison.json").write_text(json.dumps(differences, indent=2))
        if differences:
            raise ValueError("native results differ from published active-test projection")
        receipt["status"] = "native_repetition_passed"
    finally:
        cleanup_errors = []
        for name in sorted(owned):
            if subprocess.run(["docker", "rm", "-f", name], capture_output=True).returncode:
                cleanup_errors.append(name)
        for image in compiled_images:
            if subprocess.run(["docker", "image", "rm", image], capture_output=True).returncode:
                cleanup_errors.append(image)
        receipt["cleanup_errors"] = cleanup_errors
        (out / "results.json").write_text(json.dumps(all_results, indent=2))
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2))
        if cleanup_errors:
            raise RuntimeError("owned resource cleanup failed; see receipt")


if __name__ == "__main__":
    main()
