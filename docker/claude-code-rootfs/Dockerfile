ARG UBUNTU_BASE_IMAGE=ubuntu:24.04@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea

FROM ${UBUNTU_BASE_IMAGE} AS builder

ARG CLAUDE_CODE_VERSION=2.1.205
ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142
ARG NODE_VERSION=22.23.2
ARG NODE_SHA256=d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307
ARG UBUNTU_BASE_IMAGE
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    test "$TARGETARCH" = amd64; \
    test "$CLAUDE_CODE_VERSION" = 2.1.205; \
    test "$CLAUDE_RUNTIME_VERSION" = 2.1.205-20260812-234142; \
    test "$NODE_VERSION" = 22.23.2; \
    printf '%s\n' "$NODE_SHA256" | grep -Eq '^[0-9a-f]{64}$'; \
    printf '%s\n' "$UBUNTU_BASE_IMAGE" | grep -Eq '@sha256:[0-9a-f]{64}$'

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      binutils \
      ca-certificates \
      curl \
      file \
      jq \
      libgcc-s1 \
      libstdc++6 \
      patchelf \
      python3-minimal \
      xz-utils \
 && rm -rf /var/lib/apt/lists/*

ARG NODE_DIST_BASE_URL=https://nodejs.org/dist
ARG NPM_REGISTRY_URL=https://registry.npmjs.org

RUN set -eux; \
    printf '%s\n' "$NODE_DIST_BASE_URL" | grep -Eq '^https://[^[:space:]]+$'; \
    printf '%s\n' "$NPM_REGISTRY_URL" | grep -Eq '^https://[^[:space:]]+$'; \
    archive="node-v${NODE_VERSION}-linux-x64.tar.xz"; \
    curl -fsSLo "/tmp/$archive" "${NODE_DIST_BASE_URL%/}/v${NODE_VERSION}/$archive"; \
    echo "$NODE_SHA256  /tmp/$archive" | sha256sum -c -; \
    mkdir -p /opt/claude-code/node; \
    tar -xJf "/tmp/$archive" --strip-components=1 -C /opt/claude-code/node; \
    rm -f "/tmp/$archive"

ENV PATH=/opt/claude-code/node/bin:${PATH}

RUN set -eux; \
    npm install --registry "$NPM_REGISTRY_URL" --global --prefix /opt/claude-code/npm "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION"; \
    package_dir=/opt/claude-code/npm/lib/node_modules/@anthropic-ai/claude-code; \
    test "$(node -p "require('${package_dir}/package.json').version")" = "$CLAUDE_CODE_VERSION"; \
    native_cli="$(find "$package_dir" -type f -path '*/claude-code-linux-x64/claude' -print -quit)"; \
    test -n "$native_cli"; \
    mkdir -p /opt/claude-code/bin; \
    cp "$native_cli" /opt/claude-code/bin/claude-native; \
    chmod 0755 /opt/claude-code/bin/claude-native; \
    node "$package_dir/cli-wrapper.cjs" --version | grep -F "$CLAUDE_CODE_VERSION (Claude Code)"

RUN cat > /usr/local/bin/patch-bun-in-place <<'PYTHON'
#!/usr/bin/python3
import pathlib
import struct
import sys


path = pathlib.Path(sys.argv[1])
data = bytearray(path.read_bytes())
old = b"/lib64/ld-linux-x86-64.so.2\0"
new = b"/__claude_code/l\0"

if data[:6] != b"\x7fELF\x02\x01":
    raise SystemExit(f"expected a little-endian ELF64 file: {path}")

program_header_offset = struct.unpack_from("<Q", data, 32)[0]
program_header_size = struct.unpack_from("<H", data, 54)[0]
program_header_count = struct.unpack_from("<H", data, 56)[0]
if program_header_size != 56:
    raise SystemExit(f"unexpected ELF64 program header size: {program_header_size}")

interpreters = []
for index in range(program_header_count):
    offset = program_header_offset + index * program_header_size
    if struct.unpack_from("<I", data, offset)[0] != 3:
        continue
    file_offset = struct.unpack_from("<Q", data, offset + 8)[0]
    file_size = struct.unpack_from("<Q", data, offset + 32)[0]
    interpreters.append((file_offset, file_size))

if len(interpreters) != 1:
    raise SystemExit(f"expected one PT_INTERP in {path}, got {len(interpreters)}")

