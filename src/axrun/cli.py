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

from axrun.adapters._candidate import load_candidate
from axrun.axern_backend import AxernBackend
from axrun.catalog import resolve_adapters, resolve_model_protocol
from axrun.datasets import (
    ProgramBenchCompatibilityResolver,
    ProgramBenchOfficialSingleResolver,
    SweBenchVerifiedResolver,
    SyntheticCodeTaskResolver,
    SyntheticGreenfieldResolver,
)
from axrun.errors import AxrunError, ContractError
from axrun.lifecycle.base import CompositePreStartLifecycle, PreStartLifecycle
from axrun.lifecycle.model_tunnel import ModelTunnelLifecycle
from axrun.lifecycle.stage_progress import StageProgressObserver
from axrun.models import (
    EpisodePhase,
    HarnessRuntimeRequirements,
    HarnessSpec,
    ResolvedEpisode,
    canonical_json,
    resolved_episode_from_dict,
)
from axrun.preparation import (
    AxernEnvironmentPreparationClient,
    EnvironmentPreparationService,
    KovaSdkPreparationClient,
    PreparationStore,
    seed_build_spec_from_dict,
)
from axrun.progress.store import ProgressStore
from axrun.proxy.model import ModelProxy
from axrun.qualification import qualify_episode
from axrun.report import canonical_report_json, report_markdown, verify_record
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore
from axrun.trajectories.bundle import load_trajectory_bundle


def _episode(path: Path) -> ResolvedEpisode:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractError("ResolvedEpisode must be a JSON object")
    return resolved_episode_from_dict(cast(dict[str, Any], raw))


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
    requirements: HarnessRuntimeRequirements,
) -> PreStartLifecycle | None:
    protocol = resolve_model_protocol(requirements)
    if protocol is None:
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
        protocol=protocol,
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
        "--harness", choices=("static-candidate", "claude-code"), default="static-candidate"
    )
    resolve.add_argument("--candidate-file", default="")
    resolve.add_argument("--task-image", required=True)
    resolve.add_argument("--task-platform", choices=("linux/amd64", "linux/arm64"), required=True)
    _add_claude_arguments(resolve)
    resolve.add_argument("--inference-environment", required=True)
    resolve.add_argument("--verification-environment", required=True)
    resolve.add_argument("--output", type=Path, required=True)
    greenfield = commands.add_parser(
        "resolve-greenfield", help="resolve the Axrun no-Git greenfield synthetic row"
    )
    greenfield.add_argument("row", type=Path)
    greenfield.add_argument("--episode-id", required=True)
    greenfield.add_argument(
        "--harness", choices=("static-candidate", "claude-code"), default="static-candidate"
    )
    greenfield.add_argument(
        "--candidate-variant", choices=("gold", "empty", "known-bad"), default="gold"
    )
    greenfield.add_argument("--inference-image", required=True)
    greenfield.add_argument("--verification-image", required=True)
    greenfield.add_argument(
        "--task-platform", choices=("linux/amd64", "linux/arm64"), required=True
    )
    _add_claude_arguments(greenfield)
    greenfield.add_argument("--inference-environment", required=True)
    greenfield.add_argument("--verification-environment", required=True)
    greenfield.add_argument("--output", type=Path, required=True)
    programbench = commands.add_parser(
        "resolve-programbench-compatibility",
        help="resolve the closed ProgramBench 1.2.4 calculator compatibility fixture",
    )
    programbench.add_argument("row", type=Path)
    programbench.add_argument("--episode-id", required=True)
    programbench.add_argument(
        "--harness", choices=("static-candidate", "claude-code"), default="static-candidate"
    )
    programbench.add_argument(
        "--candidate-variant", choices=("gold", "empty", "known-bad"), default="gold"
    )
    programbench.add_argument("--inference-image", required=True)
    programbench.add_argument("--verification-image", required=True)
    programbench.add_argument(
        "--task-platform", choices=("linux/amd64", "linux/arm64"), required=True
    )
    _add_claude_arguments(programbench)
    programbench.add_argument("--inference-environment", required=True)
    programbench.add_argument("--verification-environment", required=True)
    programbench.add_argument("--output", type=Path, required=True)
    programbench_official = commands.add_parser(
        "resolve-programbench-official",
        help=("resolve the locked executable ProgramBench 1.2.4 tty-clock contract"),
    )
    programbench_official.add_argument("row", type=Path)
    programbench_official.add_argument("--episode-id", required=True)
    programbench_official.add_argument(
        "--harness", choices=("static-candidate", "claude-code"), default="static-candidate"
    )
    _add_claude_arguments(programbench_official)
    programbench_official.add_argument("--test-assets-dir", type=Path, required=True)
    programbench_official.add_argument("--static-candidate-directory", type=Path)
    programbench_official.add_argument("--runtime-image", required=True)
    programbench_official.add_argument("--inference-environment", required=True)
    programbench_official.add_argument("--verification-environment", required=True)
    programbench_official.add_argument("--output", type=Path, required=True)
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
    prepare = commands.add_parser(
        "prepare-kova-environment",
        help="explicitly build one Kova seed image and create an Axern Environment",
    )
    prepare.add_argument("spec", type=Path)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--wait-timeout", type=float, default=900.0)
    preparation_status = commands.add_parser("preparation-status")
    preparation_status.add_argument("preparation_id")
    preparation_resume = commands.add_parser("preparation-resume")
    preparation_resume.add_argument("preparation_id")
    preparation_resume.add_argument("--wait-timeout", type=float, default=900.0)
    preparation_binding = commands.add_parser("preparation-binding")
    preparation_binding.add_argument("preparation_id")
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


