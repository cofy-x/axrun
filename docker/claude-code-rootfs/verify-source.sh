#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dockerfile="$root/Dockerfile"

grep -Fq 'ARG CLAUDE_CODE_VERSION=2.1.205' "$dockerfile"
grep -Fq 'ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142' "$dockerfile"
grep -Fq 'ARG NODE_VERSION=22.23.2' "$dockerfile"
grep -Fq 'ARG CLAUDE_PACKAGE_SHA256=287e5ef2ec39e653cd78c356fb80a5c206241879bc17cefa42df5605b806db91' "$dockerfile"
grep -Fq 'ARG CLAUDE_NATIVE_AMD64_SHA256=d3dadfa9cde294ac82c755eb6d889291228849180bac5d677ad1a4027aca1bc4' "$dockerfile"
grep -Fq 'ARG CLAUDE_NATIVE_ARM64_SHA256=b9bee2e92869637ccf2d154ae09baaba561b7354b32f15ab8549a9b731b53847' "$dockerfile"
grep -Fq 'ARG NODE_AMD64_SHA256=d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307' "$dockerfile"
grep -Fq 'ARG NODE_ARM64_SHA256=fff4078c5def658577f92c88db7db3bc0072924bfb93fe52c1e744a54e94abb8' "$dockerfile"
grep -Fq 'native_package=claude-code-linux-x64' "$dockerfile"
grep -Fq 'native_package=claude-code-linux-arm64' "$dockerfile"
grep -Fq '*) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 64 ;;' "$dockerfile"
grep -Fq 'new = b"/__claude_code/l\0"' "$dockerfile"
grep -Fq 'unset LD_LIBRARY_PATH' "$dockerfile"
grep -Fq 'canonical_mount_target /__claude_code' "$dockerfile"
grep -Fq 'canonical_entry /__claude_code/usr/local/bin/claude' "$dockerfile"

if grep -Eq '(cr\.aliyuncs\.com|AKIA|token=|password=|_authToken|ENV[[:space:]]+LD_LIBRARY_PATH)' "$dockerfile"; then
    echo 'private registry or credential-like value found in Dockerfile' >&2
    exit 1
fi

printf '%s\n' 'Claude Code rootfs source contract verified'
