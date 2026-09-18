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

from axrun.adapters import CommandVerifierAdapter, MiniSweAgentAdapter
from axrun.adapters._candidate import load_candidate
from axrun.axern_backend import AxernBackend
from axrun.errors import AxrunError, ContractError
from axrun.models import EpisodePhase, ResolvedEpisode, resolved_episode_from_dict
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore


def _episode(path: Path) -> ResolvedEpisode:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractError("ResolvedEpisode must be a JSON object")
    return resolved_episode_from_dict(cast(dict[str, Any], raw))


def _adapters(episode: ResolvedEpisode) -> tuple[MiniSweAgentAdapter, CommandVerifierAdapter]:
    return (
        MiniSweAgentAdapter(
            command=episode.harness.command,
            version=episode.harness.version,
            timeout_seconds=episode.harness.timeout_seconds,
        ),
        CommandVerifierAdapter(
            command=episode.verifier.command,
            version=episode.verifier.version,
            timeout_seconds=episode.verifier.timeout_seconds,
            name=episode.verifier.identity,
        ),
    )


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
        "diagnostic_code": record.diagnostic_code,
        "message": record.message,
    }
    if record.phase == EpisodePhase.COMPLETED:
        result = store.load_result(record.verification_result, record.verification_result_digest)
        value.update(verdict=result.verdict, score=result.score)
    return value


def _export(store: EpisodeStore, episode_id: str, destination: Path) -> Path:
    record = store.load(episode_id)
    if record is None:
        raise ContractError(f"episode record does not exist: {episode_id}")
    if record.phase != EpisodePhase.COMPLETED:
        raise ContractError(f"episode is not complete: {record.phase.value}")
    candidate = load_candidate(Path(record.candidate_manifest))
    result = store.load_result(record.verification_result, record.verification_result_digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ContractError(f"export destination already exists: {destination}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        shutil.copytree(Path(record.candidate_manifest).parent, temporary / "candidate")
        (temporary / "verification-result.json").write_text(
            json.dumps(asdict(result), sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        (temporary / "export.json").write_text(
            json.dumps(
                {
                    "episode_id": episode_id,
                    "candidate_digest": candidate.digest,
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
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a ResolvedEpisode JSON file")
    validate.add_argument("episode", type=Path)
    run = commands.add_parser("run", help="execute inference and isolated verification")
    run.add_argument("episode", type=Path)
    for name in ("status", "inspect", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("episode_id")
    wait = commands.add_parser("wait")
    wait.add_argument("episode_id")
    wait.add_argument("--timeout", type=float)
    export = commands.add_parser("export")
    export.add_argument("episode_id")
    export.add_argument("destination", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            episode = _episode(args.episode)
            _print({"episode_id": episode.episode_id, "spec_digest": episode.digest})
            return 0
        store = EpisodeStore(args.state_dir)
        if args.command == "status":
            _print(_status(store, args.episode_id))
            return 0
        if args.command == "inspect":
            record = store.load(args.episode_id)
            if record is None:
                raise ContractError(f"episode record does not exist: {args.episode_id}")
            _print(record.as_dict())
            return 0
        if args.command == "export":
            _print({"path": str(_export(store, args.episode_id, args.destination))})
            return 0
        client = _client(args)
        try:
            runner = _runner(args, client)
            if args.command == "run":
                episode = _episode(args.episode)
                inference, verifier = _adapters(episode)
                result = runner.run(episode, inference=inference, verifier=verifier)
            elif args.command == "cancel":
                _print(runner.cancel(args.episode_id).as_dict())
                return 0
            else:
                episode = store.load_spec(args.episode_id)
                inference, verifier = _adapters(episode)
                if args.command == "wait":
                    result = runner.wait(
                        args.episode_id,
                        inference=inference,
                        verifier=verifier,
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
