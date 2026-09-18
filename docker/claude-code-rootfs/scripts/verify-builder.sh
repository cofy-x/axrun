#!/usr/bin/env bash
set -euo pipefail

. /tmp/architecture.env
cleanup() {
  rm -f /__claude_code "/$LIB_ALIAS" "/$USR_ALIAS" /l
}
trap cleanup EXIT
cp /tmp/claude-loader /l
ln -s "lib/$DEB_LIB_ARCH" "/$LIB_ALIAS"
ln -s "usr/lib/$DEB_LIB_ARCH" "/$USR_ALIAS"
ln -s / /__claude_code
env -u LD_LIBRARY_PATH /opt/claude-code/bin/claude-native --version \
  | grep -F "$CLAUDE_CODE_VERSION (Claude Code)"
