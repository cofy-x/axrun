"""Crash-safe caller-owned preparation state."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from axrun.errors import ContractError, RecoveryRequiredError
from axrun.preparation.models import (
    EnvironmentPreparationReceipt,
    PreparationRecord,
    PreparationState,
    SeedBuildReceipt,
    SeedBuildSpec,
)


class PreparationStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def initialize(self, spec: SeedBuildSpec, *, now: str) -> PreparationRecord:
        with self.lock(spec.preparation_id):
            existing = self.load_record(spec.preparation_id)
            if existing is not None:
                if existing.request_digest != spec.request_digest:
                    raise RecoveryRequiredError("persisted preparation request digest differs")
                return existing
            spec_path = self.spec_path(spec.preparation_id)
            if spec_path.exists():
                persisted = self.load_spec(spec.preparation_id)
                if persisted.request_digest != spec.request_digest:
                    raise RecoveryRequiredError("persisted preparation spec differs")
            else:
                _atomic_write(spec_path, _json(asdict(spec)))
            record = PreparationRecord(
                schema_version=1,
                preparation_id=spec.preparation_id,
                request_digest=spec.request_digest,
                state=PreparationState.NEW,
                created_at=now,
                updated_at=now,
            )
            self.save_record(record)
            return record

    def spec_path(self, preparation_id: str) -> Path:
        return self.root / "preparations" / preparation_id / "spec.json"

    def record_path(self, preparation_id: str) -> Path:
        return self.root / "preparations" / preparation_id / "record.json"

    def load_spec(self, preparation_id: str) -> SeedBuildSpec:
        raw = _object(json.loads(self.spec_path(preparation_id).read_text(encoding="utf-8")))
        return SeedBuildSpec(**raw)

    def load_record(self, preparation_id: str) -> PreparationRecord | None:
        path = self.record_path(preparation_id)
        if not path.exists():
            return None
        raw = _object(json.loads(path.read_text(encoding="utf-8")))
        raw["state"] = PreparationState(raw["state"])
        return PreparationRecord(**raw)

    def save_record(self, record: PreparationRecord) -> None:
        _atomic_write(self.record_path(record.preparation_id), _json(asdict(record)))

    def save_seed_receipt(self, preparation_id: str, receipt: SeedBuildReceipt) -> tuple[Path, str]:
        path = (
            self.root
            / "preparations"
            / preparation_id
            / "receipts"
            / f"seed-build-{receipt.digest}.json"
        )
        _atomic_write(path, _json(asdict(receipt)))
        return path, receipt.digest

    def save_preparation_receipt(self, receipt: EnvironmentPreparationReceipt) -> tuple[Path, str]:
        path = (
            self.root
            / "preparations"
            / receipt.preparation_id
            / "receipts"
            / f"environment-{receipt.digest}.json"
        )
        _atomic_write(path, _json(asdict(receipt)))
        return path, receipt.digest

    def load_preparation_receipt(self, record: PreparationRecord) -> EnvironmentPreparationReceipt:
        if not record.preparation_receipt:
            raise ContractError("preparation has no ready receipt")
        raw = _object(json.loads(Path(record.preparation_receipt).read_text(encoding="utf-8")))
        receipt = EnvironmentPreparationReceipt(**raw)
        if receipt.digest != record.preparation_receipt_digest:
            raise ContractError("preparation receipt digest mismatch")
        return receipt

    def load_seed_receipt(self, record: PreparationRecord) -> SeedBuildReceipt:
        if not record.seed_build_receipt:
            raise ContractError("preparation has no seed build receipt")
        raw = _object(json.loads(Path(record.seed_build_receipt).read_text(encoding="utf-8")))
        receipt = SeedBuildReceipt(**raw)
        if receipt.digest != record.seed_build_receipt_digest:
            raise ContractError("seed build receipt digest mismatch")
        return receipt

    @contextmanager
    def lock(self, preparation_id: str) -> Generator[None, None, None]:
        path = self.root / "locks" / f"preparation-{preparation_id}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def seed_build_spec_from_dict(raw: dict[str, Any]) -> SeedBuildSpec:
    expected = {
        "schema_version",
        "preparation_id",
        "source_uri",
        "source_digest",
        "recipe_digest",
        "destination",
        "target_role",
        "platform",
        "format",
        "idempotency_key",
        "environment_namespace",
        "working_directory",
        "labels",
    }
    if set(raw) != expected:
        raise ContractError("SeedBuildSpec has an invalid shape")
    return SeedBuildSpec(**raw)


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("preparation JSON must be an object")
    result: dict[str, Any] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            raise ContractError("preparation JSON keys must be strings")
        result[key] = item
    return result


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
