"""Bounded released-Axern acceptance for the locked ProgramBench seqtk case.

This consumes the immutable evidence produced by ``programbench_seqtk_native.py``.
It deliberately uses only the released ``axern-sdk`` and Axrun's public CLI.  The
caller must choose the repeat count before execution; all repetitions are kept.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from axern_sdk import AxernClient
from google.protobuf.json_format import MessageToDict

INSTANCE = "lh3__seqtk.94e7070"
SDK_VERSION = "0.11.3"
TASK_DIGEST = "sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0"
VARIANTS = ("reference-build", "partial", "compile-failure")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _message(value: Any) -> dict[str, Any]:
    return MessageToDict(value, preserving_proto_field_name=True)


def _record(output: Path, name: str, value: object) -> None:
    (output / f"{name}.json").write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _command(repo: Path, output: Path, label: str, args: list[str], timeout: int = 2400) -> None:
    with (output / f"{label}.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            args,
            cwd=repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=True,
        )


def _extract_locked_candidate(source: Path, destination: Path) -> None:
    """Extract a digest-verified native input without accepting links or traversal."""
    destination.mkdir(parents=True)
    root = destination.resolve()
    with tarfile.open(source, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > 10_000:
            raise ValueError("candidate archive has too many entries")
        total = 0
        names: set[str] = set()
        for member in members:
            name = PurePosixPath(member.name)
            if (
                not member.name
                or name.is_absolute()
                or ".." in name.parts
                or "." in name.parts
                or name.as_posix() != member.name
                or member.name in names
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("candidate archive contains an unsafe entry")
            names.add(member.name)
            total += member.size
            if total > 512 << 20:
                raise ValueError("candidate archive exceeds the extracted size limit")
            target = (root / member.name).resolve(strict=False)
            if not target.is_relative_to(root):
                raise ValueError("candidate archive escapes its destination")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(member.mode & 0o777)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("candidate archive payload is missing")
            with target.open("wb") as writer:
                shutil.copyfileobj(stream, writer, length=1024 * 1024)
            target.chmod(member.mode & 0o777)


def _test_map(details: dict[str, Any]) -> dict[str, str]:
    return {f"{row['branch']}/{row['name']}": row["status"] for row in details["tests"]}


def _status_name(run: Any) -> str:
    field = run.DESCRIPTOR.fields_by_name["status"]
    return str(field.enum_type.values_by_number[int(run.status)].name)


def _isolation_run(
    client: AxernClient,
    output: Path,
    active_runs: set[str],
    environment_id: str,
    label: str,
    code: str,
) -> None:
    run = client.create_run(
        environment_id=environment_id,
        argv=["python3", "-c", code],
        request_cpu="100m",
        request_memory="512MiB",
    )
    active_runs.add(run.id)
    _record(output, f"{label}-created", _message(run))
    terminal = client.wait_run(run.id, timeout=180)
    _record(output, label, _message(terminal))
    if _status_name(terminal) != "RUN_STATUS_SUCCEEDED" or terminal.exit_code != 0:
        raise AssertionError(f"fresh isolation probe failed: {label}")
    active_runs.remove(run.id)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--native-evidence", type=Path, required=True)
    parser.add_argument("--context-file", type=Path, required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--verification-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, choices=range(1, 4), required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = args.repo.resolve()
    fixture = repo / "fixtures/programbench/seqtk-1.2.4-official"
    native = args.native_evidence.resolve()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    if importlib.metadata.version("axern-sdk") != SDK_VERSION:
        raise RuntimeError(f"released axern-sdk=={SDK_VERSION} is required")
    if not args.runtime_image.endswith(f"@{TASK_DIGEST}"):
        raise ValueError("runtime image must be the locked linux/amd64 platform digest")
    if "@sha256:" not in args.verification_image:
        raise ValueError("verification image must be content-addressed")

    receipt = json.loads((native / "receipt.json").read_text(encoding="utf-8"))
    if (
        receipt["status"] != "native_repetition_passed"
        or receipt["cleanup_errors"] != []
        or receipt["repetitions"] != args.repetitions
        or receipt["platform"] != "linux/amd64"
        or not receipt["base"].endswith(f"@{TASK_DIGEST}")
    ):
        raise ValueError("native evidence does not match the declared acceptance contract")
    digests = json.loads((native / "input-digests.json").read_text(encoding="utf-8"))
    for name, expected in digests.items():
        if _sha256(native / "inputs" / name) != expected:
            raise ValueError(f"native input digest mismatch: {name}")

    inputs = output / "seqtk-inputs"
    assets = inputs / "assets" / INSTANCE / "tests"
    assets.mkdir(parents=True)
    lock = json.loads((fixture / "asset-lock.json").read_text(encoding="utf-8"))
    for branch in lock["test_blobs"]["branches"]:
        shutil.copyfile(native / "inputs" / f"{branch}.tar.gz", assets / f"{branch}.tar.gz")
    for variant in VARIANTS:
        _extract_locked_candidate(native / "inputs" / f"{variant}.tar.gz", inputs / variant)

    axrun_sha = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    _record(
        output,
        "acceptance-plan",
        {
            "axern_sdk": SDK_VERSION,
            "axrun_sha": axrun_sha,
            "context": args.context,
            "native_evidence": str(native),
            "repetitions": args.repetitions,
            "runtime_image": args.runtime_image,
            "verification_image": args.verification_image,
            "variants": list(VARIANTS),
        },
    )

    client = AxernClient.from_context(str(args.context_file), args.context)
    environments: list[str] = []
    active_runs: set[str] = set()
    failures: list[dict[str, object]] = []
    completed: list[dict[str, object]] = []
    try:
        inference = client.create_environment(image_ref=args.runtime_image)
        environments.append(inference.id)
        _record(output, "environment", _message(inference))
        verification = client.create_environment(image_ref=args.verification_image)
        environments.append(verification.id)
        _record(output, "verification-environment", _message(verification))
        for repetition in range(1, args.repetitions + 1):
            for variant in VARIANTS:
                label = f"{variant}-{repetition}"
                episode_id = f"{output.name}-{label}"
                state = output / f"state-{label}"
                episode = output / f"{label}.episode.json"
                base = [
                    sys.executable,
                    "-m",
                    "axrun.cli",
                    "--context-file",
                    str(args.context_file),
                    "--context",
                    args.context,
                    "--state-dir",
                    str(state),
                ]
                execution_started = False
                try:
                    _command(
                        repo,
                        output,
                        f"{label}-resolve",
                        [
                            *base,
                            "resolve-programbench-official",
                            str(fixture / "row.json"),
                            "--episode-id",
                            episode_id,
                            "--test-assets-dir",
                            str(inputs / "assets"),
                            "--static-candidate-directory",
                            str(inputs / variant),
                            "--runtime-image",
                            args.runtime_image,
                            "--inference-environment",
                            inference.id,
                            "--verification-image",
                            args.verification_image,
                            "--verification-environment",
                            verification.id,
                            "--output",
                            str(episode),
                        ],
                    )
                    execution_started = True
                    _command(repo, output, f"{label}-run", [*base, "run", str(episode)])
                    detail_paths = list(
                        (state / "verification-details").glob("sha256/*/programbench.json")
                    )
                    execution_paths = list((state / "verifications").glob("*/execution.json"))
                    if len(detail_paths) != 1 or len(execution_paths) != 1:
                        raise AssertionError("acceptance output is incomplete")
                    details = json.loads(detail_paths[0].read_text(encoding="utf-8"))
                    execution = json.loads(execution_paths[0].read_text(encoding="utf-8"))
                    expected_cleanup = (
                        "not_created" if variant == "compile-failure" else "completed"
                    )
                    if execution["cleanup_state"] != expected_cleanup:
                        raise AssertionError("derived Environment cleanup is incomplete")
                    compile_run = client.get_run(execution["compile"]["execution"]["run_id"])
                    if variant == "compile-failure":
                        if not (
                            details["compile_error"] == "compile_failed"
                            and details["not_run"] == 429
                            and not execution["derived_environment_id"]
                            and not compile_run.rootfs_snapshot.environment_id
                            and all(
                                step["execution"] is None for step in execution["branches"].values()
                            )
                        ):
                            raise AssertionError(
                                "compile failure acquired a score or derived state"
                            )
                    else:
                        native_result = json.loads(
                            (native / label / "result.json").read_text(encoding="utf-8")
                        )
                        expected_tests = native_result["tests"]
                        observed_tests = _test_map(details)
                        differences = {
                            key: {
                                "native": expected_tests.get(key),
                                "axern": observed_tests.get(key),
                            }
                            for key in expected_tests.keys() | observed_tests.keys()
                            if expected_tests.get(key) != observed_tests.get(key)
                        }
                        _record(output, f"{label}-comparison", differences)
                        if differences:
                            raise AssertionError("native and Axern per-test results differ")
                        executable = native_result["executable"].split()[0]
                        if details["executable_sha256"] != executable:
                            raise AssertionError("native and Axern executable hashes differ")
                        snapshot = client.wait_rootfs_snapshot(compile_run.id, timeout=120)
                        _record(output, f"{label}-rootfs", _message(snapshot))
                        if snapshot.environment_id != execution["derived_environment_id"]:
                            raise AssertionError("rootfs result and execution record disagree")
                        allocations = [
                            step["execution"]["allocation_id"]
                            for step in execution["branches"].values()
                        ]
                        if len(allocations) != len(set(allocations)) or len(allocations) != 2:
                            raise AssertionError("branches did not receive fresh Allocations")
                        if variant == "reference-build" and repetition == 1:
                            isolated = client.create_environment(image_ref=snapshot.image_ref)
                            environments.append(isolated.id)
                            _record(output, "isolation-environment", _message(isolated))
                            _isolation_run(
                                client,
                                output,
                                active_runs,
                                isolated.id,
                                "fresh-one",
                                "from pathlib import Path; "
                                "assert not Path('/opt/seqtk-probe').exists(); "
                                "Path('/opt/seqtk-probe').write_text('private')",
                            )
                            _isolation_run(
                                client,
                                output,
                                active_runs,
                                isolated.id,
                                "fresh-two",
                                "from pathlib import Path; "
                                "assert not Path('/opt/seqtk-probe').exists()",
                            )
                    evidence: dict[str, Any] = {"record": execution, "runs": {}}
                    for step in [execution["compile"], *execution["branches"].values()]:
                        ref = step.get("execution")
                        if ref:
                            evidence["runs"][ref["run_id"]] = _message(
                                client.get_run(ref["run_id"])
                            )
                    _record(output, f"{label}-execution", evidence)
                    completed.append(
                        {
                            "label": label,
                            "passed": details["passed"],
                            "failed": details["failed"],
                            "not_run": details["not_run"],
                            "score": details["score"],
                            "resolved": details["resolved"],
                            "executable_sha256": details.get("executable_sha256", ""),
                        }
                    )
                except (
                    subprocess.SubprocessError,
                    RuntimeError,
                    AssertionError,
                    ValueError,
                ) as exc:
                    failures.append(
                        {"label": label, "error_type": type(exc).__name__, "message": str(exc)}
                    )
                    if execution_started:
                        _command(
                            repo,
                            output,
                            f"{label}-cancel",
                            [*base, "cancel", episode_id],
                            timeout=120,
                        )
                    break
            if failures:
                break
        _record(
            output,
            "summary",
            {"completed": completed, "failures": failures, "native_sdk_parity": not failures},
        )
        if failures:
            raise RuntimeError("seqtk acceptance incomplete; inspect the recorded evidence")
    finally:
        cleanup: list[dict[str, str]] = []
        for run_id in sorted(active_runs):
            try:
                client.cancel_run(run_id)
            except Exception as exc:  # cleanup evidence must survive SDK-specific failures
                cleanup.append({"run_id": run_id, "error_type": type(exc).__name__})
        for environment_id in reversed(environments):
            try:
                client.delete_environment(environment_id)
            except Exception as exc:  # cleanup evidence must survive SDK-specific failures
                cleanup.append({"environment_id": environment_id, "error_type": type(exc).__name__})
        _record(output, "cleanup", {"errors": cleanup, "environments": environments})
        client.close()
        if cleanup:
            raise RuntimeError("owned SDK resources require cleanup; inspect cleanup.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
