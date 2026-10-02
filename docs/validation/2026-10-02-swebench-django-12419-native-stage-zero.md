# SWE-bench Verified Django 12419 native stage-zero oracle — 2026-10-02

The fixed `django__django-12419` gold, unrelated known-bad, and empty controls completed on native `linux/amd64` at `wayne-hk-dev`. The pinned upstream TestSpec, evaluation script, and scorer classified gold as resolved, known-bad as unresolved, and empty as unscored. A subsequent model-free Axern Run admitted the actual imported runtime image. Neither stage is Axrun fresh-verifier parity, normal CLI acceptance, a Claude result, or general SWE-bench support. The native oracle uses upstream patch-apply semantics and scorer but does not call upstream `run_instance`.

## Locked inputs and image

- Dataset: `SWE-bench/SWE-bench_Verified` commit `91aa3ed51b709be6457e12d00300a6a596d4c6a3`; Parquet 2,090,470 bytes, SHA-256 `43ed5a3d1d98da36472c1ade65ddd2085d7b4ff694fcaf6a023a07c5c1f32f21`. The complete enriched-v1 row SHA-256 is `6eea69026b82f8c17d1c2e299d39fada46d60acf6a9f39a4de20ab84749f1d37`; seed digest is `b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471`.
- Pinned official SWE-bench scorer checkout: `f7bbbb2ccdf479001d6467c9e34af59e44a840f9`, clean; exact dependency freeze SHA-256 `de9c9901cf9f9c1b8227f33e509b5a25adad36322c3958d485ca00531b5d48e4`. Prepared private assets validated against manifest SHA-256 `1e3dba04e3554a868e7ff34ead8d4a6e33a5e16e127b383352b3a0ce8611babe`.
- Official source platform manifest: `docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768`. The accepted derived clean-base seed has local image ID `sha256:22e52c3ff1f69caa7cba8b84dd0075da761c9d09ad795b76c6ec04cbfd58134d`, built from Axrun `63b68d449bc8a67f70363f4f0150dda30d26058c`. It inherits the source's `/testbed` working directory and its 11 RootFS layers comprise the source's exact 10 layers plus one new layer. This local image ID is **not** an Axern imported runtime digest.
- The offline seed audit found clean Git HEAD `7fa1a93c6c8109010a6ff3f604fda83b604e0e97` with its base commit present, system Python 3.10.12, and test-environment Python 3.6.13. Each case used a fresh Docker container with `--network none`, `--pull never`, 2 CPUs, 4 GiB memory, 256 PIDs, no Docker log persistence, and a 900-second case timeout. No model credential was needed or used.

## Retained pre-acceptance failures

The first seed, built from Axrun `c03ef8103d2508abd20d425a3de7621c74180ddc`, had local image ID `sha256:5157f52d166cf6260429db6889fb4a9fd6bec90f73f38818b9bd892b145424d5` and two layers beyond the official source. Docker history identified a redundant `WORKDIR`; no oracle ran on this seed. The Dockerfile removed that instruction and the new candidate was committed and transferred before rebuilding the accepted one-layer seed.

The first attempt on the accepted seed reached preflight and passed the read-only seed audit, then failed in the gold container before a benchmark verdict. `rsync -a` had retained Mac UID:GID `502:50` on mode-`0600` inputs; the capped container could not read the patch. The private `oracle-v2` receipt remains `incomplete` with zero scored cases, SHA-256 `4e8203a9dff0445cbe5105af89dbfbe7899d0f608583cc8e3ff7a7d76f6ea815`. Only the seven copied private assets and their directory were changed to `root:root`, retaining file mode `0600` and directory mode `0700`; their manifest was revalidated unchanged. A fresh `oracle-v3` run, rather than an amendment to the failed receipt, produced the result below.

## Official results and private evidence

| Control | Expected F2P | Official observed statuses | Official resolution | Classification |
| --- | ---: | ---: | --- | --- |
| Gold patch, SHA-256 `a1f6c1f9598eda33d4de4b85f018d759390b8e6c951af3f554b9df5b90ff7862` | 1/1 passed | 1 | true | test completed |
| Unrelated known-bad patch, SHA-256 `86f6e27cc48b291ae69b4cbd0af848a9af2ea76aba497d4a9eef0990e1722ab5` | 0/1 passed | 2 | false | test completed |
| Empty patch | — | — | null | official empty-patch unscored |

