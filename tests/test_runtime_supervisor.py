from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest

from axrun.errors import ContractError
from axrun.fixtures.claude.runtime_supervisor import supervise
from axrun.progress.schema import progress_snapshot_from_bytes, runtime_progress_from_bytes
from axrun.trajectories.schema import TrajectoryContractError

FIXTURES = Path(__file__).parent / "fixtures" / "claude-code-2.1.205"
STREAM_FIXTURE = (
    "import pathlib,sys,time;"
    "lines=pathlib.Path(sys.argv[1]).read_bytes().splitlines(keepends=True);"
    "[(sys.stdout.buffer.write(line),sys.stdout.buffer.flush(),time.sleep(0.03)) "
    "for line in lines];"
    "raise SystemExit(int(sys.argv[2]))"
)


@pytest.mark.parametrize(("name", "child_exit"), [("success", 0), ("error", 1)])
def test_supervisor_incrementally_publishes_safe_progress(
    tmp_path: Path, name: str, child_exit: int
) -> None:
    progress = tmp_path / "run" / "progress.json"
    trajectory = tmp_path / "outputs" / "trajectory.jsonl"
    usage = tmp_path / "outputs" / "usage.json"
    errors: list[BaseException] = []

    def run() -> None:
        try:
            exit_code = supervise(
                command=[
                    sys.executable,
                    "-c",
                    STREAM_FIXTURE,
                    str(FIXTURES / f"{name}.native.jsonl"),
                    str(child_exit),
                ],
                prompt_path=FIXTURES / f"{name}.prompt.txt",
                native_path=tmp_path / "run" / "raw.jsonl",
                trajectory_path=trajectory,
                usage_path=usage,
                progress_path=progress,
                harness_log_path=tmp_path / "outputs" / "harness.log",
                secrets=("CREDENTIAL-HEADER-MARKER-MUST-DISAPPEAR",),
                heartbeat_seconds=0.01,
            )
            assert exit_code == 0
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    revisions: set[int] = set()
    while thread.is_alive():
        if progress.exists():
            with suppress(OSError, ContractError):
                revisions.add(runtime_progress_from_bytes(progress.read_bytes()).revision)
        time.sleep(0.005)
    thread.join()

    assert errors == []
    assert len(revisions) >= 3
    final = runtime_progress_from_bytes(progress.read_bytes())
    assert final.process_alive is False
    assert final.native_event_count > 0
    assert final.canonical_event_count > 0
    assert trajectory.read_bytes() == (FIXTURES / f"{name}.canonical.jsonl").read_bytes()
    assert usage.read_bytes() == (FIXTURES / f"{name}.usage.json").read_bytes()
    safe_payload = progress.read_text()
    for marker in (
        "RAW-THINKING-MARKER-MUST-DISAPPEAR",
        "RAW-SIGNATURE-MARKER-MUST-DISAPPEAR",
        "CREDENTIAL-HEADER-MARKER-MUST-DISAPPEAR",
        "axrun-local-tunnel",
    ):
        assert marker not in safe_payload


def test_supervisor_rejects_partial_json_without_emitting_a_partial_event(
    tmp_path: Path,
) -> None:
    native = tmp_path / "partial.native.jsonl"
    init = (FIXTURES / "success.native.jsonl").read_bytes().splitlines(keepends=True)[0]
    native.write_bytes(init + b'{"type":"assistant","message":')

    with pytest.raises(TrajectoryContractError, match="invalid JSON"):
        supervise(
            command=[sys.executable, "-c", STREAM_FIXTURE, str(native), "0"],
            prompt_path=FIXTURES / "success.prompt.txt",
            native_path=tmp_path / "run" / "raw.jsonl",
            trajectory_path=tmp_path / "outputs" / "trajectory.jsonl",
            usage_path=tmp_path / "outputs" / "usage.json",
            progress_path=tmp_path / "run" / "progress.json",
            harness_log_path=tmp_path / "outputs" / "harness.log",
            heartbeat_seconds=0.01,
        )

    lines = (tmp_path / "outputs" / "trajectory.jsonl").read_bytes().splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["kind"] in {"session_start", "context"} for line in lines)


def test_caller_progress_parser_rejects_runtime_shape() -> None:
    payload = (
        FIXTURES / "success.native.jsonl"
    ).read_bytes()  # raw provider data is never a caller progress contract
    with pytest.raises(ContractError):
        progress_snapshot_from_bytes(payload)
