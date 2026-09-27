# Flask-5014 on released Axern v0.12.0

This is a single locked `pallets__flask-5014` acceptance, not suite or leaderboard
support. It supersedes the *capability blocker* in the
[v0.11.4 record](2026-09-27-swebench-flask-5014-claude-tunnel-blocked.md);
that historical failed episode was not reused. The reference/gold patch and
hidden tests were not supplied to Claude. The image audit establishes absence
of the locked patch signatures in accessible image bytes, not absence of every
possible unknown hidden artifact.

## Released stack and inputs

- Native `linux/amd64` on the registered `wayne-hk-dev` host. The managed
  release CLI and all running local stack components reported `0.12.0`; the
  [Axern release](https://github.com/cofy-x/axern/releases/tag/v0.12.0) points
  to `c6bbc9d12350e1df48acf15d233ca9683b83c308`. The node image was
  `ghcr.io/cofy-x/axern/node-all-in-one@sha256:991ce2e78126625ab99a7eae657ffc894bc9a6ad1e624c726fa22e8572715b26`.
- Axrun execution commit `bd2f6ed72b3032ae08be98121c83666da69a22d8` used the released
  `axern-sdk==0.12.0` PyPI wheel, locked at SHA-256
  `3adab79d86bd8dec8049f2ace66852ed76b27f6dda705876488b35302e4dd100`.
  No Axern source package or private Proto was used.
- Locked official source `linux/amd64` platform manifest:
  `docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4`.
  Reloading it into the v0.12.0 node returned the immutable runtime ref
  `index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:98b8b97b38b834eb5a9dad6a42a0380278a911afc74c7025b893ea79294a7da3`.
  Reloading the local amd64 Claude Code 2.1.205 rootfs returned
  `index.docker.io/library/axrun-claude-code-rootfs@sha256:df44581291434e694b4f9f054be19df394653d0e1fc5c1e893ed754cbe3fb13b`.
  Both returned digests matched the previous content identities; the imports
  were executed against the new stack rather than inferred from old receipts.
- The locked dataset row/oracle and complete per-test evidence are unchanged
  from [stage zero](2026-09-27-swebench-flask-5014-axern-parity.md). The
  fail-closed full-image audit receipt SHA-256 was
  `cf5ad56bff952cbb24c78bb13f66dfa7f4f5f3d961e57e8ce4e541532cfc5529`.

## Network and deterministic gates

A separate public-SDK `network-policy-sdk` profile created two fresh Runs on
the released stack. Its deny-all Run
`run-39e7a491-ae76-4f9a-abba-1f662f2f4482` /
`alloc-d81f6bc4-c3f0-41ae-a0fb-01ecf9a445a9` received no HTTPS 200 and
could not connect to direct-IP TCP; sealed output was 86 bytes, SHA-256
`9079a81a1273e733b58d245d95516e4cf3a5a364e4cf4f85d9c3eb5df26849c8`.
The unrestricted control `run-bc1c217e-5c3c-402b-9a39-47e4e0f2b87f` /
`alloc-466368bf-6d43-42f8-bfd1-be7dc630469b` obtained actual HTTPS 200
and direct-IP TCP; sealed output was 83 bytes, SHA-256
`829a65e057287e1cf628fa8f63a2514992192e439d0fc94fb0fc0b03e927f928`.
Both Runs succeeded; their temporary Environment was deleted and confirmed
absent. This independently checks the Axrun StagePlan-to-SDK network mapping;
the released [Axern #187 acceptance](https://github.com/cofy-x/axern/issues/187)
also checks undeclared Tunnel ports and revocation without egress grants.

The new v0.12.0 deterministic parity receipt SHA-256 is
`a0db0121a2fb9a8c6d6157a67bfda437ca2a1bfbb7e65ae2a7a5d63843b56df9`.
With separate parity Environments
`env-b7de116a-26ed-4ba4-af5f-458a6bf3bc82` and
`env-54a3fc08-c047-44f6-80bb-1dbec61be31a`, all cases matched the locked
oracle test-by-test, including classification and scoring denominator:

| Case | Inference Run / Allocation | Fresh verification Run / Allocation | Result |
| --- | --- | --- | --- |
| Gold | `run-75bd04e9-acdf-4ead-8688-723d58c17940` / `alloc-1fa9c6f5-139b-407a-ac0e-715ccd4e4cd7` | `run-27e89354-b820-4b27-8098-05e5f667bfcf` / `alloc-1010009c-1964-4cdd-b8e5-77a1072ca2fc` | 60/60, passed, score 1.0 |
| Known-bad | `run-c8bd000d-7317-4403-8ba0-4b298881d480` / `alloc-a7cb576c-f048-4cd9-9e2b-22eea25be193` | `run-c345bb02-3ac3-40d1-9e47-e4e79675ccd9` / `alloc-8d1c8b66-101f-4c68-b9e0-2eb3f29702d2` | 59/60, failed, score 0.0 |
| Empty | `run-a6e490c4-415b-419d-aed3-387f7cb1bc1a` / `alloc-3da3ac3e-a9b8-462f-9055-3dcac1b6479a` | `run-58a39242-9da1-4e44-9ee3-2b04ae1364d5` / `alloc-dfda8f3d-1cfd-4df3-863a-b5420dd69095` | official unscored, legal failed, score null |

Every listed Run and its qualification Run reached `RUN_STATUS_SUCCEEDED`.
Sealed file lengths and SHA-256 were independently checked. The two parity
Environments were deleted after the Claude acceptance and confirmed absent.

## Real Claude candidate and fresh verifier

The new episode `flask-5014-claude-f05d1cc494e240548f78fddaed5f2cf2`
used separate inference/verification Environments
`env-7da6be12-7932-413f-bfdd-20c5c2413194` and
`env-d87fa697-7161-45a4-832d-78a5c7f0d382`. Inference qualification was
`run-6e6abd61-7765-4613-b7fc-b9e640ce1879` /
`alloc-cabcaa59-c177-42ab-8c54-b3a935d2a3ce`; verification qualification
was `run-57984591-a741-44d2-9f06-3dc3a4bf37a6` /
`alloc-15218ace-3a3c-48f4-96dd-ba08b508b18c`. Qualification proved the
readonly Claude mount, Claude 2.1.205, Node 22.23.2, and image workspace.

The inference Run `run-6de9bbb6-3c1d-4e01-a190-632710db7d6d` /
`alloc-d3841441-ab40-4c67-8035-139210a0dc93` was persisted before
Allocation-scoped Tunnel setup. Public Run inspection showed network mode
`isolated`, only the non-secret Claude model/Tunnel configuration in sandbox
environment names, and the rootfs ImageMount at `/__claude_code`; qualification
independently confirmed that mount was readonly. A caller-only check compared
the actual credential against the public Run JSON and found no match.
Tunnel health and `/v1/messages` preflight completed before Claude was released;
preflight returned upstream HTTP 200. The proxy observed 18 safe request
summaries. Its final one was an Anthropic-compatible
`/v1/messages?beta=true` upstream HTTP 200. The Tunnel was revoked and the
caller-side ModelProxy stopped on completion.

The caller used `https://api.deepseek.com/anthropic`, main model
`deepseek-flash`, Opus/Sonnet `deepseek-flash[1m]`, Haiku/subagent
`deepseek-flash`, effort `max`, compact window `786432`, and 40 turns.
`DEEPSEEK_API_KEY` was checked for presence only, then read by caller-side
ModelProxy. The sandbox received the fixed
`ANTHROPIC_AUTH_TOKEN=axrun-local-tunnel` placeholder; neither the real key
nor Tunnel token entered the Run spec or declared outputs.

| Independently downloaded sealed output | Bytes | SHA-256 |
| --- | ---: | --- |
| `candidate.patch` | 1,393 | `e0df5c2cab8a654f5a5aa22814d20bcd438553ff2c1e396c92483e26a55d24d8` |
| `trajectory.jsonl` | 63,921 | `c22e5c5d273bfe5e02a6a016b665853561ebd703af585822312ac2fe0f0a4ecc` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 146 | `c21c0fedc904f9d43d6e611fc05ad2cade93922809198ce3a798f7e0223e92d9` |

The immutable CandidateBundle digest was
`f85607c00ffc3e78c669b291ee2c6db345d98751db723be659d5096ac72a9f1e`;
the separate TrajectoryBundle digest was
`4661173e753c00fd877c4a61e5bcd9b6e98cd3a74527a844a1cc3104826eb5da`
(72 canonical events). The verifier started from the different immutable task
Environment with no Claude mount, model Tunnel, credential, process, or
inference filesystem. Its fresh Run
`run-0c6913e5-0ed8-4595-8fdf-79e409eb7dc7` /
`alloc-5ee994ae-06e8-48ae-ae4b-6da6577cb950` also had `isolated`
network mode. `verification.json` sealed at 8,752 bytes / SHA-256
`affc119c0911088bd6df958f524fe441df086737733a948d3a8a742715910a7f`;
`verifier.log` sealed at 19,877 bytes / SHA-256
`c2c2634cc8ebff2ad3935a6ee2e1d93d7dcfb8dd9cbb2b0f45f31a23858d3f14`.
The VerificationResult digest
`7d6a65d3d9a9c0af402b0b0141c9c5354bfe725165872519e8aa11f88558295a`
references the exact CandidateBundle. All 60 expected tests passed, score
1.0, verdict `passed`, diagnostic code empty. This is an actual solved
single-instance run, not a claim about all SWE-bench tasks.

The private evidence credential scan found zero matches. The caller client
closed; Tunnel cleanup was `revoked`, ModelProxy cleanup `stopped`, and both
model Environments were deleted and confirmed absent. The validation profile
was `LINUX_VERIFY_HOST=wayne-hk-dev make linux-run REPO=axrun
PROFILE=swebench-flask-claude-axern` after the v0.12.0 parity profile on the
same committed Axrun candidate. The closed private configuration and full
per-test logs remain Git-ignored on the validation host.

## Boundary and follow-up

The catalog still does not expose this trial adapter through the generic
`axrun run` or `verify-record` CLI. The acceptance tool composes the exact
reviewed adapters explicitly and checks the sealed candidate, trajectory,
qualification, and result chain. General catalog registration needs its own
reviewed image-secrecy gate so an arbitrary caller cannot bypass the
pre-inference audit; this successful trial alone does not create general
Flask or SWE-bench suite support. The native oracle uses the pinned upstream
test script and scorer but does not invoke upstream `run_instance`.
