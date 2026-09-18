#!/usr/bin/env bash
set -euo pipefail

readonly claude_version=2.1.205
readonly node_version=22.23.2

usage() {
  cat >&2 <<'EOF'
Usage: verify-image.sh <amd64|arm64> [IMAGE]

Export IMAGE, mount that rootfs read-only at /__claude_code in an independent
container, and verify the common mount ABI, versions, ELF architecture and
PT_INTERP. IMAGE defaults to the tag emitted by build-local.sh.
EOF
  exit 2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
fi

readonly architecture="$1"
case "$architecture" in
  amd64)
    readonly elf_machine=62
    ;;
  arm64)
    readonly elf_machine=183
    ;;
  *)
    usage
    ;;
esac

readonly image="${2:-axrun-claude-code-rootfs:${claude_version}-${architecture}}"
readonly image_architecture="$(docker image inspect "$image" --format '{{.Architecture}}')"
if [[ "$image_architecture" != "$architecture" ]]; then
  echo "image architecture mismatch: expected $architecture, got $image_architecture" >&2
  exit 1
fi

readonly rootfs_dir="$(mktemp -d "${TMPDIR:-/tmp}/axrun-claude-rootfs.XXXXXX")"
container_id=""
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker rm -f "$container_id" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$rootfs_dir"
}
trap cleanup EXIT

container_id="$(docker create --platform "linux/$architecture" "$image")"
docker export "$container_id" | tar -xf - -C "$rootfs_dir"
docker rm "$container_id" >/dev/null
container_id=""

AXRUN_ROOTFS_DIR="$rootfs_dir" \
AXRUN_EXPECTED_ARCH="linux/$architecture" \
AXRUN_EXPECTED_ELF_MACHINE="$elf_machine" \
AXRUN_EXPECTED_CLAUDE_VERSION="$claude_version" \
AXRUN_EXPECTED_NODE_VERSION="$node_version" \
python3 - <<'PYTHON'
import json
import os
from pathlib import Path
import struct


root = Path(os.environ["AXRUN_ROOTFS_DIR"])
manifest = json.loads((root / "opt/claude-code/manifest.json").read_text())
assert manifest["architecture"] == os.environ["AXRUN_EXPECTED_ARCH"]
assert manifest["installed_claude_code_version"] == os.environ["AXRUN_EXPECTED_CLAUDE_VERSION"]
assert manifest["node_version"] == os.environ["AXRUN_EXPECTED_NODE_VERSION"]
assert manifest["canonical_mount_target"] == "/__claude_code"
assert manifest["canonical_entry"] == "/__claude_code/usr/local/bin/claude"

binary = root / "opt/claude-code/bin/claude-native"
data = binary.read_bytes()
assert data[:6] == bytes.fromhex("7f454c460201")
machine = struct.unpack_from("<H", data, 18)[0]
assert machine == int(os.environ["AXRUN_EXPECTED_ELF_MACHINE"]), machine

header_offset = struct.unpack_from("<Q", data, 32)[0]
header_size = struct.unpack_from("<H", data, 54)[0]
header_count = struct.unpack_from("<H", data, 56)[0]
interpreters = []
for index in range(header_count):
    offset = header_offset + index * header_size
    if struct.unpack_from("<I", data, offset)[0] != 3:
        continue
    file_offset = struct.unpack_from("<Q", data, offset + 8)[0]
    file_size = struct.unpack_from("<Q", data, offset + 32)[0]
    interpreters.append(data[file_offset : file_offset + file_size].rstrip(b"\0").decode())
assert interpreters == ["/__claude_code/l"], interpreters
PYTHON

docker run --rm \
  --platform "linux/$architecture" \
  --mount "type=bind,src=$rootfs_dir,dst=/__claude_code,readonly" \
  "$image" \
  /bin/sh -lc "
    set -eu
    test \"\$(/__claude_code/opt/claude-code/node/bin/node --version)\" = v${node_version}
    /__claude_code/usr/local/bin/claude --version | grep -F '${claude_version} (Claude Code)'
    if touch /__claude_code/readonly-probe 2>/dev/null; then exit 91; fi
  "

if docker image inspect "$image" --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -Eq '^LD_LIBRARY_PATH='; then
  echo "image config must not set LD_LIBRARY_PATH" >&2
  exit 1
fi

docker image inspect "$image" --format \
  'verified image_id={{.Id}} platform={{.Os}}/{{.Architecture}} claude=2.1.205 node=22.23.2 pt_interp=/__claude_code/l mount=readonly'
