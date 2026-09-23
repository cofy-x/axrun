# ProgramBench seqtk provenance-policy v2 acceptance

Status: a fresh Claude Code 2.1.205 episode completed with a legitimate compile-failed verdict. This is an execution and provenance-evidence check, **not** a passing candidate or an official leaderboard integrity attestation. ProgramBench 1.2.4's [submission integrity attestations](https://github.com/facebookresearch/ProgramBench/blob/main/src/programbench/data/templates/README.md.j2) require a separate, supportable claim about source provenance.

## Locked inputs

- Axrun candidate commit `2210ce30e997f4c9d81919855c0be97fecb4c1fa`, released `axern-sdk==0.11.3`, and released Axern local stack/CLI `v0.11.3` on native `linux/amd64` `wayne-hk-kvm`.
- ProgramBench `1.2.4`, git `963063c9271cc40fa179977356782ea4582e0b0c`, locked instance `lh3__seqtk.94e7070`, test revision `de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5`. Blob and evaluator locks are unchanged from the [deterministic acceptance](2026-09-23-programbench-seqtk-axern-v0.11.3.md).
- Task image `index.docker.io/programbench/lh3_1776_seqtk.94e7070@sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0`; verifier image `index.docker.io/axrun/seqtk-evaluator@sha256:f777ae80f074fbe841afebb3d66e7d0753b8442455e4fb94a714bfc069e9f61b`; readonly Claude rootfs `index.docker.io/library/axrun-claude-code-rootfs@sha256:acce229813389a0aaa65e1a0407b58700175cc0d9c877299159ac7d7b6fd0da3`.
- The new `programbench-1.2.4-seqtk-94e7070-v2` row explicitly requires reconstruction from executable behavior and bundled documentation only. Its seed digest is `4e947c65d12af6ee8c6eaf8ec7c03c8107a63332fdd2495eab2225b82a54c7aa`. The official evaluator, test identities, denominator, network policy, and timeout were not changed.
- Model endpoint `https://api.deepseek.com/anthropic`; primary `deepseek-flash`, Opus/Sonnet `deepseek-flash[1m]`, Haiku/Subagent `deepseek-flash`, effort `max`, auto-compact window `786432`, max turns `40`. The caller selected `DEEPSEEK_API_KEY` by variable name; the sandbox received only the fixed authentication placeholder.

## Bounded attempts

The first new episode, `seqtk-integrity-v2-20260923-01`, used inference Environment `env-d348aef8-6ee6-444d-872e-5981bd307e4f` and separate verifier Environment `env-6fad4090-c472-4586-a39d-56084e4569b7`. Its inference qualification was `run-1965c006-1d94-4383-a564-e9e125b11826` / `alloc-23784eb8-c7d6-40e2-8170-0df332062274`; verification qualification was `run-39787ea7-d940-40b4-aef9-af62694e85cd` / `alloc-901c25fb-c130-4a29-bbe3-ee0f68b44f73`. Qualification confirmed amd64, the execute-only seed reference, readonly Claude 2.1.205 mount and Node 22.23.2. After successful tunnel/model preflight, inference Run `run-1ec7531d-306f-4199-9a46-a03a1d4b4b11` / `alloc-5e1c9233-e273-450d-a0ea-4724c1d61bb1` encountered an upstream HTTP 503 (`upstream_response`) during inference. It terminated failed/1; no CandidateBundle or business verdict was fabricated.

One replacement episode was designated as the final attempt, `seqtk-integrity-v2-20260923-02`, using the same immutable input row and Environments but new Runs and Allocations. Its qualification result digest was `7ced9a874c2deb21489f4b010594f26d58aaa5cb359982099294b8c1648f09ca`; inference qualification was `run-14cf2b46-a4cc-49d1-be66-35bba9003cc2` / `alloc-dcea2de8-ed8c-432b-b103-8eaeb00bdc19`, and verification qualification was `run-d0c07eb9-3a83-43e4-bd81-78363eb420f2` / `alloc-23d7c25b-3458-453f-a64c-c85fb6e7c5ee`. Inference Run `run-891a424c-d309-4329-b96a-b17322773f5e` / Allocation `alloc-daa11191-4fcd-44c2-a5ae-be887ca37e57` received successful model responses, reached the explicit 40-turn limit, and sealed a candidate rather than silently rerunning.

| Sealed inference output | Bytes | Independently recomputed SHA-256 |
| --- | ---: | --- |
| `workspace.tar` | 71680 | `cba0c777dc4c5ba309688030931709326c6f3420c506c40934eabf1ce16dc66f` |
| `trajectory.jsonl` | 109167 | `ed7cb4afd180d08f38efdf6185fa8d6053ff8bb2770efff9f90d48195961a6e9` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 148 | `cde9fecb20e62536fe5a11e6b2c65181054319dd7926b9077e4878e6f2f71b13` |

The immutable CandidateBundle digest is `c0ddb58b443d0f2515c5f3d8f5ee1324d5e3757763bc0c6ad9dff450888dd867`; TrajectoryBundle digest is `2e3ee739407c5a8cc202ee1cd7d0e29d17500fe40639650f97380e82fa6f7f85`. `axrun verify-record` independently returned `integrity_verified=true` with 173 canonical events.

The fresh compile Run `run-0b9123f7-c67d-478e-a90e-be7d8d2a8c82` / Allocation `alloc-1f3f4d4c-6e89-45a5-ba4c-acd02a40eb13` was in the separate verifier Environment and exited failed/22. The benchmark-owned coordinator classified this as `business_failed`; it produced no rootfs result or derived Environment, and no branch Runs were launched. VerificationResult digest `45197120b3fb70fecd657344a1d9c22b4ea43cdd8101b63b6dcf45f5480e3d2d` references the exact CandidateBundle and records `failed`, score `0.0`, diagnostic `PROGRAMBENCH_COMPILE_FAILED`. It is not a 429-test parity result.

## Provenance and cleanup

The body-free review of the historical v1 candidate found 5 network-retrieval tool calls and 1 bundled ELF. The new v2 candidate review found 0 network-retrieval calls, 0 package-registry calls, 0 WebFetch/WebSearch calls, and 0 bundled ELF files. Both reviews remain `human_attestation_required`: tool-call text matching is advisory, blocked requests do not imply external consultation, and no trajectory can prove what source a model already knew.

A value-based scan of 47 private evidence files across both new attempts found zero occurrences of the caller credential. After both Runs, the public Tunnel list contained zero sessions. The two base Environments created for this acceptance were deleted, and public queries confirmed both absent. No Axern, ProgramBench, Openbench, or Forge source was changed. Private artifacts remain under `/data/forge-artifacts/seqtk-integrity-v2.JeFeNS` and `/data/forge-artifacts/seqtk-integrity-v2-retry.rZ2M9h`; neither directory is a public dataset input.

To review a completed episode without printing tool arguments or response bodies, run:

```bash
uv run axrun --state-dir STATE_DIR verify-record EPISODE_ID
uv run axrun --state-dir STATE_DIR review-programbench-provenance EPISODE_ID
```

This acceptance advances issue #6's evidence and policy boundary but does not close it. The explicit prompt and zero-risk-count review are not a substitute for the upstream human provenance attestation. The tty-clock partial TUI variability remains independently tracked by issue #3.
