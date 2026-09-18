#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dockerfile="$root/Dockerfile"

grep -Fq 'ARG CLAUDE_CODE_VERSION=2.1.205' "$dockerfile"
grep -Fq 'ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142' "$dockerfile"
grep -Fq 'ARG NODE_VERSION=22.23.2' "$dockerfile"
grep -Fq 'ARG NODE_SHA256=d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307' "$dockerfile"
grep -Fq 'test "$TARGETARCH" = amd64' "$dockerfile"
grep -Fq 'new = b"/__claude_code/l\0"' "$dockerfile"
grep -Fq 'unset LD_LIBRARY_PATH' "$dockerfile"
grep -Fq 'canonical_entry /__claude_code/usr/local/bin/claude' "$dockerfile"

if grep -Eq '(cr\.aliyuncs\.com|AKIA|token=|password=)' "$dockerfile"; then
    echo 'private registry or credential-like value found in Dockerfile' >&2
    exit 1
fi

printf '%s\n' 'Claude Code rootfs source contract verified'
