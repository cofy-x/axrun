# Flask-5014 real Claude acceptance: isolated Tunnel capability gap

This is a **blocked** real-model acceptance, not a Claude candidate or a
SWE-bench score. The [deterministic official parity](2026-09-27-swebench-flask-5014-axern-parity.md)
remains valid; the official instance is not registered as a completed model
vertical. No inference workload was released, no CandidateBundle or
TrajectoryBundle was built, and no fresh model-candidate verifier verdict exists.

## Locked setup and image gate

- Axrun branch `feat/swebench-flask-stage-zero`, acceptance diagnostic commit
  `56ac11195b9b226082548005bc6ee5024b43ece4`; published
  `axern-sdk==0.11.4` and released Axern CLI/local stack v0.11.4 on native
  `linux/amd64`. The rootfs qualification used Claude Code 2.1.205 and Node
  22.23.2.
- Official task source platform digest:
  `docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4`.
  Axern imported runtime digest:
  `index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:98b8b97b38b834eb5a9dad6a42a0380278a911afc74c7025b893ea79294a7da3`.
  Readonly Claude rootfs ImageMount digest:
  `index.docker.io/library/axrun-claude-code-rootfs@sha256:df44581291434e694b4f9f054be19df394653d0e1fc5c1e893ed754cbe3fb13b`.
- The fail-closed `axrun.swebench-flask-image-secrecy@2` receipt SHA-256 is
  `cf5ad56bff952cbb24c78bb13f66dfa7f4f5f3d961e57e8ce4e541532cfc5529`.
  An offline, readonly, no-host-mount audit scanned 59,754 regular files
  (3,340,526,784 bytes) and 23,268 Git objects (152,379,907 decoded bytes,
  including unreachable objects); locked official test-patch and reference-patch
  added-content signatures had zero matches. This proves only absence of those
  locked signatures in the audited accessible image bytes, **not** absence of
  every unknown secret or archive-encoded content. The earlier target-path-only
  `@1` receipt is deliberately incompatible with the model gate.
- The caller-side configuration used the non-sensitive endpoint
  `https://api.deepseek.com/anthropic`, main model `deepseek-flash`, Opus/Sonnet
  aliases `deepseek-flash[1m]`, Haiku/subagent `deepseek-flash`, effort `max`,
  auto-compact window `786432`, and `max_turns=40`. The caller checked only
  the presence of `DEEPSEEK_API_KEY`; the sandbox plan used the fixed
  `axrun-local-tunnel` authentication placeholder.

## Fresh attempts and terminal evidence

Both attempts used new, separate inference and verification Environments from
the same immutable task digest. The qualification Runs succeeded, including
readonly Claude rootfs and task workspace checks. The inference Run ID was
persisted and its Allocation reached RUNNING before ModelProxy/Tunnel setup.

| Attempt | Inference / verification Environments | Inference Run / Allocation | Tunnel result | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | `env-9d8a6dbd-baaf-4f31-a920-4cef74450a55` / `env-3d11b8c9-ef8b-42d7-8551-a44f35fcb8d2` | `run-c08f3e40-274b-4bb3-96ba-e66cd39a0f2f` / `alloc-fa9ea9f5-47c8-42f2-b44c-3c6d8af0958c` | `tunnel_health_failed` before session/token; no workload release | Run cancelled; both Environments deleted and confirmed absent |
| 2 | `env-83defd0e-fef2-4d3c-8b26-2d7f42e32112` / `env-528def72-a57e-4b44-b87e-6cb5f7e96305` | `run-a6c2ed80-5702-4630-befe-5c4b3e092183` / `alloc-40087c63-0bcf-4a60-bb3d-24522bef0304` | Public SDK `create_tunnel_session` returned gRPC `FAILED_PRECONDITION` before session/token; no workload release | Run cancelled; both Environments deleted and confirmed absent |

Attempt 2 inference qualification was
`run-3c93414a-d408-45b7-b911-d136e92f1142` /
`alloc-bed49462-51c6-47f9-9408-0ec526e7e3ec`; verification qualification
was `run-ee3809f3-f99c-4794-b5b1-a84ffb81ec5d` /
`alloc-7999fd4a-cda7-43f3-9344-762319197fb2`. The first attempt's
qualification identities and both private failure receipts remain in
Git-ignored validation evidence. Each failure receipt reported
`credential_scan_matches=0`, caller client closed, ModelProxy stopped, and no
TunnelSession to revoke. Neither attempt reached health/preflight, upstream
model request, sealed candidate outputs, or verification.

Axern v0.11.4 [documents](https://github.com/cofy-x/axern/blob/v0.11.4/docs/architecture/sandbox-network-policy.md)
that deny-all Allocations have no host network interface and no reachable
sandbox port for Tunnel. The observed `FAILED_PRECONDITION` agrees with this
contract. It is **not** evidence that the v0.11.4 egress fix is broken. Axern
[issue #187](https://github.com/cofy-x/axern/issues/187) requests an explicit
ingress-only Tunnel capability that preserves deny-all egress; Axrun must not
substitute unrestricted networking or a dummy allow rule.

## Reproduction boundary

The registered HK validation profile is
`LINUX_VERIFY_HOST=wayne-hk-dev make linux-run REPO=axrun PROFILE=swebench-flask-claude-axern`.
It requires fresh caller-created inference/verification Environment IDs in the
Git-ignored closed config and a caller-only `DEEPSEEK_API_KEY`. With the current
released Axern contract, a fresh run will fail at Tunnel creation. Do not run
this profile as a supposed model-score acceptance until #187 has a released,
security-reviewed ingress path; no benchmark score is claimed here.