file_offset, file_size = interpreters[0]
if bytes(data[file_offset:file_offset + file_size]) != old:
    raise SystemExit(f"unexpected PT_INTERP contents in {path}")
if len(new) > file_size:
    raise SystemExit("replacement interpreter does not fit PT_INTERP")

data[file_offset:file_offset + file_size] = new.ljust(file_size, b"\0")
path.write_bytes(data)
PYTHON

RUN cat > /usr/local/bin/patch-loader-in-place <<'PYTHON'
#!/usr/bin/python3
import pathlib
import sys


path = pathlib.Path(sys.argv[1])
data = path.read_bytes()
replacements = (
    (b"/usr/lib/x86_64-linux-gnu/", b"/__claude_code/glibc00000/", 2),
    (b"/lib/x86_64-linux-gnu/", b"/__claude_code/glibc0/", 2),
    (b"/etc/ld.so.cache", b"/__claude_code/c", 2),
)
for old, new, expected_count in replacements:
    if len(old) != len(new):
        raise SystemExit(f"loader replacement length mismatch: {old!r} -> {new!r}")
    if data.count(old) != expected_count:
        raise SystemExit(f"unexpected loader string count for {old!r}")
    data = data.replace(old, new)
path.write_bytes(data)
PYTHON

RUN set -eux; \
    chmod 0755 /usr/local/bin/patch-bun-in-place /usr/local/bin/patch-loader-in-place; \
    cp --dereference /lib64/ld-linux-x86-64.so.2 /tmp/claude-loader; \
    /usr/local/bin/patch-loader-in-place /tmp/claude-loader; \
    chmod 0755 /tmp/claude-loader

RUN cat > /usr/local/bin/patch-claude-elfs <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

root=/opt/claude-code
loader=/__claude_code/l
canonical_rpath=/__claude_code/opt/claude-code/lib:/__claude_code/lib/x86_64-linux-gnu:/__claude_code/lib64:/__claude_code/usr/lib/x86_64-linux-gnu:/__claude_code/usr/lib
elf_list=/tmp/claude-elfs.txt
executable_list=/tmp/claude-dynamic-executables.txt
in_place_list=/tmp/claude-in-place-elfs.txt
: > "$elf_list"
: > "$executable_list"
: > "$in_place_list"

while IFS= read -r -d '' path; do
    if ! file -b -- "$path" | grep -q '^ELF'; then
        continue
    fi
    relative_path="${path#/}"
    printf '%s\n' "$relative_path" >> "$elf_list"
    case "$path" in
        /opt/claude-code/bin/claude-native|*/claude-code-linux-x64/claude)
            size_before="$(stat -c %s "$path")"
            /usr/local/bin/patch-bun-in-place "$path"
            test "$(stat -c %s "$path")" = "$size_before"
            test "$(patchelf --print-interpreter "$path")" = "$loader"
            printf '%s\n' "$relative_path" >> "$executable_list"
            printf '%s\n' "$relative_path" >> "$in_place_list"
            continue
            ;;
    esac
    old_rpath="$(patchelf --print-rpath "$path" 2>/dev/null || true)"
    if [ -n "$old_rpath" ]; then
        patchelf --force-rpath --set-rpath "${old_rpath}:${canonical_rpath}" "$path"
    else
        patchelf --force-rpath --set-rpath "$canonical_rpath" "$path"
    fi
    interpreter="$(patchelf --print-interpreter "$path" 2>/dev/null || true)"
    if [ -n "$interpreter" ]; then
        patchelf --set-interpreter "$loader" "$path"
        printf '%s\n' "$relative_path" >> "$executable_list"
        test "$(patchelf --print-interpreter "$path")" = "$loader"
    fi
    patchelf --print-rpath "$path" | grep -Fq '/__claude_code/'
done < <(find "$root" -type f -print0)

sort -u -o "$elf_list" "$elf_list"
sort -u -o "$executable_list" "$executable_list"
sort -u -o "$in_place_list" "$in_place_list"
test -s "$elf_list"
test -s "$executable_list"
test -s "$in_place_list"
SCRIPT

RUN chmod 0755 /usr/local/bin/patch-claude-elfs \
 && /usr/local/bin/patch-claude-elfs

