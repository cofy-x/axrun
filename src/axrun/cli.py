"""Command line entrypoint for the recoverable Axern episode runner."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from axern_sdk import AxernError

from axrun.adapters import (
    CommandVerifierAdapter,
    StaticPatchAdapter,
    SweBenchVerifiedVerifierAdapter,
    SyntheticVerifierAdapter,
)
from axrun.adapters._candidate import load_candidate
from axrun.adapters.base import InferenceAdapter, VerifierAdapter
from axrun.axern_backend import AxernBackend
from axrun.datasets import SweBenchVerifiedResolver, SyntheticCodeTaskResolver
from axrun.errors import AxrunError, ContractError
from axrun.harnesses import ClaudeCodeHarness
from axrun.lifecycle.base import CompositePreStartLifecycle, PreStartLifecycle
from axrun.lifecycle.model_tunnel import ModelTunnelLifecycle
from axrun.lifecycle.stage_progress import StageProgressObserver
from axrun.models import (
    EpisodePhase,
    HarnessSpec,
    ResolvedEpisode,
    canonical_json,
    resolved_episode_from_dict,
)
from axrun.progress.store import ProgressStore
from axrun.proxy.model import ModelProxy
from axrun.proxy.protocols import AnthropicProtocol
from axrun.qualification import qualify_episode
from axrun.report import canonical_report_json, report_markdown, verify_record
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore
from axrun.trajectories.adapters import ClaudeCodeTrajectoryAdapter
from axrun.trajectories.bundle import load_trajectory_bundle


def _episode(path: Path) -> ResolvedEpisode:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractError("ResolvedEpisode must be a JSON object")
    return resolved_episode_from_dict(cast(dict[str, Any], raw))


def _adapters(
    episode: ResolvedEpisode,
) -> tuple[InferenceAdapter, VerifierAdapter]:
    if episode.harness.identity == "static-patch":
        inference: InferenceAdapter = StaticPatchAdapter(version=episode.harness.version)
    elif episode.harness.identity == "claude-code":
        inference = ClaudeCodeHarness(version=episode.harness.version)
    else:
        raise ContractError(f"unsupported harness adapter: {episode.harness.identity}")
    if episode.verifier.identity == "synthetic-code-task":
        verifier: VerifierAdapter = SyntheticVerifierAdapter(
            version=episode.verifier.version,
            timeout_seconds=episode.verifier.timeout_seconds,
        )
    elif episode.verifier.identity == "swebench-verified":
        verifier = SweBenchVerifiedVerifierAdapter(
            version=episode.verifier.version,
            timeout_seconds=episode.verifier.timeout_seconds,
        )
    elif episode.verifier.identity == "command-verifier":
        command_value = episode.verifier.config.get("command", ["/opt/axrun/run-verifier"])
        if not _is_string_array(command_value):
            raise ContractError("verifier command must be a non-empty string array")
        verifier = CommandVerifierAdapter(
            command=tuple(cast(list[str], command_value)),
            version=episode.verifier.version,
            timeout_seconds=episode.verifier.timeout_seconds,
            name=episode.verifier.identity,
        )
    else:
        raise ContractError(f"unsupported verifier adapter: {episode.verifier.identity}")
    return inference, verifier


def _is_string_array(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item) for item in cast(list[object], value)
    )


def _trajectory_adapter(episode: ResolvedEpisode) -> ClaudeCodeTrajectoryAdapter | None:
    if episode.harness.identity == "claude-code":
        return ClaudeCodeTrajectoryAdapter(version=episode.harness.version)
    return None


def _client(args: argparse.Namespace) -> Any:
    from axern_sdk import AxernClient

    if args.context_file:
        return AxernClient.from_context(args.context_file, args.context)
    return AxernClient.from_env()


def _runner(args: argparse.Namespace, client: Any) -> EpisodeRunner:
    return EpisodeRunner(
        backend=AxernBackend(client, namespace=args.namespace),
        store=EpisodeStore(args.state_dir),
    )


def _model_lifecycle(
    args: argparse.Namespace,
    client: Any,
    episode: ResolvedEpisode,
    store: EpisodeStore,
) -> PreStartLifecycle | None:
    if episode.harness.identity != "claude-code":
        return None
    upstream_url = args.model_upstream_url or os.environ.get("AXRUN_MODEL_UPSTREAM_URL", "")
    credential_env = args.model_credential_env
    credential = os.environ.get(credential_env, "")
    if not upstream_url or not credential:
        raise ContractError(
            "Claude Code requires --model-upstream-url (or AXRUN_MODEL_UPSTREAM_URL) "
            f"and a credential in {credential_env}"
        )
    proxy = ModelProxy(
        upstream_url=upstream_url,
        credential=credential,
        protocol=AnthropicProtocol(),
        connect_timeout_seconds=args.model_connect_timeout_seconds,
        read_timeout_seconds=args.model_response_timeout_seconds,
    )
    model = episode.harness.config.get("model")
    if not isinstance(model, str) or not model:
        raise ContractError("Claude Code requires a non-empty model")
    tunnel = ModelTunnelLifecycle(client=client, proxy=proxy, model=model)
    observer = StageProgressObserver(
        episode_id=episode.episode_id,
        store=store,
        proxy=proxy,
    )
    return CompositePreStartLifecycle(tunnel, observer)


def _print(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, indent=2))


def _status(store: EpisodeStore, episode_id: str) -> dict[str, Any]:
    record = store.load(episode_id)
    if record is None:
        raise ContractError(f"episode record does not exist: {episode_id}")
    value: dict[str, Any] = {
        "episode_id": record.episode_id,
        "phase": record.phase,
        "inference_run_id": record.inference.run_id if record.inference else "",
        "verification_run_id": record.verification.run_id if record.verification else "",
        "trajectory_manifest": record.trajectory_manifest,
        "trajectory_digest": record.trajectory_digest,
        "diagnostic_code": record.diagnostic_code,
        "message": record.message,
        "progress_revision": record.progress_revision,
    }
    progress = _load_progress(store, record.episode_id, record.progress_path)
    if progress is not None:
        value["progress"] = progress.as_dict()
    if record.phase == EpisodePhase.COMPLETED:
        result = store.load_result(record.verification_result, record.verification_result_digest)
        value.update(verdict=result.verdict, score=result.score)
    return value


def _load_progress(store: EpisodeStore, episode_id: str, recorded_path: str):
    if not recorded_path:
        return None
    progress_store = ProgressStore(store.root)
    if Path(recorded_path) != progress_store.path_for(episode_id):
        raise ContractError("episode progress path is not canonical")
    return progress_store.load(episode_id)


def _export(store: EpisodeStore, episode_id: str, destination: Path) -> Path:
    record = store.load(episode_id)
    if record is None:
        raise ContractError(f"episode record does not exist: {episode_id}")
    if record.phase != EpisodePhase.COMPLETED:
        raise ContractError(f"episode is not complete: {record.phase.value}")
    candidate = load_candidate(Path(record.candidate_manifest))
    trajectory = (
        load_trajectory_bundle(Path(record.trajectory_manifest))
        if record.trajectory_manifest
        else None
    )
    result = store.load_result(record.verification_result, record.verification_result_digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ContractError(f"export destination already exists: {destination}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        shutil.copytree(Path(record.candidate_manifest).parent, temporary / "candidate")
        if trajectory is not None:
            shutil.copytree(Path(record.trajectory_manifest).parent, temporary / "trajectory")
        (temporary / "verification-result.json").write_text(
            json.dumps(asdict(result), sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        (temporary / "export.json").write_text(
            json.dumps(
                {
                    "episode_id": episode_id,
                    "candidate_digest": candidate.digest,
                    "trajectory_digest": trajectory.digest if trajectory is not None else "",
                    "verification_result_digest": record.verification_result_digest,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axrun")
    parser.add_argument("--state-dir", type=Path, default=Path(".axrun"))
    parser.add_argument("--context-file", default="")
    parser.add_argument("--context", default="")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--model-upstream-url", default="")
    parser.add_argument("--model-credential-env", default="AXRUN_MODEL_CREDENTIAL")
    parser.add_argument("--model-connect-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--model-response-timeout-seconds", type=float, default=300.0)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a ResolvedEpisode JSON file")
    validate.add_argument("episode", type=Path)
    resolve = commands.add_parser(
        "resolve-synthetic", help="resolve one explicit Axrun synthetic dataset row"
    )
    resolve.add_argument("row", type=Path)
    resolve.add_argument("--episode-id", required=True)
    resolve.add_argument(
        "--harness", choices=("static-patch", "claude-code"), default="static-patch"
    )
    resolve.add_argument("--candidate-file", default="")
    _add_claude_arguments(resolve)
    resolve.add_argument("--inference-environment", required=True)
    resolve.add_argument("--verification-environment", required=True)
    resolve.add_argument("--output", type=Path, required=True)
    swebench = commands.add_parser(
        "resolve-swebench-verified",
        help="resolve one official SWE-bench Verified enriched-v1 row",
    )
    swebench.add_argument("row", type=Path)
    swebench.add_argument("--episode-id", required=True)
    swebench.add_argument("--task-image", required=True)
    swebench.add_argument(
        "--task-platform",
        choices=("linux/amd64", "linux/arm64"),
        default="linux/amd64",
    )
    swebench.add_argument("--assets-dir", type=Path, required=True)
    _add_claude_arguments(swebench)
    swebench.add_argument("--inference-environment", required=True)
    swebench.add_argument("--verification-environment", required=True)
    swebench.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="execute inference and isolated verification")
    run.add_argument("episode", type=Path)
    qualify = commands.add_parser(
        "qualify", help="run bounded model-free image and mount qualification"
    )
    qualify.add_argument("episode", type=Path)
    for name in ("status", "inspect", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("episode_id")
    for name in ("wait", "resume"):
        recovery = commands.add_parser(name)
        recovery.add_argument("episode_id")
        recovery.add_argument("--timeout", type=float)
    export = commands.add_parser("export")
    export.add_argument("episode_id")
    export.add_argument("destination", type=Path)
    verify = commands.add_parser("verify-record")
    verify.add_argument("episode_id")
    report = commands.add_parser("report")
    report.add_argument("episode_id")
    report.add_argument("--format", choices=("json", "markdown"), default="json")
    report.add_argument("--output", type=Path)
    return parser


def _add_claude_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--claude-mount-image", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--claude-default-opus-model", default="")
    parser.add_argument("--claude-default-sonnet-model", default="")
    parser.add_argument("--claude-default-haiku-model", default="")
    parser.add_argument("--claude-subagent-model", default="")
    parser.add_argument(
        "--claude-effort-level", choices=("low", "medium", "high", "max"), default=""
    )
    parser.add_argument("--claude-auto-compact-window", type=int, default=0)
    parser.add_argument(
        "--claude-disallowed-tools",
        nargs="*",
        default=None,
        metavar="TOOL",
        help="Claude built-in tools to disable; defaults to WebFetch and WebSearch offline",
    )
    parser.add_argument("--max-turns", type=int, default=40)


def _claude_harness(args: argparse.Namespace, *, working_directory: str) -> HarnessSpec:
    if not args.claude_mount_image or not args.model:
        raise ContractError("claude-code requires --claude-mount-image and --model")
    config: dict[str, Any] = {
        "mount_image": args.claude_mount_image,
        "model": args.model,
        "max_turns": args.max_turns,
        "working_directory": working_directory,
    }
    if args.claude_disallowed_tools is not None:
        config["disallowed_tools"] = args.claude_disallowed_tools
    for argument, key in (
        (args.claude_default_opus_model, "default_opus_model"),
        (args.claude_default_sonnet_model, "default_sonnet_model"),
        (args.claude_default_haiku_model, "default_haiku_model"),
        (args.claude_subagent_model, "subagent_model"),
        (args.claude_effort_level, "effort_level"),
    ):
        if argument:
            config[key] = argument
    if args.claude_auto_compact_window:
        config["auto_compact_window"] = args.claude_auto_compact_window
    return HarnessSpec(identity="claude-code", version="2.1.205", config=config)


def _write_episode(episode: ResolvedEpisode, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(asdict(episode)) + b"\n")
    _print(
        {
            "episode_id": episode.episode_id,
            "seed_digest": episode.seed_digest,
            "output": str(output),
        }
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            episode = _episode(args.episode)
            _print({"episode_id": episode.episode_id, "spec_digest": episode.digest})
            return 0
        if args.command == "resolve-synthetic":
            raw_value: object = json.loads(args.row.read_text(encoding="utf-8"))
            if not isinstance(raw_value, dict):
                raise ContractError("synthetic dataset row must be a JSON object")
            if args.harness == "static-patch":
                if not args.candidate_file:
                    raise ContractError("static-patch requires --candidate-file")
                harness = HarnessSpec(
                    identity="static-patch",
                    version="1",
                    config={"candidate_file": args.candidate_file},
                )
            else:
                harness = _claude_harness(args, working_directory="/workspace")
            episode = SyntheticCodeTaskResolver().resolve(
                cast(dict[str, Any], raw_value),
                source_dir=args.row.parent,
                episode_id=args.episode_id,
                inference_environment_id=args.inference_environment,
                verification_environment_id=args.verification_environment,
                harness=harness,
            )
            _write_episode(episode, args.output)
            return 0
        if args.command == "resolve-swebench-verified":
            raw_value = json.loads(args.row.read_text(encoding="utf-8"))
            if not isinstance(raw_value, dict):
                raise ContractError("SWE-bench Verified row must be a JSON object")
            episode = SweBenchVerifiedResolver().resolve(
                cast(dict[str, Any], raw_value),
                asset_dir=args.assets_dir,
                episode_id=args.episode_id,
                inference_environment_id=args.inference_environment,
                verification_environment_id=args.verification_environment,
                task_image=args.task_image,
                task_platform=args.task_platform,
                harness=_claude_harness(args, working_directory="/testbed"),
            )
            _write_episode(episode, args.output)
            return 0
        store = EpisodeStore(args.state_dir)
        if args.command == "status":
            _print(_status(store, args.episode_id))
            return 0
        if args.command == "inspect":
            record = store.load(args.episode_id)
            if record is None:
                raise ContractError(f"episode record does not exist: {args.episode_id}")
            value = record.as_dict()
            progress = _load_progress(store, record.episode_id, record.progress_path)
            if progress is not None:
                value["progress"] = progress.as_dict()
            _print(value)
            return 0
        if args.command == "export":
            _print({"path": str(_export(store, args.episode_id, args.destination))})
            return 0
        if args.command in {"verify-record", "report"}:
            report = verify_record(store, args.episode_id)
            if args.command == "verify-record":
                _print(report)
                return 0
            payload = (
                report_markdown(report)
                if args.format == "markdown"
                else canonical_report_json(report)
            )
            if args.output is None:
                print(payload, end="")
            else:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                if args.output.exists():
                    raise ContractError(f"report output already exists: {args.output}")
                args.output.write_text(payload, encoding="utf-8")
                _print({"path": str(args.output)})
            return 0
        client = _client(args)
        try:
            runner = _runner(args, client)
            if args.command == "qualify":
                episode = _episode(args.episode)
                inference, _ = _adapters(episode)
                inference.plan(episode)
                result = qualify_episode(
                    episode,
                    client=client,
                    backend=runner.backend,
                    store=store,
                )
                _print(result.as_dict())
                return 0
            if args.command == "run":
                episode = _episode(args.episode)
                inference, verifier = _adapters(episode)
                inference.plan(episode)
                qualify_episode(
                    episode,
                    client=client,
                    backend=runner.backend,
                    store=store,
                )
                result = runner.run(
                    episode,
                    inference=inference,
                    verifier=verifier,
                    trajectory=_trajectory_adapter(episode),
                    inference_lifecycle=_model_lifecycle(args, client, episode, store),
                )
            elif args.command == "cancel":
                _print(runner.cancel(args.episode_id).as_dict())
                return 0
            else:
                episode = store.load_spec(args.episode_id)
                inference, verifier = _adapters(episode)
                if args.command in {"wait", "resume"}:
                    result = runner.wait(
                        args.episode_id,
                        inference=inference,
                        verifier=verifier,
                        trajectory=_trajectory_adapter(episode),
                        timeout=args.timeout,
                    )
                else:
                    raise AssertionError(f"unhandled command: {args.command}")
            _print(asdict(result))
            return 0
        finally:
            client.close()
    except (AxrunError, AxernError, OSError, ValueError) as exc:
        print(f"axrun: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
