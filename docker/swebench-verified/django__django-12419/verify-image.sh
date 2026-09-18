#!/usr/bin/env bash
set -euo pipefail

image="${1:-${IMAGE:-axrun-swebench-verified-django-12419:arm64-dev}}"
base_commit="7fa1a93c6c8109010a6ff3f604fda83b604e0e97"

test "$(docker image inspect "${image}" --format '{{.Architecture}}')" = arm64

docker run --rm --platform linux/arm64 --network none "${image}" bash -euo pipefail -c '
  test "$(uname -m)" = aarch64
  test "$PWD" = /testbed
  test "$(git rev-parse HEAD)" = "'"${base_commit}"'"
  test -z "$(git status --porcelain --untracked-files=all)"
  python -c "import django; assert django.VERSION[:2] == (3, 1)"
  git --version
'
