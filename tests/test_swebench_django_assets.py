"""Synthetic lock tests; no official row, patch body, Docker, or network."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

PATH = Path(__file__).parents[1] / "tools/validation/swebench_django_assets.py"
SPEC = importlib.util.spec_from_file_location("swebench_django_assets", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _synthetic_row(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    row = {
        "FAIL_TO_PASS": ["synthetic.case"],
        "PASS_TO_PASS": [],
        "base_commit": MODULE.BASE_COMMIT,
        "created_at": "2020-01-01T00:00:00Z",
        "difficulty": "synthetic",
        "environment_setup_commit": MODULE.SETUP_COMMIT,
        "eval_script": "#!/bin/bash\ntrue\n",
        "eval_type": "pass_and_fail",
        "hints_text": "",
        "image": MODULE.IMAGE,
        "instance_id": MODULE.INSTANCE_ID,
        "log_parser": "parse_log_django",
        "patch": "diff --git a/a b/a\nsynthetic\n",
        "problem_statement": "Synthetic problem, not benchmark content.",
        "repo": "django/django",
        "test_patch": "diff --git a/t b/t\nsynthetic\n",
        "version": "3.1",
    }
    for field, constant in (
        ("patch", "GOLD_SHA256"),
        ("eval_script", "EVAL_SHA256"),
        ("test_patch", "TEST_SHA256"),
    ):
        monkeypatch.setattr(MODULE, constant, MODULE.sha256(cast(str, row[field]).encode()))
    monkeypatch.setattr(MODULE, "ROW_SHA256", MODULE.sha256(MODULE.canonical_json(row)))
    monkeypatch.setattr(
        MODULE,
        "SEED_DIGEST",
        MODULE.sha256(
            MODULE.canonical_json(
                {"dataset": MODULE.DATASET, "row_schema": "enriched-v1", "row": row}
            )
        ),
    )
    return row


def _prepare_synthetic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, dict[str, Any]]:
    row = _synthetic_row(monkeypatch)

    def fake_harness(path: Path) -> Path:
        return path

    def fake_raw_row(path: Path) -> dict[str, Any]:
        return {"instance_id": MODULE.INSTANCE_ID}

    def fake_enrichment(raw: dict[str, Any], checkout: Path) -> dict[str, Any]:
        return row

    monkeypatch.setattr(MODULE, "_check_harness", fake_harness)
    monkeypatch.setattr(MODULE, "_read_raw_row", fake_raw_row)
    monkeypatch.setattr(MODULE, "_official_enrichment", fake_enrichment)
    output = tmp_path / "private"
    manifest = MODULE.prepare_assets(tmp_path / "fake.parquet", tmp_path / "fake-scorer", output)
    return output, manifest


def test_prepare_synthetic_assets_and_revalidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output, manifest = _prepare_synthetic(monkeypatch, tmp_path)
    assert MODULE.validate_assets(output) == manifest
    assert set(manifest["assets"]) == set(MODULE.ASSET_NAMES)
    assert manifest["assets"]["known_bad.patch"]["bytes"] > 0
    assert manifest["assets"]["known_bad.patch"]["sha256"] == MODULE.KNOWN_BAD_SHA256
    assert manifest["assets"]["empty.patch"]["bytes"] == 0
    assert manifest["assets"]["empty.patch"]["sha256"] == MODULE.EMPTY_SHA256
    assert manifest["assets"]["row.json"]["sha256"] == MODULE.ROW_SHA256
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())
    assert MODULE.load_locked_row(output / "row.json")["instance_id"] == MODULE.INSTANCE_ID
    assert (
        MODULE.prepare_assets(tmp_path / "fake.parquet", tmp_path / "fake-scorer", output)
        == manifest
    )


@pytest.mark.parametrize("name", [*MODULE.ASSET_NAMES, "assets-manifest.json"])
def test_any_prepared_asset_tampering_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    output, _ = _prepare_synthetic(monkeypatch, tmp_path)
    target = output / name
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(MODULE.AssetError):
        MODULE.validate_assets(output)
    with pytest.raises(MODULE.AssetError):
        MODULE.prepare_assets(tmp_path / "fake.parquet", tmp_path / "fake-scorer", output)


def test_wrong_instance_and_row_shape_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output, _ = _prepare_synthetic(monkeypatch, tmp_path)
    row = json.loads((output / "row.json").read_text())
    row["instance_id"] = "django__django-else"
    (output / "row.json").write_bytes(MODULE.canonical_json(row))
    with pytest.raises(MODULE.AssetError, match="SHA-256"):
        MODULE.load_locked_row(output / "row.json")
    row["instance_id"] = MODULE.INSTANCE_ID
    row["extra"] = "unknown"
    (output / "row.json").write_bytes(MODULE.canonical_json(row))
    with pytest.raises(MODULE.AssetError, match="fields"):
        MODULE.load_locked_row(output / "row.json")


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_json_parser_rejects_ambiguous_values(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "synthetic.json"
    path.write_text(payload)
    with pytest.raises(MODULE.AssetError):
        MODULE._load_json(path)


def test_parquet_bytes_and_single_row_are_locked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parquet = tmp_path / "source.parquet"
    parquet.write_bytes(b"synthetic parquet")
    monkeypatch.setattr(MODULE, "PARQUET_BYTES", len(parquet.read_bytes()))
    monkeypatch.setattr(MODULE, "PARQUET_SHA256", MODULE.sha256(parquet.read_bytes()))
    raw = {
        "instance_id": MODULE.INSTANCE_ID,
        **{key: "x" for key in MODULE.RAW_FIELDS - {"instance_id"}},
    }
    monkeypatch.setattr(MODULE, "RAW_ROW_SHA256", MODULE.sha256(MODULE.canonical_json(raw)))
    rows: list[dict[str, Any]] = [raw]
    fake_pyarrow = types.ModuleType("pyarrow")
    fake_parquet = types.ModuleType("pyarrow.parquet")

    def fake_to_pylist() -> list[dict[str, Any]]:
        return rows

    def fake_read_table(path: Path, filters: list[tuple[str, str, str]]) -> Any:
        return types.SimpleNamespace(to_pylist=fake_to_pylist)

    monkeypatch.setattr(fake_parquet, "read_table", fake_read_table, raising=False)
    monkeypatch.setattr(fake_pyarrow, "parquet", fake_parquet, raising=False)
    monkeypatch.setitem(sys.modules, "pyarrow", fake_pyarrow)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", fake_parquet)
    assert MODULE._read_raw_row(parquet) == raw
    rows.append(raw)
    with pytest.raises(MODULE.AssetError, match="exactly one"):
        MODULE._read_raw_row(parquet)
    rows.pop()
    parquet.write_bytes(b"changed parquet")
    with pytest.raises(MODULE.AssetError, match="size or SHA-256"):
        MODULE._read_raw_row(parquet)


def test_tracked_repo_output_requires_ignored_private_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    with pytest.raises(MODULE.AssetError, match="ignored"):
        MODULE._private_output_dir(repository / "visible")
    (repository / ".gitignore").write_text(".private/\n")
    assert MODULE._private_output_dir(repository / ".private") == repository / ".private"
    private = repository / ".private"
    private.mkdir(mode=0o700)
    (private / "tracked.txt").write_text("synthetic")
    subprocess.run(["git", "-C", str(repository), "add", "-f", ".private/tracked.txt"], check=True)
    with pytest.raises(MODULE.AssetError, match="tracked"):
        MODULE._private_output_dir(private)


def test_git_environment_omits_caller_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.helper")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "synthetic-helper")
    env = MODULE._safe_git_env()
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "GIT_CONFIG_COUNT" not in env
    assert "GIT_CONFIG_KEY_0" not in env
    assert "GIT_CONFIG_VALUE_0" not in env
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"


def test_symlink_and_open_permissions_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output, _ = _prepare_synthetic(monkeypatch, tmp_path)
    output.chmod(0o755)
    with pytest.raises(MODULE.AssetError, match="private"):
        MODULE.validate_assets(output)
    output.chmod(0o700)
    row = output / "row.json"
    row_copy = tmp_path / "row-copy.json"
    row_copy.write_bytes(row.read_bytes())
    row.unlink()
    os.symlink(row_copy, row)
    with pytest.raises(MODULE.AssetError, match="regular file"):
        MODULE.validate_assets(output)
