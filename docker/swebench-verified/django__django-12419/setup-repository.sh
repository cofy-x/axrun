#!/usr/bin/env bash
set -euo pipefail

: "${DJANGO_BASE_COMMIT:?DJANGO_BASE_COMMIT is required}"

test "$(git -C /testbed rev-parse HEAD)" = "${DJANGO_BASE_COMMIT}"
test -z "$(git -C /testbed remote)"
test -z "$(git -C /testbed status --porcelain --untracked-files=all)"
git -C /testbed config user.email setup@axrun.invalid
git -C /testbed config user.name "Axrun SWE-bench seed"

python -m pip install --no-deps --editable /testbed

test "$(git -C /testbed rev-parse HEAD)" = "${DJANGO_BASE_COMMIT}"
test -z "$(git -C /testbed status --porcelain --untracked-files=all)"
chmod -R a+rwX /testbed
