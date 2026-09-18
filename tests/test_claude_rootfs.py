import re
from pathlib import Path


def test_claude_205_rootfs_source_is_fixed_dual_arch_and_registry_neutral() -> None:
    dockerfile = (
        Path(__file__).parents[1] / "docker" / "claude-code-rootfs" / "Dockerfile"
    ).read_text(encoding="utf-8")
    required = {
        "ARG CLAUDE_CODE_VERSION=2.1.205",
        "ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142",
        "ARG NODE_VERSION=22.23.2",
        "ARG CLAUDE_PACKAGE_SHA256="
        "287e5ef2ec39e653cd78c356fb80a5c206241879bc17cefa42df5605b806db91",
        "ARG CLAUDE_NATIVE_AMD64_SHA256="
        "d3dadfa9cde294ac82c755eb6d889291228849180bac5d677ad1a4027aca1bc4",
        "ARG CLAUDE_NATIVE_ARM64_SHA256="
        "b9bee2e92869637ccf2d154ae09baaba561b7354b32f15ab8549a9b731b53847",
        "ARG NODE_AMD64_SHA256=d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307",
        "ARG NODE_ARM64_SHA256=fff4078c5def658577f92c88db7db3bc0072924bfb93fe52c1e744a54e94abb8",
        "ARG NODE_DIST_BASE_URL=https://nodejs.org/dist",
        "ARG NPM_REGISTRY_URL=https://registry.npmjs.org",
        "native_package=claude-code-linux-x64",
        "native_package=claude-code-linux-arm64",
        "source_interp=/lib64/ld-linux-x86-64.so.2",
        "source_interp=/lib/ld-linux-aarch64.so.1",
        '*) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 64 ;;',
        'new = b"/__claude_code/l\\0"',
        "unset LD_LIBRARY_PATH",
        "canonical_mount_target /__claude_code",
        "canonical_entry /__claude_code/usr/local/bin/claude",
    }
    assert all(value in dockerfile for value in required)
    architecture_case = re.search(
        r'case "\$TARGETARCH" in \\\n(?P<body>.*?)    esac;', dockerfile, re.DOTALL
    )
    assert architecture_case is not None
    assert set(re.findall(r"^      ([a-z0-9*]+)\)", architecture_case["body"], re.MULTILINE)) == {
        "amd64",
        "arm64",
        "*",
    }
    assert "ENV LD_LIBRARY_PATH" not in dockerfile
    forbidden = ("cr.aliyuncs.com", "AKIA", "token=", "password=", "_authToken")
    assert all(value not in dockerfile for value in forbidden)
