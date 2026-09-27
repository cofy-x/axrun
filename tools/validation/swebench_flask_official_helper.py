"""Pinned SWE-bench source bridge for the Flask stage-zero oracle.

Invoked only by swebench_flask_official_oracle.py with an explicitly selected
Python environment that already has the official harness dependencies. This
module does not install dependencies or fetch data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

PARQUET_SHA256 = "030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25"
PARQUET_BYTES = 6_304_616
ROW_SHA256 = "36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e"
INSTANCE_ID = "pallets__flask-5014"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _read_official_row(parquet_path: Path) -> dict[str, Any]:
    import pyarrow.parquet as parquet

    data = parquet_path.read_bytes()
    if len(data) != PARQUET_BYTES or _sha256(data) != PARQUET_SHA256:
        raise ValueError("pinned official Parquet bytes or SHA-256 differ")
    table = parquet.read_table(parquet_path, filters=[("instance_id", "==", INSTANCE_ID)])
    rows = table.to_pylist()
    if len(rows) != 1 or rows[0].get("instance_id") != INSTANCE_ID:
        raise ValueError("pinned Parquet does not contain exactly one Flask instance")
    row = rows[0]
    if _sha256(_canonical(row)) != ROW_SHA256:
        raise ValueError("pinned Parquet Flask row digest differs")
    return row


def _check_harness_source(harness_source: Path) -> None:
    import swebench

    package = Path(swebench.__file__).resolve().parent
    if package != (harness_source / "swebench").resolve():
        raise ValueError("scorer Python imported SWE-bench from a different source")


def prepare(parquet_path: Path, harness_source: Path, row_path: Path) -> dict[str, Any]:
    from swebench.harness.test_spec.test_spec import make_test_spec

    _check_harness_source(harness_source)
    official_row = _read_official_row(parquet_path)
    if row_path.is_file():
        supplied = json.loads(row_path.read_text(encoding="utf-8"))
        if _canonical(supplied) != _canonical(official_row):
            raise ValueError("supplied enriched row differs from pinned Parquet row")
    else:
        row_path.write_bytes(_canonical(official_row) + b"\n")
        row_path.chmod(0o600)
    spec = make_test_spec(official_row, namespace="swebench")
    if spec.instance_image_key != "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest":
        raise ValueError("official TestSpec image key differs from locked instance")
    if spec.eval_script != official_row["eval_script"]:
        raise ValueError("enriched eval script differs from pinned official TestSpec")
    if official_row["FAIL_TO_PASS"] != spec.FAIL_TO_PASS:
        raise ValueError("official TestSpec fail-to-pass list differs")
    if official_row["PASS_TO_PASS"] != spec.PASS_TO_PASS:
        raise ValueError("official TestSpec pass-to-pass list differs")
    return {
        "raw_row_match": True,
        "parquet_sha256": PARQUET_SHA256,
        "row_sha256": ROW_SHA256,
        "eval_script_sha256": _sha256(spec.eval_script.encode("utf-8")),
        "fail_to_pass_count": len(spec.FAIL_TO_PASS),
        "pass_to_pass_count": len(spec.PASS_TO_PASS),
    }


def grade(harness_source: Path, row_path: Path, test_log: Path, patch_path: Path) -> dict[str, Any]:
    from swebench.harness.grading import get_eval_report, get_logs_eval
    from swebench.harness.test_spec.test_spec import make_test_spec

    _check_harness_source(harness_source)
    row = json.loads(row_path.read_text(encoding="utf-8"))
    if _sha256(_canonical(row)) != ROW_SHA256:
        raise ValueError("row changed after official preparation")
    spec = make_test_spec(row, namespace="swebench")
    status_map, found = get_logs_eval(spec, str(test_log))
    if not found:
        raise ValueError("official grader did not find a complete test output")
    prediction = {
        "instance_id": INSTANCE_ID,
        "model_name_or_path": f"axrun-stage-zero-{patch_path.parent.name}",
        "model_patch": patch_path.read_text(encoding="utf-8"),
    }
    report = get_eval_report(spec, prediction, str(test_log), include_tests_status=True)
    return {"status_map": status_map, "report": report}


def empty(harness_source: Path, row_path: Path, output_path: Path) -> dict[str, Any]:
    from swebench.harness.reporting import make_run_report

    _check_harness_source(harness_source)
    row = json.loads(row_path.read_text(encoding="utf-8"))
    if _sha256(_canonical(row)) != ROW_SHA256:
        raise ValueError("row changed after official preparation")
    prediction = {
        "instance_id": INSTANCE_ID,
        "model_name_or_path": "axrun-stage-zero-empty",
        "model_patch": "",
    }
    previous = Path.cwd()
    try:
        os.chdir(output_path.parent)
        report_path = make_run_report(
            {INSTANCE_ID: prediction}, [row], "axrun-stage-zero-empty", client=None
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
    finally:
        os.chdir(previous)
    if report.get("empty_patch_ids") != [INSTANCE_ID]:
        raise ValueError("official run report did not classify empty patch")
    if report.get("completed_instances") != 0 or report.get("resolved_instances") != 0:
        raise ValueError("official run report assigned a test verdict to empty patch")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "grade", "empty"))
    parser.add_argument("--harness-source", type=Path, required=True)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--row", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test-log", type=Path)
    parser.add_argument("--patch", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        payload = prepare(args.parquet, args.harness_source, args.row)
    elif args.action == "grade":
        if args.test_log is None or args.patch is None:
            parser.error("grade requires --test-log and --patch")
        payload = grade(args.harness_source, args.row, args.test_log, args.patch)
    else:
        payload = empty(args.harness_source, args.row, args.output)
    args.output.write_bytes(_canonical(payload) + b"\n")
    args.output.chmod(0o600)


if __name__ == "__main__":
    main()