def _write_preparation_output(value: object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _preparation_service(
    args: argparse.Namespace,
) -> tuple[EnvironmentPreparationService, Any, KovaSdkPreparationClient]:
    client = _client(args)
    try:
        kova = KovaSdkPreparationClient.from_env()
    except Exception:
        client.close()
        raise
    return (
        EnvironmentPreparationService(
            store=PreparationStore(args.state_dir),
            kova=kova,
            axern=AxernEnvironmentPreparationClient(client),
        ),
        client,
        kova,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            episode = _episode(args.episode)
            _print({"episode_id": episode.episode_id, "spec_digest": episode.digest})
            return 0
        preparation_store = PreparationStore(args.state_dir)
        if args.command == "preparation-status":
            record = preparation_store.load_record(args.preparation_id)
            if record is None:
                raise ContractError(f"preparation does not exist: {args.preparation_id}")
            _print(asdict(record))
            return 0
        if args.command == "preparation-binding":
            record = preparation_store.load_record(args.preparation_id)
            if record is None:
                raise ContractError(f"preparation does not exist: {args.preparation_id}")
            _print(asdict(preparation_store.load_preparation_receipt(record).environment_binding()))
            return 0
        if args.command in {"prepare-kova-environment", "preparation-resume"}:
            service, preparation_axern, preparation_kova = _preparation_service(args)
            try:
                if args.command == "prepare-kova-environment":
                    raw_spec: object = json.loads(args.spec.read_text(encoding="utf-8"))
                    if not isinstance(raw_spec, dict):
                        raise ContractError("SeedBuildSpec must be a JSON object")
                    receipt = service.prepare(
                        seed_build_spec_from_dict(cast(dict[str, Any], raw_spec)),
                        wait_timeout=args.wait_timeout,
                    )
                    _write_preparation_output(asdict(receipt), args.output)
                else:
                    receipt = service.resume(args.preparation_id, wait_timeout=args.wait_timeout)
                _print(asdict(receipt))
                return 0
            finally:
                preparation_kova.close()
                preparation_axern.close()
        if args.command == "resolve-synthetic":
            raw_value: object = json.loads(args.row.read_text(encoding="utf-8"))
            if not isinstance(raw_value, dict):
                raise ContractError("synthetic dataset row must be a JSON object")
            if args.harness == "static-candidate":
                if not args.candidate_file:
                    raise ContractError("static-candidate requires --candidate-file")
                harness = HarnessSpec(
                    identity="static-candidate",
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
                task_image=args.task_image,
                task_platform=args.task_platform,
                harness=harness,
            )
            _write_episode(episode, args.output)
            return 0
        if args.command == "resolve-greenfield":
            raw_value = json.loads(args.row.read_text(encoding="utf-8"))
            if not isinstance(raw_value, dict):
                raise ContractError("greenfield dataset row must be a JSON object")
            harness = (
                HarnessSpec(
                    "static-candidate", "1", config={"candidate_variant": args.candidate_variant}
                )
                if args.harness == "static-candidate"
                else _claude_harness(args, working_directory="/workspace")
            )
            episode = SyntheticGreenfieldResolver().resolve(
                cast(dict[str, Any], raw_value),
                source_dir=args.row.parent,
                episode_id=args.episode_id,
                inference_environment_id=args.inference_environment,
                verification_environment_id=args.verification_environment,
                inference_image=args.inference_image,
                verification_image=args.verification_image,
                task_platform=args.task_platform,
                harness=harness,
            )
            _write_episode(episode, args.output)
            return 0
        if args.command == "resolve-programbench-compatibility":
            raw_value = json.loads(args.row.read_text(encoding="utf-8"))
            if not isinstance(raw_value, dict):
                raise ContractError("ProgramBench compatibility row must be a JSON object")
            harness = (
                HarnessSpec(
                    "static-candidate", "1", config={"candidate_variant": args.candidate_variant}
                )
                if args.harness == "static-candidate"
                else _claude_harness(args, working_directory="/workspace")
            )
            episode = ProgramBenchCompatibilityResolver().resolve(
                cast(dict[str, Any], raw_value),
                source_dir=args.row.parent,
                episode_id=args.episode_id,
                inference_environment_id=args.inference_environment,
                verification_environment_id=args.verification_environment,
                inference_image=args.inference_image,
                verification_image=args.verification_image,
                task_platform=args.task_platform,
                harness=harness,
            )
            _write_episode(episode, args.output)
            return 0
        if args.command == "resolve-programbench-official":
            raw_value = json.loads(args.row.read_text(encoding="utf-8"))
            if not isinstance(raw_value, dict):
                raise ContractError("ProgramBench official row must be a JSON object")
            harness = (
                HarnessSpec("static-candidate", "1")
                if args.harness == "static-candidate"
                else _claude_harness(args, working_directory="/workspace")
            )
            episode = ProgramBenchOfficialSingleResolver().resolve(
                cast(dict[str, Any], raw_value),
                source_dir=args.row.parent,
                episode_id=args.episode_id,
                inference_environment_id=args.inference_environment,
                verification_environment_id=args.verification_environment,
                harness=harness,
                runtime_image=args.runtime_image,
                test_assets_dir=args.test_assets_dir,
                static_candidate_dir=args.static_candidate_directory,
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
                selection = resolve_adapters(episode)
                selection.inference.plan(episode, selection.candidate.capture_plan(episode))
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
                selection = resolve_adapters(episode)
                selection.inference.plan(episode, selection.candidate.capture_plan(episode))
                qualify_episode(
                    episode,
                    client=client,
                    backend=runner.backend,
                    store=store,
                )
                result = runner.run(
                    episode,
                    inference=selection.inference,
                    candidate=selection.candidate,
                    verifier=selection.verifier,
                    trajectory=selection.trajectory,
                    inference_lifecycle=_model_lifecycle(
                        args, client, episode, store, selection.runtime
                    ),
                )
            elif args.command == "cancel":
                episode = store.load_spec(args.episode_id)
                selection = resolve_adapters(episode)
                _print(runner.cancel(args.episode_id, verifier=selection.verifier).as_dict())
                return 0
            else:
                episode = store.load_spec(args.episode_id)
                selection = resolve_adapters(episode)
                if args.command in {"wait", "resume"}:
                    result = runner.wait(
                        args.episode_id,
                        inference=selection.inference,
                        candidate=selection.candidate,
                        verifier=selection.verifier,
                        trajectory=selection.trajectory,
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
