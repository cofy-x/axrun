"""Prepare private, pinned inputs for the django__django-12419 official oracle.

This is a local-only bridge from the original 13-field Verified Parquet row to
Axrun's 17-field enriched-v1 contract. It neither fetches inputs nor runs an
image or scorer. The caller supplies the local Parquet, pinned scorer checkout,
and a private output directory. Never commit the generated files.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
import types
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

DATASET = "SWE-bench/SWE-bench_Verified"
DATASET_COMMIT = "91aa3ed51b709be6457e12d00300a6a596d4c6a3"
HARNESS_COMMIT = "f7bbbb2ccdf479001d6467c9e34af59e44a840f9"
INSTANCE_ID = "django__django-12419"
PARQUET_BYTES = 2_090_470
PARQUET_SHA256 = "43ed5a3d1d98da36472c1ade65ddd2085d7b4ff694fcaf6a023a07c5c1f32f21"
RAW_ROW_SHA256 = "ad8afd0cb5cff7ab1944e426088dca3a730c35ab3201ba73d35e150312bf36c3"
ROW_SHA256 = "6eea69026b82f8c17d1c2e299d39fada46d60acf6a9f39a4de20ab84749f1d37"
SEED_DIGEST = "b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471"
EVAL_SHA256 = "da94f6e6b371f5f4f929fd0e71d2de2aa38427429380e7a18dfdc4498e5e5cd7"
GOLD_SHA256 = "a1f6c1f9598eda33d4de4b85f018d759390b8e6c951af3f554b9df5b90ff7862"
TEST_SHA256 = "ee1374e13a6aaff38f08d96759e2f3d51a9c6d39a8b8820e30c9e74c4293af97"
KNOWN_BAD_SHA256 = "86f6e27cc48b291ae69b4cbd0af848a9af2ea76aba497d4a9eef0990e1722ab5"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
BASE_COMMIT = "7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
SETUP_COMMIT = "0668164b4ac93a5be79f5b87fae83c657124d9ab"
IMAGE = "swebench/sweb.eval.x86_64.django_1776_django-12419:latest"
SCHEMA = "axrun.swebench-django-assets@1"
RAW_FIELDS = frozenset(
    {
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "base_commit",
        "created_at",
        "difficulty",
        "environment_setup_commit",
        "hints_text",
        "instance_id",
        "patch",
        "problem_statement",
        "repo",
        "test_patch",
        "version",
    }
)
ROW_FIELDS = RAW_FIELDS | {"eval_script", "eval_type", "image", "log_parser"}
ASSET_NAMES = ("row.json", "gold.patch", "known_bad.patch", "empty.patch", "eval.sh", "test.patch")
KNOWN_BAD_PATCH = (
    b"diff --git a/axrun-oracle-known-bad.txt b/axrun-oracle-known-bad.txt\n"
    b"new file mode 100644\n"
    b"--- /dev/null\n"
    b"+++ b/axrun-oracle-known-bad.txt\n"
    b"@@ -0,0 +1 @@\n"
    b"+Unrelated candidate change for the unresolved control.\n"
)


class AssetError(ValueError):
    """Source identity, private storage, or an existing asset failed validation."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AssetError("JSON contains duplicate keys")
        value[key] = item
    return value


def _reject_constant(value: str) -> Any:
    raise AssetError(f"JSON contains non-finite value: {value}")


def _load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_pairs,
        parse_constant=_reject_constant,
    )


def _safe_git_env() -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "TMPDIR")
    env = {key: value for key in allowed if (value := os.environ.get(key)) is not None}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return env


def _git(checkout: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=False,
        capture_output=True,
        text=True,
        env=_safe_git_env(),
        timeout=15,
    )
    if result.returncode:
        raise AssetError(f"Git identity check failed: {' '.join(args)}")
    return result.stdout.strip()


def _check_harness(checkout: Path) -> Path:
    checkout = checkout.resolve(strict=True)
    if not (checkout / "swebench/harness/test_spec/test_spec.py").is_file():
        raise AssetError("official scorer source is missing")
    if Path(_git(checkout, "rev-parse", "--show-toplevel")) != checkout:
        raise AssetError("official scorer must be its own Git checkout")
    if _git(checkout, "rev-parse", "HEAD") != HARNESS_COMMIT:
        raise AssetError("official scorer revision differs from lock")
    if _git(checkout, "status", "--porcelain=v1", "--untracked-files=all"):
        raise AssetError("official scorer checkout must be clean")
    return checkout


@contextmanager
def _scorer_modules(checkout: Path) -> Generator[None]:
    # Import the pinned scorer's test-spec modules without importing its
    # unrelated data-collection package (which has optional dependencies).
    if any(name == "swebench" or name.startswith("swebench.") for name in sys.modules):
        raise AssetError("SWE-bench was imported before selecting the pinned scorer")
    names = ("swebench", "swebench.harness", "swebench.harness.test_spec")
    try:
        for name in names:
            module = types.ModuleType(name)
            module.__package__ = name
            module.__path__ = [str(checkout / name.replace(".", "/"))]
            sys.modules[name] = module
        yield
    finally:
        for name in tuple(sys.modules):
            if name == "swebench" or name.startswith("swebench."):
                del sys.modules[name]


