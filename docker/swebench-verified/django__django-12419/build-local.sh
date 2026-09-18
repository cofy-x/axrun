#!/usr/bin/env bash
set -euo pipefail

context_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
image="${IMAGE:-axrun-swebench-verified-django-12419:arm64-dev}"
django_repository="${DJANGO_REPOSITORY:-https://github.com/django/django.git}"
django_base_commit="7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
build_context="$(mktemp -d "${TMPDIR:-/tmp}/axrun-django-12419.XXXXXX")"
trap 'rm -rf "${build_context}"' EXIT

cp "${context_dir}/.dockerignore" "${build_context}/"
cp "${context_dir}/Dockerfile" "${build_context}/"
cp "${context_dir}/environment-arm64.yml" "${build_context}/"
cp "${context_dir}/environment-arm64.lock" "${build_context}/"
cp "${context_dir}/requirements-case.txt" "${build_context}/"
cp "${context_dir}/setup-repository.sh" "${build_context}/"
git init -q "${build_context}/testbed-source"
git -C "${build_context}/testbed-source" remote add origin "${django_repository}"
git -C "${build_context}/testbed-source" fetch --depth=1 origin "${django_base_commit}"
git -C "${build_context}/testbed-source" checkout -q --detach FETCH_HEAD
git -C "${build_context}/testbed-source" remote remove origin
test "$(git -C "${build_context}/testbed-source" rev-parse HEAD)" = "${django_base_commit}"
test -z "$(git -C "${build_context}/testbed-source" status --porcelain --untracked-files=all)"

build_args=(--build-arg TARGETARCH=arm64)
if [[ -n "${BUILD_NETWORK:-}" ]]; then
  build_args+=(--network "${BUILD_NETWORK}")
fi
if [[ -n "${APT_MIRROR:-}" ]]; then
  build_args+=(--build-arg "APT_MIRROR=${APT_MIRROR}")
fi
if [[ -n "${MINICONDA_BASE_URL:-}" ]]; then
  build_args+=(--build-arg "MINICONDA_BASE_URL=${MINICONDA_BASE_URL}")
fi
if [[ -n "${CONDAFORGE_CHANNEL_URL:-}" ]]; then
  build_args+=(--build-arg "CONDAFORGE_CHANNEL_URL=${CONDAFORGE_CHANNEL_URL}")
fi

docker buildx build \
  --platform linux/arm64 \
  "${build_args[@]}" \
  --load \
  --tag "${image}" \
  "${build_context}"

"${context_dir}/verify-image.sh" "${image}"
