"""Caller-local CLI commands that resolve dataset rows into episode files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from axrun.datasets import (
    ProgramBenchCompatibilityResolver,
    ProgramBenchOfficialSingleResolver,
    SweBenchVerifiedResolver,
    SyntheticCodeTaskResolver,
    SyntheticGreenfieldResolver,
)
from axrun.datasets.swebench_flask_official import SweBenchFlaskOfficialResolver
from axrun.errors import ContractError
from axrun.models import HarnessSpec, ResolvedEpisode, canonical_json

RESOLVE_COMMANDS = frozenset(
    {
        "resolve-synthetic",
        "resolve-greenfield",
        "resolve-programbench-compatibility",
        "resolve-programbench-official",
        "resolve-swebench-verified",
        "resolve-swebench-flask-official",
    }
)


def flask_import_receipt(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1 << 20:
        raise ContractError("Flask image import receipt must be a bounded regular file")
    value: object = json.loads(path.read_text(encoding="utf-8"))
    fields = {"source_ref", "canonical_ref", "immutable_ref", "content_digest", "platform"}
    if not isinstance(value, dict):
        raise ContractError("Flask image import receipt has an invalid shape")
    entries = cast(dict[object, object], value)
    if set(entries) != fields or any(
        not isinstance(item, str) or not item for item in entries.values()
    ):
        raise ContractError("Flask image import receipt has an invalid shape")
    return cast(dict[str, str], entries)


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
    output.write_bytes(canonical_json(episode.as_dict()) + b"\n")
    print(
        json.dumps(
            {
                "episode_id": episode.episode_id,
                "seed_digest": episode.seed_digest,
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
        )
    )


def resolve_command(args: argparse.Namespace) -> None:
    """Run one resolver command after argparse validation, without opening an Axern client."""
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
        return
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
        return
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
        return
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
            verification_image=args.verification_image,
            test_assets_dir=args.test_assets_dir,
            static_candidate_dir=args.static_candidate_directory,
        )
        _write_episode(episode, args.output)
        return
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
        return
    if args.command == "resolve-swebench-flask-official":
        raw_value = json.loads(args.row.read_text(encoding="utf-8"))
        if not isinstance(raw_value, dict):
            raise ContractError("official Flask enriched row must be a JSON object")
        harness = (
            HarnessSpec("static-candidate", "1")
            if args.harness == "static-candidate"
            else _claude_harness(args, working_directory="/testbed")
        )
        episode = SweBenchFlaskOfficialResolver().resolve(
            cast(dict[str, Any], raw_value),
            asset_dir=args.assets_dir,
            episode_id=args.episode_id,
            inference_environment_id=args.inference_environment,
            verification_environment_id=args.verification_environment,
            task_image=args.task_image,
            image_import_receipt=flask_import_receipt(args.image_import_receipt),
            wheelhouse_dir=args.wheelhouse_dir,
            admission_receipt_file=args.admission_receipt,
            harness=harness,
            static_candidate_file=args.candidate_file,
        )
        _write_episode(episode, args.output)
        return
    raise AssertionError(f"unhandled resolver command: {args.command}")
