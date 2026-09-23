# Synthetic patch-hygiene E2E acceptance — 2026-09-18

This is a new acceptance record. It does not alter the earlier Claude E2E record, whose candidate
correctly passed but also demonstrated why runtime bytecode belongs in the task seed's ignore
policy. No credential, Tunnel token, sensitive header, request body, or response body is recorded.

## Versions and immutable inputs

- Axrun implementation commit: `4e7f960f933edfddc394596b56aeb0c8adfe7b9f`
- Axern source-cluster commit: `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`
- Released SDK: `axern-sdk==0.8.1`
- Platform: `linux/arm64` local-development acceptance
- Synthetic base commit: `69b31ae17c45d731fd5b6fa43660c05aea4a9027`
- Synthetic task image: `index.docker.io/library/axrun-synthetic-code-task@sha256:207342f294efcbb882aef9f401dc84120f15ecbfcd8c1c429e3821d3df1324c7`
- Claude rootfs: `index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633`
- Environment: `env-e01cb28a-ec64-46c8-9f90-eb7f1ed1656a`
- Seed digest: `45628b0130c417759d74107963a43c9dde976cccc01a8d6a0e0e5f3b958a3b1f`

The task image was rebuilt after adding the repository-owned `.gitignore`, imported through
Axern's public source-development image-import target, and selected by the canonical digest
returned by Axern. The ignore policy excludes Python bytecode and cache directories while Git's
normal tracked/untracked candidate export continues to retain newly created source files.

## Static qualification

| Path | Verdict | Score | Inference Run / Allocation | Verification Run / Allocation |
| --- | --- | ---: | --- | --- |
| gold | passed | 1.0 | `run-88aa2aaf-e34c-436e-8277-2c9788a9fa99` / `alloc-9090e3b5-dcd3-4ee0-a5af-a8362ea336fb` | `run-3f8a6aed-af2f-45e3-a1eb-a0f49637299d` / `alloc-2673d6a1-e246-4b8e-9087-4336c9082b1b` |
| empty | failed | 0.0 | `run-5e02ed9a-aaab-4488-af3f-e9090b8364ff` / `alloc-78d64003-430c-49ac-bf54-2c6e4f91b7bd` | `run-7bfb9d7e-5fae-4f7a-909e-02e064a2b1dc` / `alloc-05822c00-d7a4-4ebb-bf0d-6a48ac7a245f` |

The empty candidate produced the legitimate business diagnostic `SYNTHETIC_TESTS_FAILED`; it was
not converted from an infrastructure error.

## Real Claude candidate and fresh verification

- Episode: `synthetic-hygiene-claude-01`
- Inference Run: `run-374cde6d-4f94-45af-b48e-8e12e083c802`
- Inference Allocation: `alloc-bb88b2e0-4eec-4a53-b736-fe0f32d35c7b`
- CandidateBundle: `6b61ca08d3ade3e5ab04abc6dbdee3ad8286578f4d541789253a7ff6426945f9`
- Verification Run: `run-19a3389f-05d5-438b-af6b-db62ada0245b`
- Verification Allocation: `alloc-41f7a9de-a989-4174-995d-21e4c75f1028`
- VerificationResult: `55c15a13d7cd781757df7f367c1d3e5ed1d4f670034ec513abce109395c41b60`
- Verdict: `passed`, score `1.0`

| Sealed output | Bytes | SHA-256 |
| --- | ---: | --- |
| `candidate.patch` | 202 | `ab5c849b4c34154fbd2a25965be4b98004ef5d5248be1cad483a41da5a5baaaa` |
| `trajectory.jsonl` | 19984 | `395d5ca31da7aa090640f6b28b89a9cc4021c91ccaba4bd5b1b701f8e69f6fcb` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 143 | `39f2d1834ca62f5fc2896c0517eb09e8d87a9019ad1ac41c64d9e62d70cd0495` |

Axrun independently rechecked each sealed file's length and digest. The candidate patch contains
the required `calculator.py` source change and contains neither `__pycache__` nor `.pyc` paths.

## Security, diagnostics, and cleanup

- Credential scan: `0` matches across 83 Axrun state and artifact files.
- The sandbox received only the fixed `axrun-local-tunnel` authentication sentinel.
- ModelProxy, connector, and TunnelSession completed the unconditional cleanup path.
- No Allocation workload container remained after the runs; the source Compose services remained
  healthy.
- Safe failed-stage diagnosis now distinguishes `proxy_protocol_rejected`,
  `proxy_upstream_error`, `upstream_response`, `tunnel_health_failed`, and
  `tunnel_model_preflight_failed` without persisting headers or bodies.

## amd64 canonical acceptance status

The only available Axern source Compose node reported `aarch64`; therefore this record does not
claim amd64 benchmark acceptance. The remaining environment requirement is one reachable
`linux/amd64` Axern node with the matching amd64 synthetic task image and Claude rootfs imported
and selected by their Axern-returned canonical digests. With those values and an Environment built
from the task image, the direct acceptance commands are:

```bash
uv run axrun resolve-synthetic fixtures/synthetic/code-task-v1/row.json \
  --episode-id synthetic-amd64-claude-NEW \
  --harness claude-code \
  --claude-mount-image "$AMD64_CLAUDE_ROOTFS_DIGEST" \
  --model deepseek-flash \
  --claude-default-opus-model 'deepseek-flash[1m]' \
  --claude-default-sonnet-model 'deepseek-flash[1m]' \
  --claude-default-haiku-model deepseek-flash \
  --claude-subagent-model deepseek-flash \
  --claude-effort-level max \
  --claude-auto-compact-window 786432 \
  --inference-environment "$AMD64_ENVIRONMENT_ID" \
  --verification-environment "$AMD64_ENVIRONMENT_ID" \
  --output /tmp/axrun-synthetic-amd64.json

uv run axrun --state-dir .axrun --context-file "$AXERN_CONFIG" --context "$AXERN_CONTEXT" \
  --model-upstream-url https://api.deepseek.com/anthropic \
  --model-credential-env DEEPSEEK_API_KEY \
  run /tmp/axrun-synthetic-amd64.json
```
