from pathlib import Path


def test_claude_205_rootfs_source_is_fixed_and_registry_neutral() -> None:
    dockerfile = (
        Path(__file__).parents[1] / "docker" / "claude-code-rootfs" / "Dockerfile"
    ).read_text(encoding="utf-8")
    required = {
        "ARG CLAUDE_CODE_VERSION=2.1.205",
        "ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142",
        "ARG NODE_VERSION=22.23.2",
        "ARG NODE_SHA256=d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307",
        'test "$TARGETARCH" = amd64',
        'new = b"/__claude_code/l\\0"',
        "unset LD_LIBRARY_PATH",
        "canonical_entry /__claude_code/usr/local/bin/claude",
    }
    assert all(value in dockerfile for value in required)
    assert "cr.aliyuncs.com" not in dockerfile
    assert (
        "sha256:9590ae7513cf0102446d301ec03b168c9dc33fbcfe14aed9c507072360e18e72" not in dockerfile
    )
