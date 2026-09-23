# ProgramBench seqtk real Claude Code acceptance on Axern v0.11.3

Status: passed for one locked official instance. This is not suite or leaderboard support, and it
does not resolve the tty-clock partial-result discrepancy tracked by cofy-x/axrun#3.

This is an execution and scoring acceptance, not an attestation that the candidate is eligible
for an official leaderboard submission under the upstream
[integrity attestations](https://github.com/facebookresearch/ProgramBench/blob/main/src/programbench/data/templates/README.md.j2). A later private-evidence review found attempted `curl`,
`wget`, and `git clone` commands in the canonical trajectory, despite the enforced deny-all
sandbox network. It also found a prebuilt fallback file in the submitted archive. The verifier's
compiled executable hash differs from that fallback, so this run does not show the fallback was
used; nevertheless, a 429/429 score and network isolation alone do not prove compliance with
ProgramBench's source/provenance restrictions. No hidden test body or credential is disclosed here.

## Fixed identities

- Axrun execution commit: `8c7cd39581b1bce0dbe33359edf1ceb88796d97b` (the CLI exact-option
  parsing fix from this branch). Released `axern-sdk==0.11.3`; released Axern CLI and stack
  `v0.11.3` on native `linux/amd64` `wayne-hk-kvm`.
- ProgramBench `1.2.4`, git `963063c9271cc40fa179977356782ea4582e0b0c`, instance
  `lh3__seqtk.94e7070`; locked test revision
  `de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5`. The test blob sizes and hashes, evaluator
  dependency lock, and native/static baselines are recorded in
  [the deterministic acceptance](2026-09-23-programbench-seqtk-axern-v0.11.3.md).
- Official task image: `index.docker.io/programbench/lh3_1776_seqtk.94e7070@sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0`.
- Axrun evaluator image: `index.docker.io/axrun/seqtk-evaluator@sha256:f777ae80f074fbe841afebb3d66e7d0753b8442455e4fb94a714bfc069e9f61b`.
- Claude rootfs: locally built image ID
  `sha256:48f202ab91e59f910405b88cf980366a4c5f5cdd77e29a9e681882a7ddb486cd`, imported
  through released `axern local image load` as
  `index.docker.io/library/axrun-claude-code-rootfs@sha256:acce229813389a0aaa65e1a0407b58700175cc0d9c877299159ac7d7b6fd0da3`.
  Its independent Docker check confirmed Claude Code `2.1.205`, Node `22.23.2`, amd64 ELF,
  `/__claude_code/l` PT_INTERP, and readonly bind-mount execution.
- Model proxy: Anthropic-compatible `https://api.deepseek.com/anthropic`; model `deepseek-flash`,
  Opus/Sonnet `deepseek-flash[1m]`, Haiku/Subagent `deepseek-flash`, effort `max`, auto-compact
  window `786432`, max turns `40`. Caller selected `DEEPSEEK_API_KEY` by name; its value was never
  placed in the resolved episode or sandbox. Sandbox authentication was the fixed placeholder.
- Resolved seed digest: `67164b8de88ce1b83047939fcdffecb14ac02e8e26322c3132b6f100c4afd20d`.
  Episode ID: `seqtk-claude-v0113-20260923-01`.

## Qualification, inference and sealed outputs

Inference Environment `env-f9199809-d8d8-4065-a10c-873d939293f3` and different verification
Environment `env-2e0999a2-6283-46fe-9c73-1de2b513a813` were created from the immutable image
references above. Qualification Runs were
`run-ac004a97-a1a4-4874-8b63-d5cf79a2f443` / `alloc-de83c6f1-f1a0-43ff-aaff-816100f067fb`
and `run-2c082c2c-3de8-4ee5-8742-02d68f1eb264` /
`alloc-446f3b93-71dd-4944-a654-b20edc9a6684`. Qualification confirmed x86_64, the seed
`/workspace/executable` as a regular file with mode `0111`, and Claude 2.1.205/Node 22.23.2 from
the readonly ImageMount. The inference StagePlan used deny-all networking and disabled WebFetch and
WebSearch.

Real inference Run `run-f00c9217-1030-45ff-bc06-1bf0d7cfa3c4` /
Allocation `alloc-fb6d854d-5f98-484b-b518-728af080e559` was persisted before ModelProxy and
Allocation-scoped Tunnel setup. Tunnel health and model preflight succeeded before inputs-ready.
The caller-side proxy observed successful Anthropic-compatible upstream responses. The Run
finished successfully; the tunnel session `tun-d9bc875cddb258a25c2b4c378868e91f` was revoked.
No active session remained for this Allocation.

All four declared files were downloaded through Axern sealed output. Axrun checked each download
against the SDK-reported byte length and SHA-256; a separate local recomputation yielded:

| Sealed output | Bytes | SHA-256 |
| --- | ---: | --- |
| `workspace.tar` | 266240 | `6427502f03527ce462a856bf35e12b860833e968e8fc082679041927ba922f48` |
| `trajectory.jsonl` | 152051 | `985011246f64739189e16cd2f6b3a56fea3e07379d94cb0d8659966d395ba08e` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 148 | `8419c3cb2f7c948a3d40a94efd537ce69bbf7920878eef92ceea54467b3851b3` |

The empty harness log is a valid sealed file, not a missing output. The immutable CandidateBundle
digest is `7258a401c9ad7f7b68cdcfda2a9693c50b90aaf0ab52ee6c3b71e9ae514e39c2`;
TrajectoryBundle digest is `26208e9daed1a65eb85d95df70d51f1f34679187ae8e63ecfbaa7d7f80112f7e`.
The candidate archive omitted the seed-owned top-level `executable`. Its 35 files contained no
byte-for-byte copy of the seed executable (SHA-256
`348c6e08241681487a4031afd1c34c6970409209adaed9e8a04330be0c0b1e7b`). It did contain
agent-produced source, `compile.sh`, and a prebuilt fallback at `src/prebuilt/seqtk-linux-x86_64`
with a **different** SHA-256,
`57d19ab53bc3677b32ae347f85a33327e0e87f63350e205b5ce20c5ed87225c7`.
The branch blob identifiers and sensitive header names did not occur in the four inference outputs.

## Fresh official verification

The immutable bundle alone entered the different verification Environment. Compile Run
`run-a4168859-c2cb-438f-9f03-fe069d455d17` /
Allocation `alloc-d92654ec-9e36-4f63-a96f-d58b03665418` was created with
`rootfs_snapshot=True`. The workload reached `succeeded` with exit code 0; the independently
queried rootfs result was `ROOTFS_SNAPSHOT_STATUS_READY`, digest
`sha256:ce892e6c43ad2da58bc7a49c563e445cae8cf7e03a5863c8b96d03e1419c68eb`, returning
derived Environment `env-d4f961ea-57ed-512b-aedb-7e40fcc9ca1a`.

Each active official branch then used a fresh Run and Allocation from that same derived
Environment:

| Branch | Run | Allocation |
| --- | --- | --- |
| `5d974fdda794` | `run-bf869bab-ca69-4b0f-a813-3acae9b15064` | `alloc-4e491157-d5bf-46b7-b20e-ea251aa42922` |
| `e592c32aec70` | `run-bf7407dc-4265-4f63-bf36-bab151aa4f85` | `alloc-1b32f212-d33b-4f11-b871-0a9d5726b1ab` |

Both branch Runs succeeded. The full 429-row test map reports 429 passed, 0 failed, 0 not-run;
2 active branches, 0 ignored branches, 11 ignored tests, no branch or compile error. The compiled
executable SHA-256 is `dcd073ddf2fa9fc11352443d25b00912ddc4719099348e8573f2c1b86a4f9d53`.
Official single-instance score is `1.0`, `resolved=true`; final verdict is `passed` with an empty
diagnostic code. VerificationResult digest
`2a5ff5bbd23630e9d364711d0a6b913a18264230c24b480cc50056233899bbe6`
references the exact CandidateBundle digest. `axrun verify-record` returned
`integrity_verified=true`.

The verifier's derived Environment cleanup state was `completed`; the caller then deleted both
base Environments. Public queries confirmed all three Environment IDs absent. A value-based scan
of 40 private evidence files found **zero** occurrences of the caller credential. This scan did
not export the credential to a file. Complete private evidence, including per-test records and
sealed artifacts, remains at `/data/forge-artifacts/seqtk-claude-v0113.UR5S8smM`.

The first resolver invocation stopped before creating an episode because argparse considered
`--model` an ambiguous abbreviation of caller-side `--model-*` options. Axrun now disables option
abbreviations and has a regression test; the successful episode above was resolved only after
that correction. No test, denominator, timeout, official evaluator, or Axern source changed.
