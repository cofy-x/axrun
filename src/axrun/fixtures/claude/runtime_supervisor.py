"""Allocation-local Claude supervisor with incremental safe progress."""

from __future__ import annotations

import argparse
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from axrun.progress.schema import (
    RUNTIME_PROGRESS_FORMAT,
    RuntimeProgress,
    canonical_progress_bytes,
)
from axrun.trajectories.adapters.claude_code import (
    ClaudeTrajectoryNormalizer,
    claude_stage_exit_code,
)
from axrun.trajectories.schema import canonical_event_bytes

_TOOL_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


def supervise(
    *,
    command: list[str],
    prompt_path: Path,
    native_path: Path,
    trajectory_path: Path,
    usage_path: Path,
    progress_path: Path,
    harness_log_path: Path,
    secrets: tuple[str, ...] = (),
    heartbeat_seconds: float = 1.0,
) -> int:
    if not command:
        raise ValueError("Claude supervisor command is required")
    for path in (
        native_path,
        trajectory_path,
        usage_path,
        progress_path,
        harness_log_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    normalizer = ClaudeTrajectoryNormalizer(
        prompt_path.read_text(encoding="utf-8"), secrets=secrets
    )
    revision = 0
    latest_event_kind = ""
    latest_tool_name = ""
    last_agent_activity_at = ""
    process_alive = False

    def publish() -> None:
        nonlocal revision
        revision += 1
        snapshot = RuntimeProgress(
            schema_version=1,
            format=RUNTIME_PROGRESS_FORMAT,
            revision=revision,
            updated_at=_now(),
            process_alive=process_alive,
            native_event_count=normalizer.native_event_count,
            canonical_event_count=normalizer.canonical_event_count,
            latest_event_kind=latest_event_kind,
            latest_tool_name=latest_tool_name,
            trajectory_bytes=normalizer.canonical_bytes,
            usage_bytes=len(normalizer.usage_bytes),
            last_agent_activity_at=last_agent_activity_at,
        )
        _atomic_write(progress_path, canonical_progress_bytes(snapshot))

    publish()
    lines: queue.Queue[bytes | None] = queue.Queue(maxsize=16)
    with (
        prompt_path.open("rb") as prompt,
        native_path.open("wb", buffering=0) as native,
        trajectory_path.open("wb", buffering=0) as trajectory,
        harness_log_path.open("wb", buffering=0) as harness_log,
    ):
        process = subprocess.Popen(
            command,
            stdin=prompt,
            stdout=subprocess.PIPE,
            stderr=harness_log,
            close_fds=True,
        )
        process_alive = True
        publish()
        stdout = process.stdout
        assert stdout is not None

        def read_stdout() -> None:
            try:
                for raw_line in stdout:
                    lines.put(raw_line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_stdout, name="claude-stream-reader", daemon=True)
        reader.start()
        last_heartbeat = time.monotonic()
        try:
            while True:
                timeout = max(0.05, heartbeat_seconds - (time.monotonic() - last_heartbeat))
                try:
                    raw_line = lines.get(timeout=timeout)
                except queue.Empty:
                    publish()
                    last_heartbeat = time.monotonic()
                    continue
                if raw_line is None:
                    break
                native.write(raw_line)
                emitted = normalizer.feed_native_line(raw_line)
                last_agent_activity_at = _now()
                for event in emitted:
                    trajectory.write(canonical_event_bytes(event) + b"\n")
                    latest_event_kind = event.kind
                    if event.kind == "tool_call":
                        raw_name = event.data.get("name")
                        latest_tool_name = (
                            raw_name
                            if isinstance(raw_name, str) and _TOOL_NAME.fullmatch(raw_name)
                            else "unknown"
                        )
                _atomic_write(usage_path, normalizer.usage_bytes)
                publish()
                last_heartbeat = time.monotonic()
            agent_exit_code = process.wait()
            reader.join(timeout=5.0)
            normalizer.finalize()
            _atomic_write(usage_path, normalizer.usage_bytes)
            os.fsync(native.fileno())
            os.fsync(trajectory.fileno())
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)
            raise
        finally:
            process_alive = False
            publish()
    return claude_stage_exit_code(native_path, agent_exit_code)


def _atomic_write(path: Path, payload: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--usage", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--harness-log", type=Path, required=True)
    parser.add_argument("--redact-value", action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    return supervise(
        command=command,
        prompt_path=args.prompt,
        native_path=args.native,
        trajectory_path=args.trajectory,
        usage_path=args.usage,
        progress_path=args.progress,
        harness_log_path=args.harness_log,
        secrets=tuple(args.redact_value),
    )


if __name__ == "__main__":
    raise SystemExit(main())
