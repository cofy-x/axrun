#!/usr/bin/env python3
"""Qualify the arm64 image with fresh empty and gold verifier containers."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

INSTANCE_ID = "django__django-12419"
BASE_COMMIT = "7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
FAIL_TO_PASS = ["test_middleware_headers (project_template.test_settings.TestStartProjectSettings)"]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_row(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise ValueError("dataset row must be a JSON object")
    expected = {
        "instance_id": INSTANCE_ID,
        "base_commit": BASE_COMMIT,
        "log_parser": "parse_log_django",
        "FAIL_TO_PASS": FAIL_TO_PASS,
        "PASS_TO_PASS": [],
    }
    for key, value in expected.items():
        if row.get(key) != value:
            raise ValueError(f"unexpected {key} in qualification row")
    for key in ("patch", "eval_script"):
        if not isinstance(row.get(key), str) or not row[key]:
            raise ValueError(f"qualification row requires non-empty {key}")
    return row


def _run_case(
    *, image: str, root: Path, verifier: Path, eval_script: Path, name: str, patch: bytes
) -> dict[str, Any]:
    candidate = root / f"{name}.patch"
    candidate.write_bytes(patch)
    candidate_digest = _sha256(patch)
    result = root / f"{name}.json"
    log = root / f"{name}.log"
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/arm64",
            "--network",
            "none",
            "--mount",
            f"type=bind,src={root},dst=/qualification",
            "--mount",
            f"type=bind,src={verifier},dst=/opt/axrun-swebench/run_verifier.py,readonly",
            image,
            "python3",
            "/opt/axrun-swebench/run_verifier.py",
            "--workspace",
            "/testbed",
            "--base-commit",
            BASE_COMMIT,
            "--candidate",
            f"/qualification/{candidate.name}",
            "--candidate-digest",
            candidate_digest,
            "--eval-script",
            f"/qualification/{eval_script.name}",
            "--log-parser",
            "parse_log_django",
            "--fail-to-pass",
            json.dumps(FAIL_TO_PASS, separators=(",", ":")),
            "--pass-to-pass",
            "[]",
            "--result",
            f"/qualification/{result.name}",
            "--log",
            f"/qualification/{log.name}",
        ],
        check=True,
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    if payload.get("candidate_digest") != candidate_digest:
        raise RuntimeError(f"{name} verifier result references the wrong candidate")
    return {
        "candidate_sha256": candidate_digest,
        "diagnostic_code": payload.get("diagnostic_code"),
        "log_sha256": _sha256(log.read_bytes()),
        "resolved": payload.get("resolved"),
        "score": payload.get("score"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="axrun-swebench-verified-django-12419:arm64-dev")
    parser.add_argument("--row", type=Path, required=True)
    args = parser.parse_args()
    row = _load_row(args.row.resolve())
    repo_root = Path(__file__).resolve().parents[3]
    verifier = repo_root / "src/axrun/fixtures/swebench_verified/run_verifier.py"
    if not verifier.is_file():
        raise FileNotFoundError("packaged SWE-bench verifier is missing")
    with tempfile.TemporaryDirectory(prefix="axrun-swebench-qualification-") as directory:
        root = Path(directory).resolve()
        eval_script = root / "eval.sh"
        eval_script.write_text(row["eval_script"], encoding="utf-8")
        empty = _run_case(
            image=args.image,
            root=root,
            verifier=verifier,
            eval_script=eval_script,
            name="empty",
            patch=b"",
        )
        gold = _run_case(
            image=args.image,
            root=root,
            verifier=verifier,
            eval_script=eval_script,
            name="gold",
            patch=row["patch"].encode(),
        )
    if empty["resolved"] is not False or gold["resolved"] is not True:
        raise RuntimeError("qualification requires empty=failed and gold=passed")
    print(
        json.dumps(
            {"image": args.image, "instance_id": INSTANCE_ID, "empty": empty, "gold": gold},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
