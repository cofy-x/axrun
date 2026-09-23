# SWE-bench django__django-12419 arm64 E2E — 2026-09-19

This record covers one real Claude Code inference and a fresh offline SWE-bench verification on
the local Axern source Compose cluster. It is local-development arm64 acceptance, not canonical
amd64 leaderboard acceptance.

## Provenance

- Axrun execution commit: `b68701b5d883cc9022635241630b985e77507a9b`
- Axern commit: `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`
- released SDK: `axern-sdk==0.9.1`
- SDK import: Axrun's `.venv/site-packages/axern_sdk/__init__.py`, not the Axern checkout
- node platform: `linux/arm64` (`aarch64`)
- dataset / instance: `SWE-bench/SWE-bench_Verified` / `django__django-12419`
- base commit: `7fa1a93c6c8109010a6ff3f604fda83b604e0e97`
- parser / evaluation: `parse_log_django` / `pass_and_fail`

The rebuilt task image has local image ID
`sha256:76403152cf97d36eb8bcb4a107faecda34fd58cd1f02bbedf37304965d74f8cf`.
Its offline qualification produced empty `failed` and gold `passed`. Axern imported it as:

`index.docker.io/library/axrun-swebench-verified-django-12419@sha256:f55941225d3c8f663b5f9ca47cc94ea94cb6723dbbcf6563fdd3a401ad042867`

The Claude Code 2.1.205 arm64 rootfs local image ID is
`sha256:72a250f33a1b1a2d711b4ac263692cca9030cb4c1a3a8b329866824464253524`.
Axern reused its canonical import:

`index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633`

The task image keeps Django's Python 3.6.13 test environment and separately supplies system Python
3.10.12 for Axrun-owned lifecycle and trajectory control code. The Claude rootfs retains Node.js
22.23.2 and the read-only `/__claude_code/usr/local/bin/claude` ABI.

## Episode and lifecycle

- Environment: `env-e6617cc5-b112-465d-bc99-413ef52048d5`
- episode: `swebench-django-12419-arm64-trajectory-20260919-03`
- seed digest: `b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471`
- spec digest: `3ea3220bb895a1da6e6ba047332e4745cabcf7a9f5823c36594274dfa0614762`
- inference Run / Allocation: `run-e449dea4-365b-4222-96b5-e6bb80a5ce26` /
  `alloc-853e557e-4570-4e0e-9f6a-977bc2f7c1db`
- verification Run / Allocation: `run-4fd435a7-09cf-45a8-87df-899a4be461f2` /
  `alloc-039dcb25-8ac9-409f-9194-86e51ecc8a43`

The caller used the Anthropic-compatible endpoint, opaque primary model `deepseek-flash`, Opus and
Sonnet aliases `deepseek-flash[1m]`, Haiku and subagent aliases `deepseek-flash`, effort `max`,
auto-compact window `786432`, and 40 turns. Health and model preflight completed before the input
ready marker. Claude reached its explicit max-turn agent budget with a usable patch; the closed
`error_max_turns` policy published the candidate for grading. Both Axern Runs then reached
`RUN_STATUS_SUCCEEDED` with exit code zero.

Cleanup completed after the inference terminal state. Both Allocations reject further exec with
`SandboxPreconditionError`; no matching workload container, caller ModelProxy process, connector,
or Axrun CLI process remained. Tunnel session identity and client token were not persisted.

## Sealed outputs and bundles

Axrun downloaded each inference output through the sealed-output API and independently rechecked
length and SHA-256:

| Output | Bytes | SHA-256 |
| --- | ---: | --- |
| `candidate.patch` | 2,865 | `d1b0111e383ad5ae626e87984addfca0d1fd01a8491419009795d49057752923` |
| `trajectory.jsonl` | 169,082 | `acd8294e4cdc56f693534618f4116cb5fbc7120f019138547b416ef0329682e0` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 148 | `741040a561d4cd66efbde3cf58ef986e330ae7d102c6c27423228b9a979f724c` |

CandidateBundle digest
`bdc10fd594936251cd21d8bd9259e004a232019de6a97ecc53d0eaa0bff6a6aa` contains only
`files/00-candidate.patch`, with the same 2,865-byte length and SHA-256 above.

