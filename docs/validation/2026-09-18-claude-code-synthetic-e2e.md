# Claude Code synthetic E2E acceptance — 2026-09-18

This record captures a successful real-model acceptance run against the Axern source Compose cluster. It contains no provider credential, Tunnel token, request or response body, sensitive header, or machine-local secret path.

## Versions and immutable inputs

- Axrun commit: `0ec070f4cea4ee46577db9f67afb80367a627e8b`
- Axern commit: `1d3f9b581ad201625f793a5ae6ea2f49a7cd6f7a`
- Released SDK: `axern-sdk==0.8.1`
- Platform: `linux/arm64` local-development acceptance; benchmark canonical remains `linux/amd64`
- Synthetic task image: `index.docker.io/library/axrun-synthetic-code-task@sha256:a2cb20a30601b7119a55f382d80615e8622191364abd6003653d281ca0eb50b0`
- Claude Code rootfs: `index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633`
- Environment: `env-05ec66c7-87c7-4870-a7d6-c70f6abb871d`
- Episode: `synthetic-claude-deepseek-20260918-03`
- Seed digest: `4d1975b6d010a16474d4da0adb911fc88a678eee23cd2e1f19c0ecf8bac271f5`

The rootfs was imported through Axern's public source-development command. Axern returned the digest above; the Run used that canonical digest rather than the local mutable tag.

## Non-sensitive model configuration

- Protocol: Anthropic-compatible
- Upstream base URL: `https://api.deepseek.com/anthropic`
- Caller credential variable name: `DEEPSEEK_API_KEY`
- Primary model: `deepseek-flash`
- Opus alias: `deepseek-flash[1m]`
- Sonnet alias: `deepseek-flash[1m]`
- Haiku alias: `deepseek-flash`
- Subagent model: `deepseek-flash`
- Effort: `max`
- Auto-compact window: `786432`

The Allocation-scoped lifecycle passed local health, Tunnel readiness, and a real `/v1/messages` preflight with HTTP 200 before releasing Claude Code. The sandbox Run contained only the fixed `ANTHROPIC_AUTH_TOKEN=axrun-local-tunnel` sentinel. The ModelProxy removed sandbox authentication headers and injected the upstream credential in caller memory.

## Inference and sealed outputs

- Inference Run: `run-f3cf31ed-a029-4d4d-94d2-648077af088d`
- Inference Allocation: `alloc-bb91aef3-fd1c-4438-b0c2-ebcecf7c373c`
- Run exit code: `0`

| Declared output | Bytes | SHA-256 |
| --- | ---: | --- |
| `/outputs/candidate.patch` | 1841 | `0c898db61c60532001a3acbf26aae4bf4331933b8108d154f0dc82d7b5482a76` |
| `/outputs/trajectory.jsonl` | 13849 | `c7d47400899e15577a8d42da0fb8c3937e45206a56bfdb4d9dd7e459e899ee94` |
| `/outputs/harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/outputs/usage.json` | 143 | `5c411dd9b93571208caa1a2ccbf882b6bbe799d030b337992dae6b111a22aac8` |

Each downloaded file's byte length and SHA-256 matched the Axern sealed-output manifest and the immutable CandidateBundle manifest.

- CandidateBundle digest: `c2bbaacbf3859bd36e2a3fe18586be661d73dddfb7d4fc666492cd821a68e70f`

## Fresh verification

- Verification Run: `run-778e06db-cc77-405f-bf33-dff196e13561`
- Verification Allocation: `alloc-051d5875-898d-4776-943d-1deee751c25c`
- Verification output SHA-256: `1b86902bd17c085186215b1fb24d6f914bbc6775191ad1d9d90a87315e74e445`
- VerificationResult digest: `e4dff8f15f4b74a043acde6410bb147e44656dadf415517de36dc03947b84612`
- Referenced CandidateBundle digest: `c2bbaacbf3859bd36e2a3fe18586be661d73dddfb7d4fc666492cd821a68e70f`
- Verdict: `passed`
- Score: `1.0`
- Diagnostic code: empty (none)
- Verifier exit code: `0`

The verification Run had no image mounts or environment variables, used an isolated network policy, and received only the candidate patch and Axrun-owned verifier inputs. Its Run and Allocation identities differ from inference.

## Security and cleanup checks

- Credential scan: `0` matches across 39 Axrun state/artifact files, the resolved episode, and the serialized inference and verification Run records.
- No credential or Tunnel token was present in the episode, Run configuration, sealed outputs, trajectory, CandidateBundle, VerificationResult, or durable execution record.
- ModelProxy, connector, and TunnelSession cleanup completed through the lifecycle's unconditional close path.
- Post-run Axern status reported zero running Allocations, zero active Allocations, and zero running containers. One imagefs mount remained in the node's reusable image cache; it was not owned by a live Allocation.
- Repeated lifecycle `close()` remains covered as idempotent by the automated test suite.

## Reproduction

The caller must already have `DEEPSEEK_API_KEY` and `AXERN_CONFIG` set. Neither value is written into the episode.

```bash
uv run axrun resolve-synthetic fixtures/synthetic/code-task-v1/row.json \
  --episode-id NEW_UNIQUE_EPISODE_ID \
  --harness claude-code \
  --claude-mount-image index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633 \
  --model deepseek-flash \
  --claude-default-opus-model 'deepseek-flash[1m]' \
  --claude-default-sonnet-model 'deepseek-flash[1m]' \
  --claude-default-haiku-model deepseek-flash \
  --claude-subagent-model deepseek-flash \
  --claude-effort-level max \
  --claude-auto-compact-window 786432 \
  --inference-environment env-05ec66c7-87c7-4870-a7d6-c70f6abb871d \
  --verification-environment env-05ec66c7-87c7-4870-a7d6-c70f6abb871d \
  --output /tmp/axrun-synthetic-claude.json

uv run axrun \
  --state-dir .axrun \
  --context-file "$AXERN_CONFIG" \
  --context compose \
  --model-upstream-url https://api.deepseek.com/anthropic \
  --model-credential-env DEEPSEEK_API_KEY \
  run /tmp/axrun-synthetic-claude.json
```
