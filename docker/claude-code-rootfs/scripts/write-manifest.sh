#!/usr/bin/env bash
set -euo pipefail

. /tmp/architecture.env
: "${UBUNTU_BASE_IMAGE:?}"
installed_version="$(jq -r .version /opt/claude-code/npm/lib/node_modules/@anthropic-ai/claude-code/package.json)"
patched_elfs="$(jq -R -n '[inputs]' /tmp/claude-elfs.txt)"
dynamic_executables="$(jq -R -n '[inputs]' /tmp/claude-dynamic-executables.txt)"
in_place_elfs="$(jq -R -n '[inputs]' /tmp/claude-in-place-elfs.txt)"
jq -n \
  --arg schema_version 1 \
  --arg ubuntu_base_image "$UBUNTU_BASE_IMAGE" \
  --arg architecture "linux/$TARGETARCH" \
  --arg node_version "$NODE_VERSION" \
  --arg node_sha256 "$NODE_SHA256" \
  --arg claude_package_sha256 "$CLAUDE_PACKAGE_SHA256" \
  --arg claude_native_package "$CLAUDE_NATIVE_PACKAGE" \
  --arg claude_native_sha256 "$CLAUDE_NATIVE_SHA256" \
  --arg requested_claude_code_version "$CLAUDE_CODE_VERSION" \
  --arg installed_claude_code_version "$installed_version" \
  --arg runtime_version "$CLAUDE_RUNTIME_VERSION" \
  --arg canonical_mount_target /__claude_code \
  --arg canonical_entry /__claude_code/usr/local/bin/claude \
  --argjson patched_elfs "$patched_elfs" \
  --argjson dynamic_executables "$dynamic_executables" \
  --argjson in_place_elfs "$in_place_elfs" \
  '{schema_version: $schema_version, ubuntu_base_image: $ubuntu_base_image, architecture: $architecture, node_version: $node_version, node_sha256: $node_sha256, claude_package_sha256: $claude_package_sha256, claude_native_package: $claude_native_package, claude_native_sha256: $claude_native_sha256, requested_claude_code_version: $requested_claude_code_version, installed_claude_code_version: $installed_claude_code_version, runtime_version: $runtime_version, canonical_mount_target: $canonical_mount_target, canonical_entry: $canonical_entry, patched_elfs: $patched_elfs, dynamic_executables: $dynamic_executables, in_place_elfs: $in_place_elfs}' \
  > /opt/claude-code/manifest.json
