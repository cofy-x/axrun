# Synthetic Claude capability acceptance on arm64

This is a complete source-Compose acceptance of the post-qualification Axrun path:

```text
model-free qualification
  -> caller-side ModelProxy + Allocation Tunnel preflight
  -> Claude Code candidate + canonical trajectory
  -> sealed-output SHA-256 verification
  -> immutable CandidateBundle and TrajectoryBundle
  -> fresh deny-all verification Run
  -> independently verified acceptance report
```

## Identities

- Axrun commit before acceptance: `a3bf59630fd0c32ea6d612d3ba50733e4620dcc1`
- Axern commit: `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`
- Released SDK: `axern-sdk==0.9.1`
- Episode: `synthetic-capabilities-20260919-03`
- Environment: `env-e01cb28a-ec64-46c8-9f90-eb7f1ed1656a`
- Task image: `index.docker.io/library/axrun-synthetic-code-task@sha256:207342f294efcbb882aef9f401dc84120f15ecbfcd8c1c429e3821d3df1324c7`
- Claude rootfs: `index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633`
- Qualification Run / Allocation: `run-6d7ade2d-85ff-4eba-9b82-fe4f39023792` / `alloc-4ae10796-7796-4b6b-8bb9-14fd28eea836`
- Inference Run / Allocation: `run-5c972095-b0cd-4ac0-b4ed-167f0a2d4151` / `alloc-e646712f-9ff4-4a25-9551-92b03bc4b62f`
- Verification Run / Allocation: `run-f740bdba-8c99-4098-a667-91c6561ffa9b` / `alloc-98d3aad1-707b-46b2-b96f-f77608dd3ca4`

The non-sensitive runtime configuration used `deepseek-flash` as the primary model. Omitted Opus,
Sonnet, Haiku, and subagent aliases were materialized to that same opaque model ID. Effort was
`max`, auto-compact window `786432`, and max turns `20`. The canonical config explicitly disabled
`WebFetch` and `WebSearch`; the sandbox network policy remained deny-all.

## Qualification and outputs

Qualification evidence digest was
`9ffced992c5f3f4e7e147d20e3d46e087d8a4b89c5671212ce3e75ac91cecb1b`. Its sealed checks
reported `aarch64`, Git `2.39.5`, Python `3.11.16`, Claude Code `2.1.205`, Node.js `v22.23.2`,
the exact clean base commit, and a read-only `/__claude_code` mount.

All inference files were independently length- and SHA-256-verified after sealed download:

| Output | Bytes | SHA-256 |
| --- | ---: | --- |
| `candidate.patch` | 202 | `ab5c849b4c34154fbd2a25965be4b98004ef5d5248be1cad483a41da5a5baaaa` |
| `trajectory.jsonl` | 9124 | `66426a9bdae137d5a3de2beba3ca4d7fce29e36af95bcbcf1861c0d5e8159392` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 143 | `25dcef1ebf6ad0533f41aa22a311e0e5cacd089d6ba256c513ecbd9211bdf77e` |

- CandidateBundle: `191dff2aa14752776d79fa422e5add331e6e6fc23258a8fe89004a191ff0ef36`
- TrajectoryBundle: `a3bedffe85fdfa247c5dde606a26d23332f200b2faf6d85f6fa9740e051b493f`
- Canonical trajectory events: `25`
- Inference termination: `completed`
- VerificationResult: `8278b153e3aeff820226b477db7d23eb221176f554431a64e0573fc03202655c`
- Verdict / score: `passed` / `1.0`

`verify-record` independently reconstructed this digest/provenance chain. The verifier used a fresh
Run and Allocation, the same immutable task image, deny-all networking, and no inference Tunnel,
credential, process, or filesystem identity.

## Safety and cleanup

Twenty durable files across the episode, qualification, progress, sealed artifacts, candidate,
trajectory, and result locations were scanned. The caller credential value and the markers
`axrun-local-tunnel`, `x-api-key`, `authorization`, and `cookie` each had zero matches. No request
or response body was recorded. Exec probes against the qualification, inference, and verification
Allocations all returned terminal precondition errors, confirming cleanup.

Two new, non-reused episodes exposed and retained safe diagnostics before this accepted episode:

- `synthetic-capabilities-20260919-01`: Tunnel health failed because the probe assumed
  `/usr/bin/python3` in a qualified Python base image.
- `synthetic-capabilities-20260919-02`: Tunnel model preflight reached upstream with HTTP 200, then
  the Claude supervisor made the same path assumption and exited 127.

The accepted fix uses a shared control-Python rule: prefer `/usr/bin/python3` for benchmark images,
otherwise use the qualified task-image `python3`. It does not add a provider- or benchmark-specific
proxy path.

## Reproduction

The model credential stays in the caller environment and is named, never copied, by this command:

```bash
uv run axrun --state-dir .axrun \
  --context-file "$HOME/.config/axern/config.json" --context compose \
  --model-upstream-url https://api.deepseek.com/anthropic \
  --model-credential-env DEEPSEEK_API_KEY \
  --model-response-timeout-seconds 600 \
  run /tmp/axrun-synthetic-capabilities-20260919-03.json

uv run axrun --state-dir .axrun verify-record synthetic-capabilities-20260919-03
uv run axrun --state-dir .axrun report synthetic-capabilities-20260919-03 --format markdown
```
