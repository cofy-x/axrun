#!/usr/bin/env bash
set -euo pipefail

. /tmp/architecture.env
: "${NODE_DIST_BASE_URL:?}"
: "${NPM_REGISTRY_URL:?}"
printf '%s\n' "$NODE_DIST_BASE_URL" | grep -Eq '^https://[^[:space:]]+$'
printf '%s\n' "$NPM_REGISTRY_URL" | grep -Eq '^https://[^[:space:]]+$'

node_archive="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
curl -fsSLo "/tmp/$node_archive" \
  "${NODE_DIST_BASE_URL%/}/v${NODE_VERSION}/$node_archive"
echo "$NODE_SHA256  /tmp/$node_archive" | sha256sum -c -
mkdir -p /opt/claude-code/node
tar -xJf "/tmp/$node_archive" --strip-components=1 -C /opt/claude-code/node
rm -f "/tmp/$node_archive"

package_dir=/opt/claude-code/npm/lib/node_modules/@anthropic-ai/claude-code
native_dir="/opt/claude-code/npm/lib/node_modules/@anthropic-ai/$CLAUDE_NATIVE_PACKAGE"
package_archive=/tmp/claude-code.tgz
native_archive="/tmp/$CLAUDE_NATIVE_PACKAGE.tgz"
curl -fsSLo "$package_archive" \
  "${NPM_REGISTRY_URL%/}/@anthropic-ai/claude-code/-/claude-code-${CLAUDE_CODE_VERSION}.tgz"
curl -fsSLo "$native_archive" \
  "${NPM_REGISTRY_URL%/}/@anthropic-ai/${CLAUDE_NATIVE_PACKAGE}/-/${CLAUDE_NATIVE_PACKAGE}-${CLAUDE_CODE_VERSION}.tgz"
echo "$CLAUDE_PACKAGE_SHA256  $package_archive" | sha256sum -c -
echo "$CLAUDE_NATIVE_SHA256  $native_archive" | sha256sum -c -
mkdir -p "$package_dir" "$native_dir"
tar -xzf "$package_archive" --strip-components=1 -C "$package_dir"
tar -xzf "$native_archive" --strip-components=1 -C "$native_dir"
test "$(node -p "require('${package_dir}/package.json').version")" = "$CLAUDE_CODE_VERSION"
test "$(node -p "require('${native_dir}/package.json').version")" = "$CLAUDE_CODE_VERSION"
native_cli="$native_dir/claude"
test -x "$native_cli"
mkdir -p /opt/claude-code/bin
cp "$native_cli" /opt/claude-code/bin/claude-native
chmod 0755 /opt/claude-code/bin/claude-native
node "$package_dir/cli-wrapper.cjs" --version | grep -F "$CLAUDE_CODE_VERSION (Claude Code)"
rm -f "$package_archive" "$native_archive"
