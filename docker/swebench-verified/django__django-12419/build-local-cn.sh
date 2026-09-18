#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

export APT_MIRROR="${APT_MIRROR:-http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports}"
export MINICONDA_BASE_URL="${MINICONDA_BASE_URL:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda}"
export CONDAFORGE_CHANNEL_URL="${CONDAFORGE_CHANNEL_URL:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge}"
export DJANGO_REPOSITORY="${DJANGO_REPOSITORY:-https://ghproxy.net/https://github.com/django/django.git}"
export IMAGE="${IMAGE:-axrun-swebench-verified-django-12419:arm64-dev}"

exec "${script_dir}/build-local.sh"
