#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dockerfile="$root/Dockerfile"
lock="$root/artifacts.lock.json"
resolver="$root/scripts/resolve-architecture.py"
temporary=$(mktemp -d "${TMPDIR:-/tmp}/axrun-claude-source.XXXXXX")
trap 'rm -rf -- "$temporary"' EXIT

base_image=ubuntu:24.04@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea
for architecture in amd64 arm64; do
  python3 "$resolver" "$lock" "$architecture" "$temporary/$architecture.env" \
    --ubuntu-base-image "$base_image" \
    --claude-code-version 2.1.205 \
    --claude-runtime-version 2.1.205-20260812-234142 \
    --node-version 22.23.2
  grep -Fq "TARGETARCH=$architecture" "$temporary/$architecture.env"
done
if python3 "$resolver" "$lock" unknown "$temporary/unknown.env" \
  --ubuntu-base-image "$base_image" \
  --claude-code-version 2.1.205 \
  --claude-runtime-version 2.1.205-20260812-234142 \
  --node-version 22.23.2 >/dev/null 2>&1; then
  echo 'unknown TARGETARCH must fail closed' >&2
  exit 1
fi

grep -Fq 'COPY artifacts.lock.json /opt/axrun-build/artifacts.lock.json' "$dockerfile"
grep -Fq 'COPY scripts/resolve-architecture.py /opt/axrun-build/scripts/resolve-architecture.py' "$dockerfile"
grep -Fq 'io.axrun.claude-code.mount-target="/__claude_code"' "$dockerfile"
grep -Fq 'io.axrun.claude-code.entry="/__claude_code/usr/local/bin/claude"' "$dockerfile"
grep -Fq 'unset LD_LIBRARY_PATH' "$root/scripts/claude-launcher.sh"
grep -Fq 'new = b"/__claude_code/l\0"' "$root/scripts/patch-bun-interp.py"

if grep -Eq '(cr\.aliyuncs\.com|AKIA|token=|password=|_authToken|ENV[[:space:]]+LD_LIBRARY_PATH)' \
  "$dockerfile" "$lock" "$root"/scripts/*; then
  echo 'private registry, credential-like value, or global LD_LIBRARY_PATH found' >&2
  exit 1
fi
if grep -Eq '^(ADD|RUN cat >)[[:space:]]' "$dockerfile"; then
  echo 'Dockerfile must use explicit COPY and checked-in scripts' >&2
  exit 1
fi

printf '%s\n' 'Claude Code rootfs source contract verified'
