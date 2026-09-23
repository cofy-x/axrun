# Apple Silicon amd64 source-Compose runtime blocker — 2026-09-19

This record captures the canonical `linux/amd64` acceptance attempt for Axrun's live Claude
progress work. Image construction, import, Environment resolution, and released-SDK control-plane
access succeeded. The source-Compose node could not start an amd64 gVisor sandbox under Apple
Silicon emulation, so no Claude inference or verifier result is claimed.

## Provenance

- Axrun implementation commit before this record: `fe1b0901cd87955d42aff5587a91983db56158bc`
- Axern source commit: `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`
- released SDK: `axern-sdk==0.9.1`
- SDK import: Axrun's `.venv/site-packages/axern_sdk/__init__.py`
- caller credential environment: `DEEPSEEK_API_KEY` present; its value was never printed or
  persisted

The cluster was switched with Forge's public wrapper while preserving Compose state. `status`
reported `architecture=amd64` for postgres, controld, tunneld, node, gatewayd, and dns-fixture,
and reported `amd64_compose=ready`.

## Canonical images and Environment

The official SWE-bench image contains the row's base commit but its default `/testbed` HEAD is an
environment snapshot commit. Axrun therefore built the checked-in thin amd64 seed definition,
which pins the official manifest and produces a clean detached workspace at
`7fa1a93c6c8109010a6ff3f604fda83b604e0e97`.

| Role | Local image ID | Axern canonical digest |
| --- | --- | --- |
| task seed | `sha256:153d7673b16122e073e11c9ce7ef6d3a698dd26d370633c5247bcead44abfa0d` | `index.docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419@sha256:2d7b1d1e01a1c58633cf77c132a84baf358bc9b7305d3ddcac5f2d7d93743806` |
| Claude Code 2.1.205 rootfs | `sha256:068342f05d97bcd38dc9a4490d0925c075ee3a9727d844bf7f781b1777ab8117` | `index.docker.io/library/axrun-claude-code-rootfs@sha256:adf18deaad51a37b8b92d2731b1d20b494bb11974210f6c4d29ae35d5d3cb7aa` |

The writable task Environment is
`env-69a7fdee-34f6-468c-9156-0f4843a7970f`. It resolves the exact task canonical digest above.

## Failed canonical episode

- episode: `swebench-django-12419-amd64-progress-20260919-01`
- seed digest: `b3424f86226407a6f1b04e2c70a90ac27a1935d1772ef432f0bbd1898b93d471`
- spec digest: `c026492c41c360051e924e80f2e51fabbd1640c22eebf3d91b0774595df4582a`
- terminal diagnostic: `AXRUN_STAGE_FAILED`
- Axern classification: local placement rejection, `capability_unsupported`
- inference Run / Allocation: none; rejection occurred before Run persistence
- upstream model requests: none

The amd64 node's runsc ephemeral-storage capability self-test fails during node startup. A writable
rootfs Run therefore fails closed at placement because Axern correctly requires that enforcement
capability.

## Public-SDK minimal reproducer

To distinguish the writable-rootfs capability rejection from the runtime itself, a second
Environment was created from the same image with `rootfs_readonly=true`:

- Environment: `env-0bd7fc8f-a11f-4312-a240-db15a8531ae3`
- Run: `run-e6f83844-a22c-4d0a-b904-4c70d3628d2c`
- Allocation: `alloc-fa2b7634-1ae4-419e-aaf8-306d54379505`
- terminal status: `RUN_STATUS_FAILED`
- diagnostic: `WORKLOAD_DIAGNOSTIC_CODE_RUNTIME_START_ERROR`

This Run passed placement, but each `runsc create` attempt exited 128 before sandboxd became
available. The public Run message ends with `cannot read client sync file: waiting for sandbox to
start: EOF`; runtime cleanup completed through Axern. The sanitized node evidence is in
`/var/log/axnoded/axnoded.log` inside `axern-source-node-1`. No private API or Proto was used.

Together, these two paths prove the single blocker: the emulated amd64 node cannot start its gVisor
sandbox. Changing Axrun resource fields, workspace paths, model configuration, or credentials
cannot make the requested inference execute.

## Security and acceptance state

The failed episode record, resolved assets, and episode JSON were scanned without displaying the
secret. Match counts were zero for the caller credential value, `axrun-local-tunnel`, and sensitive
header names. No Tunnel session, ModelProxy upstream request, sealed inference output,
CandidateBundle, TrajectoryBundle, verification Run, or VerificationResult was created.

All deterministic progress tests and repository quality gates pass, including 92 tests. The real
Claude candidate → fresh verifier closure remains uncompleted only because no amd64 Allocation can
start on this emulated node.

## Resume command

After `scripts/axern/local-amd64.sh status` is backed by an amd64 node that can complete a minimal
SDK Run, resolve a new episode ID and execute it; do not reuse the failed episode above. With a new
resolved episode at `$EPISODE_JSON`, the acceptance command is:

```bash
uv run axrun \
  --state-dir .axrun \
  --context-file "$HOME/.config/axern/config.json" \
  --context compose \
  --model-upstream-url https://api.deepseek.com/anthropic \
  --model-credential-env DEEPSEEK_API_KEY \
  run "$EPISODE_JSON"
```

The caller must supply `DEEPSEEK_API_KEY` only through its environment. The new episode must use
the two canonical image digests and Environment produced for the working amd64 node.
