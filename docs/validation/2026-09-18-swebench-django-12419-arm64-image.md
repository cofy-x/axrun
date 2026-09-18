# SWE-bench Verified django__django-12419 arm64 image — 2026-09-18

This record covers a local-development `linux/arm64` task image. It does not replace or qualify the
official `linux/amd64` SWE-bench leaderboard image.

## Provenance and interpretation

- Axrun base commit: `817ee195f20d2d3221b1b10d17e9a0ef2667b88b`
- Axern source-cluster commit: `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`
- Openbench commit inspected: `a666534e83d8a4615d1b5841fb1475d9ab5b64a9`
- SWE-bench harness commit used by Openbench: `f7bbbb2ccdf479001d6467c9e34af59e44a840f9`
- Released SDK used for Axern validation: `axern-sdk==0.8.1`
- Dataset: `SWE-bench/SWE-bench_Verified`, instance `django__django-12419`
- Django base commit: `7fa1a93c6c8109010a6ff3f604fda83b604e0e97`
- Official amd64 image: `docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768`

Openbench delegates this row to the upstream SWE-bench `TestSpec`. That generator accepts an
explicit arm64 architecture and selects the aarch64 Miniconda bootstrap, but its cached environment
for this instance contains x86-only `linux-64` build strings. Axrun therefore does not relabel that
cache as arm64. The image pins Python 3.6.13 and the tooling environment, hash-locks the pure-Python
dependencies required by this row's single SQLite test, and proves semantic suitability through
the unchanged official eval script.

The dataset row remains external input. The build directory contains no problem statement, gold
patch, test patch, or eval script.

## Reproducible build

Default public-source build:

```bash
docker/swebench-verified/django__django-12419/build-local.sh
```

Checked-in China-local mirror profile:

```bash
docker/swebench-verified/django__django-12419/build-local-cn.sh
```

The mirror profile changes transport only. Ubuntu is selected by digest, Miniconda and Python
wheels are SHA-256 verified, and the temporary Django checkout is verified against the fixed Git
commit before and during the image build. The generated checkout exists only in an ephemeral build
context and has no remote in the final image.

- Local image: `axrun-swebench-verified-django-12419:arm64-dev`
- Local image ID: `sha256:1ec410172299f57c402216753d2c519af39a0509ebbe215619758e9a2400c3e5`
- Architecture: `linux/arm64`
- Python: `3.6.13`
- Django: `3.1`
- Git: `2.34.1`
- Workspace: clean detached `/testbed` at the fixed base commit

## Official-row qualification

The qualification script ran each candidate in a fresh container with `--network none` and used
Axrun's packaged SWE-bench verifier:

```bash
docker/swebench-verified/django__django-12419/qualify-image.py \
  --row /path/to/django__django-12419.json
```

| Candidate | Candidate SHA-256 | Resolved | Score | Diagnostic |
| --- | --- | --- | ---: | --- |
| empty | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | false | 0.0 | `SWEBENCH_TESTS_FAILED` |
| official gold | `a1f6c1f9598eda33d4de4b85f018d759390b8e6c951af3f554b9df5b90ff7862` | true | 1.0 | empty |

This run also found and fixed a pre-existing execution mismatch: the packaged verifier used newer
Python syntax even though this task resolves `python3` to Python 3.6. It is now intentionally
Python 3.6 compatible.

## Axern source-Compose truth path

The image was imported with Axern's public local-development target:

```bash
IMAGE=axrun-swebench-verified-django-12419:arm64-dev \
  make -C ../axern local-compose-image-import
```

- Axern canonical image: `index.docker.io/library/axrun-swebench-verified-django-12419@sha256:1a434903c4aecb496b16eea5d649624e04feb9dd044b0dbfa913ad343716930c`
- Environment: `env-eb0f68ed-bdd7-44a1-be4b-5bea12953dc1`
- Run: `run-c618f6ac-67ab-41dc-b093-4b5e25b90260`
- Allocation: `alloc-8df06d76-26be-4cc1-b3c7-cec232621b7d`
- Run exit code: `0`
- Sealed output: `/outputs/smoke.json`, 20 bytes,
  SHA-256 `b215ff190a08ad5dcf98fbe6ee599c5a3a2b5b7034c6b526eeeaa887f67ae648`
- Independent sealed-output length and SHA-256 check: passed

The real Allocation verified `/testbed`, exact Git HEAD, clean status, Django version, offline
network policy, and normal sealed-output completion. No credential was required or supplied.

The resolver accepts this repository only when callers explicitly select
`--task-platform linux/arm64`. The default remains `linux/amd64` and continues to require the
official SWE-bench image repository, so this development image cannot silently change benchmark
platform semantics. A real-row CLI resolve against the imported digest produced seed digest
`b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471` and spec digest
`704c77f51b465a8a8b984191001ef0634075f5474a10942256482303a2fc2a67`.
