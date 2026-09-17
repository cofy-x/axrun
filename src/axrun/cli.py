"""Small CLI for validating stable episode contracts."""

from __future__ import annotations

import argparse
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from axrun.models import ResolvedEpisode


def _episode(raw: dict[str, Any]) -> ResolvedEpisode:
    names = {item.name for item in fields(ResolvedEpisode)}
    return ResolvedEpisode(**{key: value for key, value in raw.items() if key in names})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="axrun")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a ResolvedEpisode JSON file")
    validate.add_argument("episode", type=Path)
    args = parser.parse_args(argv)
    if args.command == "validate":
        episode = _episode(json.loads(args.episode.read_text(encoding="utf-8")))
        print(f"valid episode {episode.episode_id}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
