# Canonical trajectory synthetic E2E — 2026-09-18

This record captures a new real Claude Code episode. It does not rewrite earlier native-trajectory
history. It contains no raw thinking, model request/response body, credential, Tunnel token,
sensitive header, or machine-local secret path.

## Versions and immutable runtime

- Axrun implementation commit: `2a54a1f2b1ed0e925ac2f63663cc6566c24c8d24`
- Axern source-cluster commit: `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`
- Released SDK: `axern-sdk==0.8.1`
- Platform: `linux/arm64` local-development acceptance
- Contract: `axrun.trajectory@1`, TrajectoryBundle v1
- Synthetic task image: `index.docker.io/library/axrun-synthetic-code-task@sha256:207342f294efcbb882aef9f401dc84120f15ecbfcd8c1c429e3821d3df1324c7`
- Claude rootfs: `index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633`
- Environment: `env-e01cb28a-ec64-46c8-9f90-eb7f1ed1656a`
- Episode: `synthetic-canonical-trajectory-01`
- Seed digest: `45628b0130c417759d74107963a43c9dde976cccc01a8d6a0e0e5f3b958a3b1f`

## Inference and immutable bundles

- Inference Run: `run-49223d79-6f18-4b04-b511-7e2fb0063ab7`
- Inference Allocation: `alloc-76ba3ae0-ac8f-4319-9b73-ccd3080b38eb`
- CandidateBundle: `195dda09b28151620fe666fd93bb62587cd695516132a17e1782287a47109f23`
- TrajectoryBundle: `8e1145a0587cc3731e34afc304a53e51288bda379c1346b3cd212a0742ee8845`

| Sealed output | Bytes | SHA-256 |
| --- | ---: | --- |
| `candidate.patch` | 202 | `ab5c849b4c34154fbd2a25965be4b98004ef5d5248be1cad483a41da5a5baaaa` |
| `trajectory.jsonl` | 9440 | `f59ba31a38866b8e7cb7ec35c0c2f11c7aedbf612a56eade40c1123415f792f8` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 143 | `3ae5b75e132e38b4806525c869da75e4e0073764c61495e02f44d908196dd6dc` |

The CandidateBundle contains exactly one file, `candidate.patch`. The TrajectoryBundle contains
only `trajectory.jsonl` and `usage.json`; its manifest records 26 events. Axrun rechecked all
sealed-output and bundle lengths and SHA-256 values independently.

Event counts:

| Kind | Count |
| --- | ---: |
| `session_start` | 1 |
| `context` | 1 |
| `assistant_message` | 2 |
| `tool_call` | 5 |
| `tool_result` | 5 |
| `reasoning_metadata` | 5 |
| `usage` | 6 |
| `final_result` | 1 |

The task context has `axrun_task_prompt` provenance, 148 bytes, and content digest
`c9b6280835d6766381eba804e1369f79f64a0b38744e50815ae5823a9c9d0a3d`. The model remains the
opaque string `deepseek-flash`. No internal system prompt is claimed or reconstructed.

## Fresh verification

- Verification Run: `run-944a2bd7-582c-4bb8-bd2d-86b0ecb2b4c3`
- Verification Allocation: `alloc-b54b8558-6b2c-4372-b9e8-060c0368c478`
- VerificationResult: `af0b4ddea60b89b5f239c858e355fd49eb9e817f0d69490cc15eecfbdd92479b`
- Referenced CandidateBundle: `195dda09b28151620fe666fd93bb62587cd695516132a17e1782287a47109f23`
- Verdict: `passed`, score `1.0`
- Verification output SHA-256: `eb3c61e2bb6e243df11f9f0cca7cc0422f0d4f68cd454afd7afed8e7be67b395`

The fresh verifier used deny-all networking, no environment variables, image mounts, secrets,
Tunnel, or inference path. Its only uploaded inputs were `candidate.patch` and the Axrun-owned
synthetic verifier. It did not receive trajectory, usage, harness log, or ModelProxy summary.

## Safety, export, and cleanup

- Canonical scan: zero `thinking` fields, zero `signature` fields.
- Deterministic unique-marker scan: zero `RAW-THINKING-MARKER-MUST-DISAPPEAR`,
  `RAW-SIGNATURE-MARKER-MUST-DISAPPEAR`, and credential/header marker matches across canonical
  output, TrajectoryBundle manifest, CandidateBundle, sealed outputs, and durable execution record.
- Sensitive scan: zero `authorization`, `cookie`, `x-api-key`, or `axrun-local-tunnel` markers.
- Caller credential scan: zero matches across 102 Axrun state/artifact files.
- CandidateBundle and TrajectoryBundle manifests contain none of those markers.
- `inspect` reports TrajectoryBundle manifest/digest without embedding events.
- `export` produced separate `candidate/`, `trajectory/`, and verification result outputs.
- ModelProxy, connector, and TunnelSession completed unconditional idempotent cleanup.
- No Allocation workload container remained after completion.

Benchmark/production canonical acceptance remains `linux/amd64`. This run is the valid local
arm64 development E2E; the only remaining canonical-platform requirement is a reachable amd64
Axern node with matching task/rootfs canonical image digests.