def _official_enrichment(raw: dict[str, Any], checkout: Path) -> dict[str, Any]:
    with _scorer_modules(checkout):
        module = importlib.import_module("swebench.harness.test_spec.test_spec")
        parsers = importlib.import_module("swebench.harness.log_parsers")
        if module.__file__ is None or Path(module.__file__).resolve() != (
            checkout / "swebench/harness/test_spec/test_spec.py"
        ):
            raise AssetError("TestSpec imported from an unexpected source")
        if parsers.__file__ is None or Path(parsers.__file__).resolve() != (
            checkout / "swebench/harness/log_parsers/__init__.py"
        ):
            raise AssetError("log parser imported from an unexpected source")
        spec = module.make_test_spec(raw, namespace="swebench")
        parser = parsers.MAP_REPO_TO_PARSER.get(raw["repo"])
        if parser is None or parser.__name__ != "parse_log_django":
            raise AssetError("official Django log parser differs from lock")
        if spec.instance_image_key != IMAGE:
            raise AssetError("official TestSpec image differs from lock")
        row = dict(raw)
        row.update(
            FAIL_TO_PASS=spec.FAIL_TO_PASS,
            PASS_TO_PASS=spec.PASS_TO_PASS,
            image=spec.instance_image_key,
            eval_script=spec.eval_script,
            eval_type="pass_and_fail",
            log_parser=parser.__name__,
        )
        return row


def _read_raw_row(parquet_path: Path) -> dict[str, Any]:
    try:
        parquet = cast(Any, importlib.import_module("pyarrow.parquet"))
    except ImportError as exc:
        raise AssetError("PyArrow is required to read the caller-supplied Parquet") from exc
    if parquet_path.is_symlink() or not parquet_path.is_file():
        raise AssetError("pinned Parquet must be a regular file")
    data = parquet_path.read_bytes()
    if len(data) != PARQUET_BYTES or sha256(data) != PARQUET_SHA256:
        raise AssetError("pinned Parquet size or SHA-256 differs")
    rows = cast(
        list[Any],
        parquet.read_table(parquet_path, filters=[("instance_id", "==", INSTANCE_ID)]).to_pylist(),
    )
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise AssetError("pinned Parquet must contain exactly one Django row")
    raw = cast(dict[str, Any], rows[0])
    if set(raw) != set(RAW_FIELDS) or sha256(canonical_json(raw)) != RAW_ROW_SHA256:
        raise AssetError("pinned raw Django row differs")
    return raw


