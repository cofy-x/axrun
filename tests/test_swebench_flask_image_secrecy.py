"""Closed image secrecy gate tests; no Docker or hidden benchmark assets."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).parents[1] / "tools/validation/swebench_flask_image_secrecy.py"
sys.path.insert(0, str(PATH.parent))
SPEC = importlib.util.spec_from_file_location("swebench_flask_image_secrecy", PATH)
assert SPEC and SPEC.loader
secrecy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(secrecy)

_ADDED = """diff --git a/tests/new.py b/tests/new.py
new file mode 100644
--- /dev/null
+++ b/tests/new.py
@@ -0,0 +1,2 @@
+def a_private_test():
+    assert expected_hidden_behavior()
"""
_MODIFIED = """diff --git a/tests/existing.py b/tests/existing.py
--- a/tests/existing.py
+++ b/tests/existing.py
@@ -1,2 +1,2 @@
 old()
-before()
+assert expected_hidden_behavior()
"""


def _safe_audit(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {key: 0 for key in secrecy._AUDIT_FIELDS}
    value.update({key: False for key in secrecy._BOOL_FIELDS})
    value.update(
        image_head=secrecy.IMAGE_HEAD,
        image_clean=True,
        row_base_present=True,
        filesystem_scan_complete=True,
        git_all_object_scan_complete=True,
        test_patch_forward_applies=True,
        gold_patch_forward_applies=True,
        test_target_count=2,
        gold_target_count=1,
        added_target_count=1,
        modified_target_count=1,
    )
    value.update(overrides)
    return value


def test_patch_parser_classifies_new_and_modified_targets_without_exposing_names() -> None:
    targets = secrecy._patch_targets_and_hunks(_ADDED + _MODIFIED)
    assert [target["operation"] for target in targets] == ["added", "modified"]
    assert all(target["unprovable_fragments"] == 0 for target in targets)
    assert base64.b64decode(targets[0]["added_fragments"][0]).startswith(b"def a_private_test")
    assert base64.b64decode(targets[1]["after_hunks"][0]).startswith(b"old()")


def test_short_or_ambiguous_added_fragment_blocks_even_with_changed_context() -> None:
    patch = _MODIFIED.replace("assert expected_hidden_behavior()", "ok()")
    target = secrecy._patch_targets_and_hunks(patch)[0]
    assert target["unprovable_fragments"] == 1
    assert target["added_fragments"] == []
    assert secrecy._status(_safe_audit(test_unprovable_fragment_count=1)) == (
        "blocked",
        "patch_content_history_unproven",
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"added_current_count": 1}, "new_test_target_reachable"),
        ({"added_history_count": 1}, "new_test_target_reachable"),
        ({"test_added_fragment_current_match_count": 1}, "test_added_content_reachable"),
        ({"test_added_hunk_history_match_count": 1}, "test_added_content_reachable"),
        ({"gold_added_fragment_history_match_count": 1}, "gold_added_content_reachable"),
        ({"gold_patch_reverse_applies": True}, "gold_patch_reachable"),
        ({"test_patch_id_in_history": True}, "test_patch_reachable"),
        ({"filesystem_scan_complete": False}, "full_image_scan_incomplete"),
        ({"git_all_object_scan_complete": False}, "full_image_scan_incomplete"),
        ({"test_full_filesystem_match_count": 1}, "test_added_content_reachable"),
        ({"gold_full_filesystem_match_count": 1}, "gold_added_content_reachable"),
        ({"test_all_git_object_match_count": 1}, "test_added_content_reachable"),
        ({"gold_all_git_object_match_count": 1}, "gold_added_content_reachable"),
        ({"test_patch_forward_applies": False}, "locked_patch_not_applicable_to_image"),
        ({"gold_patch_forward_applies": False}, "locked_patch_not_applicable_to_image"),
    ],
)
def test_secrecy_status_fails_closed(change: dict[str, object], reason: str) -> None:
    assert secrecy._status(_safe_audit(**change)) == ("blocked", reason)


def test_only_exact_complete_audit_shape_can_pass() -> None:
    assert secrecy._status(_safe_audit()) == (
        "passed",
        "no_locked_patch_signatures_reachable",
    )
    checked = secrecy._check_audit(_safe_audit(), 2)
    assert set(checked) == secrecy._AUDIT_FIELDS
    with pytest.raises(secrecy.SecrecyError, match="shape_invalid"):
        secrecy._check_audit({**checked, "hidden_path": "tests/secret"}, 2)
    with pytest.raises(secrecy.SecrecyError, match="boolean_invalid"):
        secrecy._check_audit({**checked, "image_clean": 1}, 2)
    with pytest.raises(secrecy.SecrecyError, match="target_count_invalid"):
        secrecy._check_audit({**checked, "test_target_count": 1}, 2)
    with pytest.raises(secrecy.SecrecyError, match="shape_invalid"):
        secrecy._check_audit(
            {key: value for key, value in checked.items() if key != "git_all_object_scan_complete"},
            2,
        )
    assert secrecy.SCHEMA.endswith("@2")


def test_private_config_is_closed_and_receipt_is_exclusive(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"row": "/private/row", "receipt": "/private/receipt"}))
    assert secrecy._config_paths(config) == (Path("/private/row"), Path("/private/receipt"))
    config.write_text('{"row":"/a","row":"/b","receipt":"/c"}')
    with pytest.raises(secrecy.SecrecyError, match="config_duplicate_key"):
        secrecy._config_paths(config)
    config.write_text(json.dumps({"row": "/a", "receipt": "/b", "extra": "leak"}))
    with pytest.raises(secrecy.SecrecyError, match="config_shape_invalid"):
        secrecy._config_paths(config)
    target = tmp_path / "receipt.json"
    secrecy._write_receipt(target, {"status": "blocked"})
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(secrecy.SecrecyError, match="receipt_path_invalid"):
        secrecy._write_receipt(target, {"status": "passed"})


def test_docker_inspection_is_pinned_readonly_offline_and_uses_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[list[str], bytes]] = []
    original_run = secrecy.subprocess.run
    audit = _safe_audit(test_target_count=1, modified_target_count=0)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if command[0] != "docker":
            return original_run(command, **kwargs)
        output = kwargs["stdout"]
        assert hasattr(output, "write")
        output.write(json.dumps(audit).encode())  # type: ignore[union-attr]
        payload = kwargs["input"]
        assert isinstance(payload, bytes)
        seen.append((command, payload))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(secrecy.subprocess, "run", fake_run)

    def no_cleanup(_name: str) -> None:
        return None

    monkeypatch.setattr(secrecy, "_ensure_removed", no_cleanup)
    result = secrecy._docker_audit("sha256:" + "a" * 64, {"patch": _MODIFIED, "test_patch": _ADDED})
    assert result["image_clean"] is True
    command, payload = seen[0]
    for required in ("--network", "none", "--read-only", "--pull", "never", "--log-driver"):
        assert required in command
    assert "--mount" not in command
    assert "--volume" not in command
    assert "sha256:" + "a" * 64 in command
    assert "a_private_test" not in " ".join(command)
    assert b"a_private_test" in payload
    assert "DEEPSEEK_API_KEY" not in secrecy.oracle.safe_subprocess_env()
    assert secrecy.AUDIT_TIMEOUT_SECONDS == 600


def test_cleanup_only_touches_named_container_and_confirms_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []
    name = "axrun-sweb-flask-secrecy-0123456789abcdef"

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"")

    monkeypatch.setattr(secrecy.subprocess, "run", fake_run)
    secrecy._ensure_removed(name)
    assert seen == [
        ["docker", "rm", "--force", name],
        ["docker", "ps", "--all", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"],
    ]
    with pytest.raises(secrecy.SecrecyError, match="cleanup_name_invalid"):
        secrecy._ensure_removed("unrelated-container")


def test_cleanup_fails_if_named_container_remains_or_inspection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "axrun-sweb-flask-secrecy-0123456789abcdef"

    def still_present(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        output = name.encode() if command[1] == "ps" else b""
        return subprocess.CompletedProcess(command, 0, stdout=output)

    monkeypatch.setattr(secrecy.subprocess, "run", still_present)
    with pytest.raises(secrecy.SecrecyError, match="cleanup_unconfirmed"):
        secrecy._ensure_removed(name)

    def inspection_failed(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 1 if command[1] == "ps" else 0, stdout=b"")

    monkeypatch.setattr(secrecy.subprocess, "run", inspection_failed)
    with pytest.raises(secrecy.SecrecyError, match="cleanup_unconfirmed"):
        secrecy._ensure_removed(name)


def test_container_code_is_syntax_checked() -> None:
    compile(secrecy._CONTAINER_CODE, "<flask-image-audit>", "exec")
    assert '"--batch-all-objects", "--batch"' in secrecy._CONTAINER_CODE
    assert 'os.walk("/", topdown=True, followlinks=False' in secrecy._CONTAINER_CODE
    assert 'root == "/"' in secrecy._CONTAINER_CODE
    assert 'name not in {"proc", "sys", "dev"}' in secrecy._CONTAINER_CODE
    assert 'name == ".git" and path != "/testbed/.git"' in secrecy._CONTAINER_CODE
    assert 'fail("additional_git_repository_unscanned")' in secrecy._CONTAINER_CODE


def test_stream_scanner_catches_boundary_spanning_signature() -> None:
    definitions = secrecy._CONTAINER_CODE.split("request = json.load(sys.stdin)", 1)[0]
    namespace: dict[str, object] = {}
    exec(compile(definitions, "<flask-image-audit-functions>", "exec"), namespace)
    namespace["SCAN_CHUNK_BYTES"] = 4
    scanner = namespace["scan_stream"]
    assert callable(scanner)
    payload = b"other-secret-content-more"
    assert scanner(
        io.BytesIO(payload), len(payload), {"test": (b"secret-content",), "gold": (b"absent",)}
    ) == {
        "test": True,
        "gold": False,
    }


def test_git_all_object_scanner_includes_dangling_blob(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "hash-object", "-w", "--stdin"],
        input=b"locked-private-signature\n",
        check=True,
        capture_output=True,
    )
    definitions = secrecy._CONTAINER_CODE.split("request = json.load(sys.stdin)", 1)[0]
    definitions = definitions.replace('cwd="/testbed"', f"cwd={str(tmp_path)!r}")
    namespace: dict[str, object] = {}
    exec(compile(definitions, "<flask-image-audit-functions>", "exec"), namespace)
    scanner = namespace["scan_git_objects"]
    assert callable(scanner)
    result: dict[str, object] = {}
    scanner(
        {"test": (b"locked-private-signature",), "gold": (b"absent",)},
        result,
    )
    assert result["git_all_object_scan_complete"] is True
    assert result["git_all_object_count"] == 1
    assert result["test_all_git_object_match_count"] == 1
    assert result["gold_all_git_object_match_count"] == 0
