#!/usr/bin/env bash
set -euo pipefail

readonly claude_version=2.1.205
readonly script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat >&2 <<'EOF'
Usage: build-local.sh <amd64|arm64> [--mirror]

Build and load the selected Claude Code rootfs into the local Docker engine.
Official public origins remain the default. --mirror explicitly selects the
npmmirror transports while retaining the Dockerfile's pinned checksums.
EOF
  exit 2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
fi

readonly architecture="$1"
case "$architecture" in
  amd64 | arm64) ;;
  *) usage ;;
esac

mirror_args=()
if [[ $# -eq 2 ]]; then
  if [[ "$2" != --mirror ]]; then
    usage
  fi
  mirror_args=(
    --build-arg NODE_DIST_BASE_URL=https://npmmirror.com/mirrors/node
    --build-arg NPM_REGISTRY_URL=https://registry.npmmirror.com
  )
fi

readonly image="axrun-claude-code-rootfs:${claude_version}-${architecture}"

docker buildx build \
  --platform "linux/${architecture}" \
  "${mirror_args[@]}" \
  --load \
  --tag "$image" \
  "$script_dir"

docker image inspect "$image" --format \
  'built {{.RepoTags}} image_id={{.Id}} platform={{.Os}}/{{.Architecture}}'