TrajectoryBundle digest
`ff0ac445926fe11d20d5f04b20fe17d6a1311a8761726f577ae46bf18a10962c` contains only the
canonical trajectory and usage files above. It has 219 events:

| Kind | Count |
| --- | ---: |
| `session_start` | 1 |
| `context` | 1 |
| `assistant_message` | 7 |
| `tool_call` | 64 |
| `tool_result` | 64 |
| `reasoning_metadata` | 40 |
| `usage` | 41 |
| `final_result` | 1 |

The task context provenance is `axrun_task_prompt`, matches the resolver-materialized prompt byte
for byte, and has SHA-256
`1f07796a60c95eb7974ea0084d52158fa47471e45dff3dde4ad328aeff3a17f6`.
No user-message event was present in this native run, so none was synthesized.

## Verification and security checks

The verification StagePlan contained exactly:

- `/inputs/candidate.patch`;
- `/opt/axrun-swebench/run_verifier.py`;
- `/opt/axrun-swebench/eval.sh`.

It used `deny_all` / actual `NETWORK_MODE_ISOLATED`, no Secret projection, no image mount, no
trajectory, usage, harness log, proxy summary, Tunnel, or inference filesystem. VerificationResult
digest `982b88378c452399113fe73d735e9a55ee76882a7fc3e43d0397364d1b69a69a`
references the exact CandidateBundle digest. Verdict: `passed`; score: `1.0`; diagnostic code:
empty; verifier exit code: `0`.

The protected scan scope was the resolved episode/assets, durable episode record, four inference
sealed downloads, CandidateBundle, TrajectoryBundle, and VerificationResult. Counts were zero for
the caller credential value, `axrun-local-tunnel`, `x-api-key`, `Authorization:`, `Cookie:`, raw
thinking markers, signature markers, and serialized `thinking` / `signature` fields. The canonical
trajectory contains reasoning metadata only. No Tunnel client token is available to scan because
it existed only in lifecycle and SDK connector memory and was never serialized.

## Reproduction

The caller must provide `DEEPSEEK_API_KEY`; the value must not appear on the command line:

```bash
TASK_DIGEST='index.docker.io/library/axrun-swebench-verified-django-12419@sha256:f55941225d3c8f663b5f9ca47cc94ea94cb6723dbbcf6563fdd3a401ad042867'
CLAUDE_DIGEST='index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633'
EPISODE_ID="swebench-django-12419-arm64-$(date +%s)"

uv run axrun resolve-swebench-verified "$ROW" \
  --episode-id "$EPISODE_ID" \
  --task-image "$TASK_DIGEST" \
  --task-platform linux/arm64 \
  --assets-dir "$ASSETS_DIR" \
  --claude-mount-image "$CLAUDE_DIGEST" \
  --model deepseek-flash \
  --claude-default-opus-model 'deepseek-flash[1m]' \
  --claude-default-sonnet-model 'deepseek-flash[1m]' \
  --claude-default-haiku-model deepseek-flash \
  --claude-subagent-model deepseek-flash \
  --claude-effort-level max \
  --claude-auto-compact-window 786432 \
  --max-turns 40 \
  --inference-environment "$ENVIRONMENT_ID" \
  --verification-environment "$ENVIRONMENT_ID" \
  --output "$EPISODE_JSON"

uv run axrun \
  --state-dir .axrun \
  --context-file "$HOME/.config/axern/config.json" \
  --context compose \
  --model-upstream-url https://api.deepseek.com/anthropic \
  --model-credential-env DEEPSEEK_API_KEY \
  run "$EPISODE_JSON"
```

No accessible `linux/amd64` Axern node existed in this source Compose cluster. Canonical benchmark
acceptance remains pending on that platform. Once an amd64 node and matching imported images are
available, create a new amd64 Environment and run the same commands with
`--task-platform linux/amd64`, `$AMD64_TASK_IMAGE_DIGEST`, `$AMD64_CLAUDE_ROOTFS_DIGEST`, and a new
episode ID. Do not reuse this arm64 Environment.
