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