RUN set -eux; \
    cp /tmp/claude-loader /l; \
    ln -s lib/x86_64-linux-gnu /glibc0; \
    ln -s usr/lib/x86_64-linux-gnu /glibc00000; \
    ln -s / /__claude_code; \
    env -u LD_LIBRARY_PATH /opt/claude-code/bin/claude-native --version \
      | grep -F "$CLAUDE_CODE_VERSION (Claude Code)"; \
    rm /__claude_code /glibc0 /glibc00000 /l

RUN cat > /usr/local/bin/claude <<'WRAPPER'
#!/bin/sh
set -eu
root=/__claude_code
manifest="$root/opt/claude-code/manifest.json"
native_cli="$root/opt/claude-code/bin/claude-native"
node="$root/opt/claude-code/node/bin/node"
js_entry="$root/opt/claude-code/npm/lib/node_modules/@anthropic-ai/claude-code/cli-wrapper.cjs"
if [ ! -r "$manifest" ]; then
    echo "error: Claude Code rootfs must be mounted at /__claude_code" >&2
    exit 126
fi
if [ -n "${CLAUDE_GLIBC_LOADER:-}" ] || [ -n "${CLAUDE_GLIBC_LIBRARY_PATH:-}" ]; then
    echo "error: external Claude glibc overrides are not supported" >&2
    exit 126
fi
unset LD_LIBRARY_PATH
export SSL_CERT_FILE="$root/etc/ssl/certs/ca-certificates.crt"
if [ -x "$native_cli" ]; then
    exec "$native_cli" "$@"
fi
exec "$node" "$js_entry" "$@"
WRAPPER

RUN set -eux; \
    chmod 0755 /usr/local/bin/claude; \
    installed_version="$(jq -r .version /opt/claude-code/npm/lib/node_modules/@anthropic-ai/claude-code/package.json)"; \
    patched_elfs="$(jq -R -n '[inputs]' /tmp/claude-elfs.txt)"; \
    dynamic_executables="$(jq -R -n '[inputs]' /tmp/claude-dynamic-executables.txt)"; \
    in_place_elfs="$(jq -R -n '[inputs]' /tmp/claude-in-place-elfs.txt)"; \
    jq -n \
      --arg schema_version 1 \
      --arg ubuntu_base_image "$UBUNTU_BASE_IMAGE" \
      --arg architecture linux/amd64 \
      --arg node_version "$NODE_VERSION" \
      --arg node_sha256 "$NODE_SHA256" \
      --arg requested_claude_code_version "$CLAUDE_CODE_VERSION" \
      --arg installed_claude_code_version "$installed_version" \
      --arg runtime_version "$CLAUDE_RUNTIME_VERSION" \
      --arg canonical_mount_target /__claude_code \
      --arg canonical_entry /__claude_code/usr/local/bin/claude \
      --argjson patched_elfs "$patched_elfs" \
      --argjson dynamic_executables "$dynamic_executables" \
      --argjson in_place_elfs "$in_place_elfs" \
      '{schema_version: $schema_version, ubuntu_base_image: $ubuntu_base_image, architecture: $architecture, node_version: $node_version, node_sha256: $node_sha256, requested_claude_code_version: $requested_claude_code_version, installed_claude_code_version: $installed_claude_code_version, runtime_version: $runtime_version, canonical_mount_target: $canonical_mount_target, canonical_entry: $canonical_entry, patched_elfs: $patched_elfs, dynamic_executables: $dynamic_executables, in_place_elfs: $in_place_elfs}' \
      > /opt/claude-code/manifest.json

FROM ${UBUNTU_BASE_IMAGE}

ARG CLAUDE_CODE_VERSION=2.1.205
ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libgcc-s1 libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/claude-code /opt/claude-code
COPY --from=builder /usr/local/bin/claude /usr/local/bin/claude
COPY --from=builder /tmp/claude-loader /l

RUN ln -s lib/x86_64-linux-gnu /glibc0 \
 && ln -s usr/lib/x86_64-linux-gnu /glibc00000

LABEL io.axrun.claude-code.version="$CLAUDE_CODE_VERSION" \
      io.axrun.claude-runtime.version="$CLAUDE_RUNTIME_VERSION" \
      io.axrun.claude-code.mount-target="/__claude_code" \
      io.axrun.claude-code.entry="/__claude_code/usr/local/bin/claude" \
      io.axrun.claude-code.rootfs="ubuntu-24.04"
