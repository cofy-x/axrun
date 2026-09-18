# django__django-12419 task images

## Canonical amd64 seed

`Dockerfile.amd64` derives the benchmark seed from the official SWE-bench image at its fixed
manifest digest. The upstream image contains the required commit but starts `/testbed` at an
environment snapshot commit. The thin Axrun seed checks out the row's exact base commit, removes
workspace-local state, and verifies system Python and Git without changing the official test
environment. Build it with:

```bash
docker build --platform linux/amd64 \
  --file docker/swebench-verified/django__django-12419/Dockerfile.amd64 \
  --tag swebench/sweb.eval.x86_64.django_1776_django-12419:axrun-seed-amd64 \
  docker/swebench-verified/django__django-12419
```

The derived tag deliberately retains the official repository identity required by the amd64
resolver contract. Axern's returned canonical digest, never this mutable local tag, is the runtime
identity.

## Local-development arm64 seed

This directory owns Axrun's self-contained `linux/arm64` local-development seed image for the
single qualified SWE-bench Verified instance `django__django-12419`. It does not replace the
official `linux/amd64` benchmark image and must not be reported as canonical leaderboard
acceptance.

The build definition is derived from the pinned official SWE-bench TestSpec. It preserves the
observable task ABI:

- repository: `django/django`;
- clean `/testbed` Git workspace;
- base commit: `7fa1a93c6c8109010a6ff3f604fda83b604e0e97`;
- Python 3.6 / Django 3.1 test environment;
- system Python 3 for Axrun-owned harness control code, isolated from the test environment;
- official row-owned test patch, evaluation script, and F2P/P2P grading remain outside the image.

The official cached environment file is not reused because it contains `linux-64` package names
and build strings. `environment-arm64.yml` pins the interpreter/toolchain while
`environment-arm64.lock` fixes every resolved conda artifact and MD5, and
`requirements-case.txt` contains the SHA-256-locked pure-Python runtime dependencies exercised by
this instance's single SQLite test. Optional dependencies for unrelated Django test modules are
deliberately excluded; empty and gold patch qualification is therefore part of this image's
acceptance contract. `artifacts.lock.json` records upstream provenance and fixed bootstrap
artifacts. The Dockerfile rejects every architecture except arm64.

Build and verify:

```bash
IMAGE=axrun-swebench-verified-django-12419:arm64-dev \
  docker/swebench-verified/django__django-12419/build-local.sh
```

The checked-in China-local profile selects the tested public mirrors without changing the source
identity, fixed commit, or checksums:

```bash
docker/swebench-verified/django__django-12419/build-local-cn.sh
```

Both entrypoints fetch the exact Django commit into an ephemeral build context on the caller, strip
the remote, and make the Dockerfile validate the clean detached Git seed again. No source checkout
or generated bundle is persisted in this directory. Every mirror value can still be overridden
explicitly when diagnosing transport failures.

The verification runs without a network and checks architecture, `/testbed`, exact Git HEAD,
clean status, Django version, and Git availability. Then qualify the image with the official row;
the script creates a fresh offline container for each candidate and requires empty to fail and gold
to pass through Axrun's packaged verifier:

```bash
docker/swebench-verified/django__django-12419/qualify-image.py \
  --row /path/to/django__django-12419.json
```

The source row remains dataset-owned. This directory persists only the reproducible image inputs,
provenance, and qualification procedure; it does not duplicate the problem statement, gold patch,
test patch, or evaluation script.

Import into the source Compose node using Axern's public development command:

```bash
IMAGE=axrun-swebench-verified-django-12419:arm64-dev \
  make -C ../axern local-compose-image-import
```

Use the canonical digest returned by Axern when creating the Environment. Never put a local
mutable tag into `ResolvedEpisode`. When resolving this local variant, pass both the canonical
digest and `--task-platform linux/arm64`; omitting the platform intentionally keeps the official
`linux/amd64` contract:

```bash
uv run axrun resolve-swebench-verified /path/to/django__django-12419.json \
  --task-image "$ARM64_TASK_IMAGE_DIGEST" \
  --task-platform linux/arm64 \
  ...
```
