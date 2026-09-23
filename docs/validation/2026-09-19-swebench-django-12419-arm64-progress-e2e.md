# SWE-bench django__django-12419 arm64 progress E2E — 2026-09-19

This record covers a real Claude Code inference, live caller-side progress observation, sealed
output verification, immutable bundle construction, and a fresh offline SWE-bench verification on
the local Axern source Compose cluster. It is local-development arm64 acceptance, not canonical
amd64 leaderboard acceptance.

## Provenance

- Axrun Allocation execution commit: `c93f53af26d8837c393c35842fadf541614f34c6`
- Axrun post-acceptance progress-retention fix: `f053f77`
- Axern commit: `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`
- released SDK: `axern-sdk==0.9.1`
- node platform: `linux/arm64` (`aarch64`)
- dataset / instance: `SWE-bench/SWE-bench_Verified` / `django__django-12419`
- base commit: `7fa1a93c6c8109010a6ff3f604fda83b604e0e97`
- seed digest: `b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471`

The source Compose state was preserved while switching back from the amd64 profile. The arm64
task and Claude images were re-imported through Axern's public `local-compose-image-import` path:

| Image | Local image ID | Axern canonical digest |
| --- | --- | --- |
| task | `sha256:76403152cf97d36eb8bcb4a107faecda34fd58cd1f02bbedf37304965d74f8cf` | `index.docker.io/library/axrun-swebench-verified-django-12419@sha256:f55941225d3c8f663b5f9ca47cc94ea94cb6723dbbcf6563fdd3a401ad042867` |
| Claude Code 2.1.205 rootfs | `sha256:72a250f33a1b1a2d711b4ac263692cca9030cb4c1a3a8b329866824464253524` | `index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633` |

All source Compose services, including the node, reported arm64. A non-destructive node restart
was required once after the architecture switch because the runtime conformance probe retained a
stale monitor; after restart the hard ephemeral-storage capability was healthy. No Axern source or
persistent control-plane state was modified or reset.

## Episode and live progress

- Environment: `env-d2335cff-303b-4eaa-ad7b-65ffb25ca649`
- episode: `swebench-django-12419-arm64-progress-20260919-07`
- spec digest: `b4ebc27c6bc3d42f6c91e85e7d04df1a20bb4ab2fc176c825c1ba7dd1c104d4e`
- inference Run / Allocation: `run-144ac594-1f25-4028-b13a-0f39d05af7dc` /
  `alloc-6fcc73ad-db05-4ab1-b7ba-b9b0624f8c08`
- verification Run / Allocation: `run-6411a7ab-53cd-4876-8ee7-98b28f8d955d` /
  `alloc-b3d11972-789d-4fae-a915-9c0b55f69fc6`

The first caller-side inspection saw the inference Run persisted with no Allocation and progress
revision zero. A later inspection saw the Allocation bound and the Claude process running. During
the still-running inference, observed revisions included `13`, `28`, `41`, `78`, `115`, `153`,
`181`, `221`, `263`, and `313`. Safe snapshots distinguished `model_request_in_flight` from
`tool_activity`, reported only the latest event kind/tool name, counts, sizes, status, latency, and
usage summary, and exposed stale duration during one long model response. They contained no
prompt, request/response body, tool arguments/results, credential, sensitive header, or Tunnel
token.

The run exposed a Python compatibility defect before this accepted episode: the Allocation-local
supervisor imported `datetime.UTC`, which is unavailable in the task image's Python 3.10. Commit
`c93f53a` changed all Allocation fixture scripts to the Python 3.10-compatible `timezone.utc` form
and added a regression check. The accepted episode then completed normally. The accepted run also
showed that the last caller snapshot could lose previously observed runtime counters after the
Allocation became unreadable. Commit `f053f77` now retains the last valid safe runtime fields while
marking the state `progress_unavailable`; its deterministic observer test covers the terminal race.

The non-sensitive model configuration was the Anthropic-compatible endpoint, opaque primary model
`deepseek-flash`, Opus and Sonnet aliases `deepseek-flash[1m]`, Haiku and subagent aliases
`deepseek-flash`, effort `max`, auto-compact window `786432`, and 40 turns. The model preflight
returned HTTP 200 before the inputs-ready marker was written. Claude reached the closed max-turn
boundary with a usable patch.

## Sealed outputs and bundles

Axrun downloaded every inference output through the sealed-output API and independently matched
its length and SHA-256 to the Axern manifest:

| Output | Bytes | SHA-256 |
| --- | ---: | --- |
| `candidate.patch` | 3,667 | `b97d2926408e77e70d4646d7c0fef6bd2e65eea18b6cc94efda56abd4aff7dfd` |
| `trajectory.jsonl` | 192,591 | `90db05746dbaa4dec8447f622baaac314fa55842da8f92afa39d4fd3c5910ea4` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 148 | `a7e14fb0532e0000325b9f657e5fe32f39487ba3430e799a21fef142f7811434` |

- CandidateBundle digest: `777a011af1afa1a41a44e2ff07c08bf7ded7a6d54dd14d39b7cc1e1554700a15`
- TrajectoryBundle digest: `1f51326611f1f741ea8127c514edaee26d301ad118aca4ac8aace18b0dbefdec`
- canonical trajectory: 218 events (`1` session start, `1` context, `6` assistant messages,
  `64` tool calls, `64` tool results, `40` reasoning metadata, `41` usage, `1` final result)

## Fresh verification and security checks

The verification Run used the same immutable task Environment but a fresh Allocation. It had no
image mount, used isolated/deny-all networking, received only the CandidateBundle patch and
Axrun-owned verifier assets, and exited zero.

- VerificationResult digest: `1d4924123177736de422598b502f6fbc51131afb78fccdb146bf4a7ed2bef2ce`
- referenced CandidateBundle digest: `777a011af1afa1a41a44e2ff07c08bf7ded7a6d54dd14d39b7cc1e1554700a15`
- verdict / score: `passed` / `1.0`
- diagnostic code: empty
- verifier exit code: `0`

The protected scan covered the episode record/spec, progress snapshot, four inference downloads,
CandidateBundle, TrajectoryBundle, VerificationResult, and resolver assets. The caller credential
value, `axrun-local-tunnel`, `x-api-key`, and a Tunnel client-token field each had zero matches.
Header-like words found only in the public Django verifier log were repository documentation and
test fixtures such as `Set-Cookie`; no header value or caller credential was present. The
inference artifacts and progress record contained no `Authorization:` or `Cookie:` header.

Cleanup was complete and idempotent: both terminal Allocations reject exec with
`SandboxPreconditionError`; the source node reports zero running/active Allocations and zero
workload containers; no caller axrun, Claude supervisor, connector, or ModelProxy process remains.

## Reproduction

The caller must provide `DEEPSEEK_API_KEY`; the value must not appear on the command line:

```bash
TASK_DIGEST='index.docker.io/library/axrun-swebench-verified-django-12419@sha256:f55941225d3c8f663b5f9ca47cc94ea94cb6729dc4082cd1bf0d0664f2633'
CLAUDE_DIGEST='index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633'
EPISODE_ID="swebench-django-12419-arm64-progress-$(date +%s)"

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

This acceptance proves the product flow and progress contract on the local arm64 development
platform. Canonical benchmark acceptance still requires the amd64 runtime blocker documented in
`2026-09-19-amd64-emulation-runtime-blocker.md` to be resolved and the same flow rerun on amd64.
