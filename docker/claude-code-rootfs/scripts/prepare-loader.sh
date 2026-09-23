#!/usr/bin/env bash
set -euo pipefail

. /tmp/architecture.env
cp --dereference "$SOURCE_INTERP" /tmp/claude-loader
python3 /opt/axrun-build/scripts/patch-loader.py \
  /tmp/claude-loader "$DEB_LIB_ARCH" "$LIB_ALIAS" "$USR_ALIAS"
chmod 0755 /tmp/claude-loader
