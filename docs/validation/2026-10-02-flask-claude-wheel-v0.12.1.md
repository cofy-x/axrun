# Real Claude independent-wheel Flask acceptance on Axern v0.12.1 — 2026-10-02

## Outcome and scope

One new `pallets__flask-5014` episode ran the real Claude Code harness from an independently installed Axrun wheel against the released Axern v0.12.1 local stack on native `linux/amd64`. The normal CLI sequence `admit → resolve → qualify → run → completed resume → verify-record → report` returned exit code `0` at all seven steps. Five new public Runs and Allocations—the image admission, two qualifications, inference, and fresh verification—succeeded. The final report has `integrity_verified=true`, an empty diagnostic, verdict `passed`, score `1.0`, and an exact 60/60 match to the locked official gold test map. This is a new model-backed episode, not a retry of the earlier [v0.12.1 static-gold cold start](2026-10-02-flask-wheel-cold-start-v0.12.1.md) or the [v0.12.0 Claude CLI acceptance](2026-09-28-flask-cli-admission.md).

The original private acceptance helper wrote a `failed_closed` summary after all seven CLI calls because its post-CLI audit accessed `result.details["resolved"]`; `resolved` is a top-level field of the sealed `verification.json` output, not a `VerificationResult.details` field. The original summary remains unchanged at SHA-256 `db3c1175ee26ad4c7226d4d23e968a4e8d8d686b5e7a9eb3acb09fa9ef1ac346`. A separate post-hoc finalization checked the existing record, public Runs, independently downloaded sealed bytes, model progress, locked test map, credential scan, and exact cleanup without rerunning the episode. Its `complete` receipt is `posthoc-finalization.json`, SHA-256 `cdc6251497fb088e405ff454c2050de77f620ca7a95a5972fcfab7134448f76b`. The helper error is retained as an audit-tool failure, not presented as an Axern or Axrun CLI failure.

This is one scoped consumer acceptance of the registered `swebench-flask-official@1` task/verifier pair. It is not generic SWE-bench or suite support, leaderboard eligibility, official environment-equivalence proof, load testing, or exhaustive startup-race coverage. The model happened to solve this instance; solving it was not a precondition for proving the execution and isolation path.

## Released consumer and fixed inputs

- Axrun source commit: `715d84e4dd8eca568fa7715c01e7d8572aa86b55`. The separate `axrun-0.1.0.dev0-py3-none-any.whl` has SHA-256 `5e87367e755a5cf28c024f09965a6ad4a0bd71b838bd16a1e5851f1e7fbd4e37`. The fresh `linux/amd64` Python `3.12.3` installation verified 81 installed wheel Python files, the `axrun.cli:main` entrypoint, no source-checkout imports, and public `axern-sdk==0.12.1`. The caller credential was present only in the caller process; no credential was installed in the wheel or episode state.
- Locked instance `pallets__flask-5014`: complete enriched-v1 row SHA-256 `36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e`, seed digest `077cf80a3e58c24d38ab8124db646a70b4f0a5d3ad389685d0f52d1b466835eb`, and pre-existing official gold grade SHA-256 `bddca4fbdf735900724faee6494a3c3acdeb6e78fcf813e7ef6147dc7659cd51`. The [locked Flask CLI acceptance](2026-09-28-flask-cli-admission.md) records the upstream dataset/scorer revision and oracle provenance; this run did not regenerate the oracle.
- Source task manifest: `docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4`. Actual imported Axern runtime: `index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:98b8b97b38b834eb5a9dad6a42a0380278a911afc74c7025b893ea79294a7da3`; image-import provenance digest `60b267c2b18acd5c6e9c3488d84724dcfa2a19081df84e5b4a71f08d8e0d7a49`. The source and runtime manifests are distinct identities.
- Claude Code `2.1.205` used the read-only amd64 rootfs `index.docker.io/library/axrun-claude-code-rootfs@sha256:df44581291434e694b4f9f054be19df394653d0e1fc5c1e893ed754cbe3fb13b`, with reimport receipt digest `5f5717f828ac65e455cbd5cc73caed826f0691863956f1e3f7771507f95f2851`. `/testbed` was the task working directory. Inference and verification both requested `deny_all` networking; `WebFetch` and `WebSearch` were disabled. The primary/Haiku/subagent model was `deepseek-flash`, Opus/Sonnet `deepseek-flash[1m]`, with effort `max`, auto-compact window `786432`, and max turns `40`. The upstream credential came from caller variable `DEEPSEEK_API_KEY`; the sandbox received only the fixed non-secret Tunnel sentinel.

Admission ran against the **actual imported runtime**, not the source-image name. The `passed` receipt, SHA-256 `b63b5efc4ef4bb21f871d421f57d8bbfecd59e445a1952188572a4153cfb4065`, reported `no_locked_patch_signatures_reachable`; its sealed 1,425-byte audit SHA-256 was `d762a453fc575e3293cbd9f8fa13e9409799e36caea3b46e85ef684b9da695ef`. This is a bounded locked-signature scan, not a claim that every possible unknown secret is absent.

## Public execution and sealed evidence

Episode ID: `flask-wheel-0121-claude-0323967f86a94303a8e55b4feb472cc4`.