def _validate_row(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise AssetError("enriched row has missing or unknown fields")
    row = cast(dict[str, Any], row)
    if set(row) != set(ROW_FIELDS):
        raise AssetError("enriched row has missing or unknown fields")
    if sha256(canonical_json(row)) != ROW_SHA256:
        raise AssetError("enriched row SHA-256 differs from lock")
    expected = {
        "instance_id": INSTANCE_ID,
        "repo": "django/django",
        "base_commit": BASE_COMMIT,
        "environment_setup_commit": SETUP_COMMIT,
        "version": "3.1",
        "image": IMAGE,
        "eval_type": "pass_and_fail",
        "log_parser": "parse_log_django",
    }
    for key, value in expected.items():
        if row[key] != value:
            raise AssetError(f"enriched row {key} differs from lock")
    if row["FAIL_TO_PASS"] == [] or row["PASS_TO_PASS"] != []:
        raise AssetError("official Django test selection differs from lock")
    for key in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        cases_value = row[key]
        if not isinstance(cases_value, list):
            raise AssetError(f"{key} must be a string list")
        cases = cast(list[object], cases_value)
        if any(not isinstance(case, str) or not case for case in cases):
            raise AssetError(f"{key} must be a string list")
        strings = cast(list[str], cases)
        if len(strings) != len(set(strings)):
            raise AssetError(f"{key} has duplicate tests")
    for key, digest in (
        ("patch", GOLD_SHA256),
        ("eval_script", EVAL_SHA256),
        ("test_patch", TEST_SHA256),
    ):
        value = row[key]
        if not isinstance(value, str) or not value or sha256(value.encode()) != digest:
            raise AssetError(f"enriched row {key} differs from lock")
    seed = sha256(canonical_json({"dataset": DATASET, "row_schema": "enriched-v1", "row": row}))
    if seed != SEED_DIGEST:
        raise AssetError("Axrun seed digest differs from lock")
    return row


def load_locked_row(path: Path) -> dict[str, Any]:
    """Read an already prepared full row, rejecting any mutation or wrong instance."""
    if path.is_symlink() or not path.is_file():
        raise AssetError("private enriched row must be a regular file")
    try:
        row = _load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetError("private enriched row is unreadable") from exc
    return _validate_row(row)


def _private_output_dir(path: Path) -> Path:
    if not path.is_absolute():
        raise AssetError("output directory must be an explicit absolute path")
    if path.is_symlink():
        raise AssetError("output directory must not be a symlink")
    resolved = path.resolve()
    existing = resolved
    while not existing.exists():
        existing = existing.parent
    if not existing.is_dir():
        raise AssetError("output directory parent is not a directory")
    result = subprocess.run(
        ["git", "-C", str(existing), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
        env=_safe_git_env(),
        timeout=15,
    )
    if result.returncode == 0:
        root = Path(result.stdout.strip()).resolve()
        relative = resolved.relative_to(root)
        if not relative.parts or relative.parts[0] == ".git":
            raise AssetError("output may not target a Git root or metadata")
        tracked = _git(root, "ls-files", "--cached", "--", str(relative))
        if tracked:
            raise AssetError("output directory contains tracked Git files")
        ignored = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", "--no-index", "--", f"{relative}/"],
            check=False,
            capture_output=True,
            env=_safe_git_env(),
            timeout=15,
        )
        if ignored.returncode != 0:
            raise AssetError("output directory inside a Git checkout must be ignored")
    if resolved.exists() and (
        not resolved.is_dir() or stat.S_IMODE(resolved.stat().st_mode) & 0o077
    ):
        raise AssetError("existing output directory must be private (mode 0700)")
    return resolved


def _asset_payloads(row: dict[str, Any]) -> dict[str, bytes]:
    if sha256(KNOWN_BAD_PATCH) != KNOWN_BAD_SHA256 or sha256(b"") != EMPTY_SHA256:
        raise AssetError("generated negative-control patches differ from lock")
    return {
        "row.json": canonical_json(row),
        "gold.patch": row["patch"].encode(),
        "known_bad.patch": KNOWN_BAD_PATCH,
        "empty.patch": b"",
        "eval.sh": row["eval_script"].encode(),
        "test.patch": row["test_patch"].encode(),
    }


def _manifest(payloads: dict[str, bytes]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "dataset": {
            "identity": DATASET,
            "commit": DATASET_COMMIT,
            "parquet_bytes": PARQUET_BYTES,
            "parquet_sha256": PARQUET_SHA256,
            "raw_row_sha256": RAW_ROW_SHA256,
        },
        "scorer_commit": HARNESS_COMMIT,
        "instance_id": INSTANCE_ID,
        "row_schema": "enriched-v1",
        "row_sha256": ROW_SHA256,
        "seed_digest": SEED_DIGEST,
        "assets": {
            name: {"bytes": len(payloads[name]), "sha256": sha256(payloads[name])}
            for name in ASSET_NAMES
        },
    }


def _write_private(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise AssetError(f"private asset is a symlink: {path.name}")
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise AssetError(f"private asset differs: {path.name}")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise AssetError(f"private asset permissions are too broad: {path.name}")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def validate_assets(output_dir: Path) -> dict[str, Any]:
    """Validate prepared private bytes and manifest against compiled-in locks."""
    directory = _private_output_dir(output_dir)
    manifest_path = directory / "assets-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise AssetError("private asset manifest is missing")
    try:
        manifest = _load_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetError("private asset manifest is unreadable") from exc
    row = load_locked_row(directory / "row.json")
    payloads = _asset_payloads(row)
    if manifest != _manifest(payloads):
        raise AssetError("private asset manifest differs from lock")
    for name, payload in payloads.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise AssetError(f"private asset differs: {name}")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise AssetError(f"private asset permissions are too broad: {name}")
    if stat.S_IMODE(manifest_path.stat().st_mode) & 0o077:
        raise AssetError("private asset manifest permissions are too broad")
    return manifest


def prepare_assets(parquet_path: Path, harness_checkout: Path, output_dir: Path) -> dict[str, Any]:
    """Enrich exactly one pinned row and materialize private, tamper-checked assets."""
    directory = _private_output_dir(output_dir)
    checkout = _check_harness(harness_checkout)
    raw = _read_raw_row(parquet_path)
    row = _validate_row(_official_enrichment(raw, checkout))
    payloads = _asset_payloads(row)
    manifest = _manifest(payloads)
    payloads["assets-manifest.json"] = canonical_json(manifest) + b"\n"
    if not directory.exists():
        directory.mkdir(parents=True, mode=0o700)
        directory.chmod(0o700)
    for name, payload in payloads.items():
        _write_private(directory / name, payload)
    return validate_assets(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate"))
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--parquet", type=Path)
    parser.add_argument("--harness-checkout", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.parquet is None or args.harness_checkout is None:
            parser.error("prepare requires --parquet and --harness-checkout")
        result = prepare_assets(args.parquet, args.harness_checkout, args.assets_dir)
    else:
        result = validate_assets(args.assets_dir)
    print(
        canonical_json(
            {"schema_version": SCHEMA, "assets_manifest_sha256": sha256(canonical_json(result))}
        ).decode()
    )


if __name__ == "__main__":
    main()