The known-bad log contains two parsed statuses, but the fixed official scoring denominator is its single expected fail-to-pass test; the extra observed status is not counted as another required test. The empty container executed diagnostically, while the official report records one empty-patch instance, zero completed instances, no test-status map, and no resolution score. It is not a 0/1 result.

The completed private `axrun.swebench-django-native-oracle@1` receipt SHA-256 is `c6836ffddff8ed673e38073980614fd0a23e00eb046b8dbbce14b5773292eb8e`. An independent read-only audit revalidated the asset manifest, scorer source/freeze, both Docker image IDs, exact 10+1 layer ancestry and labels, the receipt's three official summaries against stored official reports, and each case's stored log and patch hashes. The private files remain mode `0600` in `0700` directories; raw rows, patches, test logs, and per-test reports are not reproduced here. All `axrun-django-audit-*` and `axrun-django-oracle-*` containers were absent afterward; the seven existing Axern, two AKernel, and one BKS running containers remained running.

## Axern imported-runtime admission

The accepted seed was loaded with the released Axern v0.12.1 local image command. Its private import receipt has SHA-256 `fd6ac363b9c0d0f8cc9cb5f092d3dec90b7990cb54d37d3daba696a56ab7a8ab` and records the **distinct immutable runtime reference** `index.docker.io/library/axrun-django-seed-0121@sha256:3912793ab27162e63adec6835a9267b150341b9b5cba1532e6d7ac8933c8cbb6` (`linux/amd64`). Image load itself created no Environment or Run.

The [locked one-shot probe](../../tools/validation/swebench_django_axern_runtime_probe.py), from clean Axrun `b9f1e2478abb88124b26e1ec4cb23e5b4825d35d` with installed public `axern-sdk==0.12.1`, then executed **exactly one** fresh, model-free Run against that imported digest. Its approved inputs were the native oracle receipt SHA-256 `c6836ffddff8ed673e38073980614fd0a23e00eb046b8dbbce14b5773292eb8e` and image-import receipt above. The Run used deny-all networking, a 600-second scanner alarm, and 1 CPU/2 GiB scheduler requests; this deployment does not enforce those CPU/memory values as hard limits.

| Public identity | Value |
| --- | --- |
| Environment | `env-90e1900f-e4f6-40d6-a917-4f491feca71b` |
| Run | `run-56f60e5f-47ea-4e57-b054-c897fdf2c9d5` |
| Allocation | `alloc-5eb23a89-0281-4f25-b079-2c92320a6318` |

The Run reached `SUCCEEDED` with exit code 0. Its single public sealed output `/outputs/django-image-audit.json` was available as `application/json`, 1,428 bytes, SHA-256 `a1dc99b2aa846f4fa42f59a75681007e899539614c8c560e67c9b26e3d0003bc`. An independent SDK re-download matched its manifest and the local artifact byte-for-byte. The audit confirmed `x86_64`, deletion of its private request before scanning, a clean expected Git HEAD, complete traversal of 76,818 filesystem entries and all 339,152 Git objects, and no reachable locked gold/test-patch signatures. Its status was `passed` with reason `no_locked_patch_signatures_reachable`; this is a bounded signature check, not a general proof that no secret of any kind exists.

The private probe receipt SHA-256 is `4048174c34249a072649c1bf887a9f710243ad67212b8486e765040e65be7c6e` (`0600` in a `0700` directory). It records `cleanup=deleted_verified`: the target Environment subsequently returned NotFound, the Allocation was inactive, and there were no active Runs. Axern had 10 successful Runs before and 11 after this one attempt, with no extra Run; all three non-Axern container IDs were unchanged. No retry was made. Normal CLI deterministic fresh-verifier parity and a formal Django task/verifier identity remain outstanding; the admission result does not authorize or claim real-Claude acceptance.