| Role | Environment | Run | Allocation |
| --- | --- | --- | --- |
| Admission | `env-ab967e86-76e1-4e54-92a5-11aa40bdd3a5` | `run-47487a81-aae3-4aa0-89a6-5d366b574d50` | `alloc-9a4a174e-e832-4ad3-a5f3-615d39d8ff13` |
| Inference qualification | `env-3f7a6b8d-60f4-40a6-8b5d-abd2f519c875` | `run-0582b74f-2925-4966-9939-e7f4a1743b8e` | `alloc-c8a2b589-1d10-4589-aa38-3e20b51d60eb` |
| Verification qualification | `env-7416d3ac-0ba0-4ed1-9076-84899e290239` | `run-d8701dc1-4a4b-4b36-babc-0a036de35066` | `alloc-d04149b8-c4e9-4289-bfbe-d5554a42a6f6` |
| Claude inference | `env-3f7a6b8d-60f4-40a6-8b5d-abd2f519c875` | `run-901ac8ab-9c87-44a1-8b7b-93db6d5bd82d` | `alloc-a189f377-80b0-4be1-90ad-806a8df19977` |
| Fresh verification | `env-7416d3ac-0ba0-4ed1-9076-84899e290239` | `run-0a1233a1-6207-4601-842c-a6aa6b4e3839` | `alloc-b2815205-f89d-4883-b0f6-6f2e8d1d78b3` |

All five public Runs finished `RUN_STATUS_SUCCEEDED`. The nine declared outputs were downloaded and checked twice against their public sealed metadata and byte digests, first in the original helper and again in post-hoc finalization:

| Role / sealed output | Bytes | SHA-256 |
| --- | ---: | --- |
| Admission `/outputs/flask-image-audit.json` | 1,425 | `d762a453fc575e3293cbd9f8fa13e9409799e36caea3b46e85ef684b9da695ef` |
| Inference qualification `/outputs/qualification.json` | 423 | `5fa72546531ad62af1149c0333b96c675f8bf575a5dde77f5196635cec42846c` |
| Verification qualification `/outputs/qualification.json` | 300 | `d4380c46c4d6b7c3706bb53b385ca11367e22dcabcdec569928e00b6983ab0f9` |
| Inference `/outputs/candidate.patch` | 1,434 | `9876390145115d9a2904cd6bc63314f1f2fd1ea07da616e0194960c9c23603fe` |
| Inference `/outputs/harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Inference `/outputs/trajectory.jsonl` | 42,585 | `17fe5f1fdd0755d10ca2ec2e12d91a650e28c1fe40d93770761d4e494c0b2d4c` |
| Inference `/outputs/usage.json` | 146 | `5caf93e7ca69497abe400403557ff5ae43df31d12448cac2bafb4e19396dcecf` |
| Verification `/outputs/verification.json` | 8,752 | `43f209ab041b93ac960db469720719f4bbf75a006975a14f2223dc8a4b9a2216` |
| Verification `/outputs/verifier.log` | 19,918 | `945c0d9b0e4bb8de476fa7512d68bc59cc6784437f589bf26a607cc34d597a11` |

The immutable CandidateBundle digest is `e0919c09ecc2f385596c8d9b09d997d3c56933068b30ce344906fcfddaf2a802`; TrajectoryBundle digest `e41f752aea1103771a58d33f32f6735d8b80da77af51d05092c32c2c86bd6273` contains 77 canonical events; VerificationResult digest is `ea6ee4d93c0b626d95157ef17b42a35fc934f0248b10d560a6eb39f326ed7f8a`. The post-hoc check linked the candidate patch and trajectory/usage bytes to their bundles, the result to the candidate and sealed verification output, and the JSON report back to those digests. The report SHA-256 is `367b39d558c24717e03b6728c9d057e72f5bc6922dd11c96eeed8256f97e6a9d`; completed `resume` left the original record bytes and result unchanged, and `verify-record` produced the same report. This tests completed replay, not recovery of a live model session.

The verifier's complete 60-entry status map and category arrays matched the locked official gold grade; all 60 expected tests were observed and passed, with zero failed or missing, `resolved=true`, and no diagnostic. No hidden test body, model request/response body, sensitive header, real credential, or Tunnel token is included in this record.

## Model transport and cleanup boundary

The caller-side ModelProxy progress recorded 20 model requests. The final recorded request was an Anthropic-protocol `POST /v1/messages?beta=true`, HTTP `200`, reason `upstream_response`; the count and final status establish a real model path without disclosing request content. The exact-value credential scan of the private evidence tree returned **0 matches**. Inference and verifier used separate Runs and Allocations; only the immutable CandidateBundle crossed their boundary.

The successful CLI `run` includes the Tunnel revoke and caller-side proxy teardown contract, but no independent post-hoc TunnelSession enumeration was available or claimed. Post-hoc cleanup confirmed every owned Run terminal and each Allocation inactive, then deleted only the three exact owned Environments and verified each deletion. Public Run and sealed evidence remained retained; the shared stack, images, and unrelated workloads were not removed. This single acceptance does not replace platform-specific Tunnel revocation or network-policy regression tests.
