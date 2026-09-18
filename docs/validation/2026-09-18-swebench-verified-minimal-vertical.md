# Minimal SWE-bench Verified vertical — 2026-09-18

## Qualified contract

- Axrun implementation commit: `53967b488d6cf0890499c251794d63a091626819`
- Released SDK: `axern-sdk==0.8.1`
- Dataset: `SWE-bench/SWE-bench_Verified`, explicit `enriched-v1` row schema
- Supported instance: `django__django-12419`
- Repository: `django/django`
- Base commit: `7fa1a93c6c8109010a6ff3f604fda83b604e0e97`
- Official amd64 platform image: `docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768`
- Resolved seed digest: `b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471`
- Resolved spec digest: `5bd378ca64f3badca9e7dc86ad120ad774804d4bfbaccc5eec7988e90729e24b`

The resolver validates all 17 fields, the selected instance's fixed repository, base commit,
official image name, `pass_and_fail` evaluation type, and `parse_log_django` parser. It digests the
complete native row once, materializes content-addressed prompt and official evaluation-script
assets, and produces `ResolvedEpisode v1`. Neither the native row nor the gold patch enters the
inference or verifier StagePlan.

Claude uses the existing rootfs mount, ModelProxy, Anthropic-compatible protocol, and
Allocation-scoped Tunnel. `/testbed` is an explicit canonical harness working directory rather
than a benchmark special case hidden in the harness. Verification starts from a fresh Environment
Run/Allocation with deny-all networking, no environment variables, no image mounts, and only:

- immutable CandidateBundle patch;
- content-addressed official evaluation script;
- Axrun-owned verifier and Django log grader.

The packaged verifier's deterministic qualification covers both a fixing patch (`passed`, 1.0)
and an empty patch (`failed`, 0.0). An unapplicable patch, dirty/wrong base image, missing test
markers, or verifier process failure remains an infrastructure error.

## Actual progress and remaining acceptance

The official mutable tag was inspected and its `linux/amd64` platform manifest resolved to the
digest above. The real official row resolves and validates through the CLI. The entire source test
suite passes, including fresh-workspace patch application and offline grading.

A real SWE-bench Claude Run was not started because the only reachable Axern node is `aarch64`,
while the selected official image is `linux/amd64`. Running it on that node would violate the
canonical platform boundary. The sole remaining environment requirement is a reachable
`linux/amd64` Axern node after importing the exact official platform image and the amd64 Claude
rootfs, then creating an Environment from the returned task-image canonical digest.

```bash
uv run axrun resolve-swebench-verified /path/to/django__django-12419.json \
  --episode-id swebench-django-12419-NEW \
  --task-image docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768 \
  --assets-dir /tmp/axrun-swebench-assets \
  --claude-mount-image "$AMD64_CLAUDE_ROOTFS_DIGEST" \
  --model deepseek-flash \
  --claude-default-opus-model 'deepseek-flash[1m]' \
  --claude-default-sonnet-model 'deepseek-flash[1m]' \
  --claude-default-haiku-model deepseek-flash \
  --claude-subagent-model deepseek-flash \
  --claude-effort-level max \
  --claude-auto-compact-window 786432 \
  --inference-environment "$AMD64_SWEBENCH_ENVIRONMENT_ID" \
  --verification-environment "$AMD64_SWEBENCH_ENVIRONMENT_ID" \
  --output /tmp/axrun-swebench-django-12419.json

uv run axrun --state-dir .axrun --context-file "$AXERN_CONFIG" --context "$AXERN_CONTEXT" \
  --model-upstream-url https://api.deepseek.com/anthropic \
  --model-credential-env DEEPSEEK_API_KEY \
  run /tmp/axrun-swebench-django-12419.json
```
