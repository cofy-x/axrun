"""Private Flask Axern parity tool contract tests; no real benchmark assets or Runs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from axrun.models import canonical_digest

PATH = Path(__file__).parents[1] / "tools/validation/swebench_flask_axern_parity.py"
SPEC = importlib.util.spec_from_file_location("swebench_flask_axern_parity", PATH)
assert SPEC and SPEC.loader
sys.path.insert(0, str(PATH.parent))
parity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parity)
sys.path.pop(0)


def _write(path: Path, value: bytes) -> Path:
    path.write_bytes(value)
    return path


def _config(tmp_path: Path) -> dict[str, str]:
    return {
        "endpoint": "127.0.0.1:25000",
        "context_config": str(tmp_path / "context.json"),
        "row": str(tmp_path / "row.json"),
        "image_import_receipt": str(tmp_path / "image-import.json"),
        "wheelhouse": str(tmp_path / "wheelhouse"),
        "oracle_receipt": str(tmp_path / "oracle-receipt.json"),
        "gold_patch": str(tmp_path / "gold.patch"),
        "known_bad_patch": str(tmp_path / "known-bad.patch"),
        "official_gold_grade": str(tmp_path / "gold-grade.json"),
        "official_known_bad_grade": str(tmp_path / "known-bad-grade.json"),
        "official_empty_report": str(tmp_path / "empty-report.json"),
        "inference_environment_id": "env-inference",
        "verification_environment_id": "env-verification",
    }


def test_config_is_exact_closed_and_cannot_mix_flags(tmp_path: Path) -> None:
    config = _config(tmp_path)
    path = _write(tmp_path / "config.json", json.dumps(config).encode())
    parsed = parity._parse_args(["--config", str(path)])
    assert parsed.endpoint == "127.0.0.1:25000"
    assert parsed.row == tmp_path / "row.json"
    assert parsed.verification_environment_id == "env-verification"

    _write(path, json.dumps({**config, "model_credential": "forbidden"}).encode())
    with pytest.raises(parity.ValidationError, match="invalid_shape"):
        parity._parse_args(["--config", str(path)])
    with pytest.raises(SystemExit):
        parity._parse_args(["--config", str(path), "--endpoint", "127.0.0.1:25000"])


def test_official_row_uses_canonical_digest_not_file_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = {"instance_id": "private-fixture", "patch": "gold"}
    monkeypatch.setattr(parity, "_ROW_SHA256", canonical_digest(row))
    path = _write(tmp_path / "row.json", (json.dumps(row, indent=2) + "\n").encode())
    assert hashlib.sha256(path.read_bytes()).hexdigest() != canonical_digest(row)
    assert parity._official_row(path) == row
    _write(path, b'{"patch":"gold","patch":"gold","instance_id":"private-fixture"}')
    with pytest.raises(parity.ValidationError, match="duplicate_json_key"):
        parity._official_row(path)


def test_import_receipt_requires_exact_source_platform_and_runtime_digest(tmp_path: Path) -> None:
    runtime = f"index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:{'9' * 64}"
    value = {
        "source_ref": parity._SOURCE_IMAGE,
        "canonical_ref": parity._CANONICAL_SOURCE_IMAGE,
        "immutable_ref": runtime,
        "content_digest": f"sha256:{'9' * 64}",
        "platform": "linux/amd64",
    }
    path = _write(tmp_path / "import.json", json.dumps(value).encode())
    assert parity._image_import_receipt(path)["immutable_ref"] == runtime
    _write(path, json.dumps({**value, "platform": "linux/arm64"}).encode())
    with pytest.raises(parity.ValidationError, match="identity_mismatch"):
        parity._image_import_receipt(path)
    _write(path, json.dumps({**value, "credential": "forbidden"}).encode())
    with pytest.raises(parity.ValidationError, match="receipt_invalid"):
        parity._image_import_receipt(path)


def test_sealed_output_is_independently_checked_against_manifest(tmp_path: Path) -> None:
    data = b"sealed output"
    path = _write(tmp_path / "00-result.json", data)
    client = SimpleNamespace(
        get_sealed_output_manifest=lambda _run: [
            SimpleNamespace(
                path="/outputs/result.json",
                status="available",
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        ]
    )
    digest = hashlib.sha256(data).hexdigest()
    assert parity._sealed_summary(client, "run-1", "/outputs/result.json", path, digest) == {
        "bytes": len(data),
        "sha256": digest,
    }
    with pytest.raises(parity.ValidationError, match="digest_mismatch"):
        parity._sealed_summary(client, "run-1", "/outputs/result.json", path, "0" * 64)
    client.get_sealed_output_manifest = lambda _run: [
        SimpleNamespace(
            path="/outputs/result.json",
            status="available",
            size_bytes=len(data) + 1,
            sha256=digest,
        )
    ]
    with pytest.raises(parity.ValidationError, match="manifest_mismatch"):
        parity._sealed_summary(client, "run-1", "/outputs/result.json", path, digest)
    client.get_sealed_output_manifest = lambda _run: [
        SimpleNamespace(
            path="/outputs/result.json", status="available", size_bytes=len(data), sha256="0" * 64
        )
    ]
    with pytest.raises(parity.ValidationError, match="manifest_mismatch"):
        parity._sealed_summary(client, "run-1", "/outputs/result.json", path, digest)


def test_case_uses_formal_resolver_and_qualification_without_selection_escape_hatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def cli(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs["command"])
        if kwargs["command"][0] == "qualify":
            raise parity.ValidationError("stop_before_any_inference")
        return {"path": "private-spec"}

    monkeypatch.setattr(parity, "run_cli", cli)
    with pytest.raises(parity.ValidationError, match="stop_before_any_inference"):
        parity._case(
            case="gold",
            episode_id="new-episode",
            patch=tmp_path / "gold.patch",
            official=tmp_path / "official-grade.json",
            import_receipt={"immutable_ref": "fixed-runtime-image"},
            row_path=tmp_path / "private-row.json",
            image_import_receipt_path=tmp_path / "image-import.json",
            admission_receipt_path=tmp_path / "admission.json",
            context_config=tmp_path / "context.json",
            wheelhouse=tmp_path / "wheelhouse",
            inference_environment_id="env-i",
            verification_environment_id="env-v",
            client=SimpleNamespace(),
            store=parity.EpisodeStore(tmp_path / "state"),
            root=tmp_path,
            seen_runs=set(),
            seen_allocations=set(),
        )
    assert [command[0] for command in calls] == ["resolve-swebench-flask-official", "qualify"]
    resolve = calls[0]
    assert resolve[resolve.index("--admission-receipt") + 1] == str(tmp_path / "admission.json")
    assert resolve[resolve.index("--candidate-file") + 1] == str(tmp_path / "gold.patch")
    assert resolve[resolve.index("--harness") + 1] == "static-candidate"
    assert not hasattr(parity, "_selection")


def test_cli_context_transport_is_explicit_without_custom_client_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = {
        "current_context": "local",
        "contexts": {
            "local": {
                "endpoint": "127.0.0.1:25000",
                "proxy_mode": "direct",
                "tls": {
                    "ca_cert": "caller-ca",
                    "cert": "caller-cert",
                    "key": "caller-key-path",
                    "server_name": "gatewayd",
                },
            }
        },
    }
    path = _write(tmp_path / "context.json", json.dumps(context).encode())
    calls: list[tuple[str, str]] = []
    fake_client = SimpleNamespace()

    def client(path_value: str, name: str) -> SimpleNamespace:
        calls.append((path_value, name))
        return fake_client

    monkeypatch.setattr(parity.AxernClient, "from_context", client)
    assert parity._client("127.0.0.1:25000", path) is fake_client
    assert calls == [(str(path), "local")]
    context["contexts"]["local"]["tls"].pop("server_name")
    _write(path, json.dumps(context).encode())
    with pytest.raises(parity.ValidationError, match="transport_contract_missing"):
        parity._client("127.0.0.1:25000", path)
    assert len(calls) == 1


@pytest.mark.parametrize("fail_on", [None, "known_bad"])
def test_main_runs_fixed_case_order_without_key_or_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail_on: str | None,
) -> None:
    config = _config(tmp_path)
    row = {"patch": "synthetic gold patch"}
    _write(Path(config["row"]), (json.dumps(row) + "\n").encode())
    monkeypatch.setattr(parity, "_ROW_SHA256", canonical_digest(row))
    fake_files = {
        "oracle_receipt": b"private receipt",
        "gold_patch": row["patch"].encode(),
        "known_bad_patch": b"private known bad patch",
        "official_gold_grade": b"private gold grade",
        "official_known_bad_grade": b"private bad grade",
        "official_empty_report": b"private empty report",
    }
    constants = {
        "oracle_receipt": "_ORACLE_RECEIPT_SHA256",
        "gold_patch": "_GOLD_PATCH_SHA256",
        "known_bad_patch": "_KNOWN_BAD_PATCH_SHA256",
        "official_gold_grade": "_GOLD_GRADE_SHA256",
        "official_known_bad_grade": "_KNOWN_BAD_GRADE_SHA256",
        "official_empty_report": "_EMPTY_REPORT_SHA256",
    }
    for name, content in fake_files.items():
        _write(Path(config[name]), content)
        monkeypatch.setattr(parity, constants[name], hashlib.sha256(content).hexdigest())
    runtime = f"index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:{'9' * 64}"
    _write(
        Path(config["image_import_receipt"]),
        json.dumps(
            {
                "source_ref": parity._SOURCE_IMAGE,
                "canonical_ref": parity._CANONICAL_SOURCE_IMAGE,
                "immutable_ref": runtime,
                "content_digest": f"sha256:{'9' * 64}",
                "platform": "linux/amd64",
            }
        ).encode(),
    )
    config_path = _write(tmp_path / "config.json", json.dumps(config).encode())
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    monkeypatch.setattr(parity, "_private_root", lambda: evidence)
    monkeypatch.setattr(parity, "_check_host_and_sdk", lambda: None)
    monkeypatch.setattr(parity, "_check_environment", lambda *_args: None)
    closed: list[bool] = []
    monkeypatch.setattr(
        parity, "_client", lambda *_args: SimpleNamespace(close=lambda: closed.append(True))
    )
    calls: list[str] = []

    def fake_case(**kwargs: Any) -> dict[str, Any]:
        case = str(kwargs["case"])
        calls.append(case)
        if case == fail_on:
            raise parity.ValidationError("official_test_level_parity_mismatch")
        return {"case": case, "parity": {"parity": True}}

    monkeypatch.setattr(parity, "_case", fake_case)
    admission_calls: list[list[str]] = []

    def fake_cli(**kwargs: Any) -> dict[str, Any]:
        command = kwargs["command"]
        admission_calls.append(command)
        assert command[0] == "admit-swebench-flask-image"
        assert "DEEPSEEK_API_KEY" not in parity.os.environ
        output = Path(command[command.index("--output") + 1])
        output.write_bytes(b"private model-free admission")
        return {"status": "passed"}

    monkeypatch.setattr(parity, "run_cli", fake_cli)
    monkeypatch.setattr(
        sys, "argv", ["swebench_flask_axern_parity.py", "--config", str(config_path)]
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "SECRET-SENTINEL-NEVER-PRINT")
    previous_umask = parity.os.umask(0o077)
    parity.os.umask(previous_umask)
    try:
        outcome = parity.main()
    finally:
        parity.os.umask(previous_umask)
    receipt = json.loads((evidence / "receipt.json").read_text(encoding="utf-8"))
    assert "DEEPSEEK_API_KEY" not in parity.os.environ
    assert closed == [True]
    assert calls == (["gold", "known_bad"] if fail_on else ["gold", "known_bad", "empty"])
    assert outcome == (1 if fail_on else 0)
    assert receipt["status"] == ("failed_closed" if fail_on else "complete")
    assert receipt["schema_version"] == "axrun.swebench-flask-axern-parity@2"
    assert len(admission_calls) == 1
    assert receipt["admission_receipt"] == "admission.json"
    assert (
        receipt["admission_receipt_sha256"]
        == hashlib.sha256(b"private model-free admission").hexdigest()
    )
    assert receipt["execution_path"] == "formal_cli"
    assert "SECRET-SENTINEL" not in capsys.readouterr().out
    assert "SECRET-SENTINEL" not in json.dumps(receipt)
