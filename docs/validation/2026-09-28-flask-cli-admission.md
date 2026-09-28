# Locked Flask normal-CLI admission acceptance — 2026-09-28

## Scope and baseline

The registered `swebench-flask-official@1` task/verifier pair completed the normal
CLI path on a Forge-registered native `linux/amd64` host:

```text
admit → explicit resolve → qualify → run → completed resume → verify-record → report
```

Exactly one gold, known-bad and empty episode ran, in that order. After their
complete official test-level parity passed, exactly one new Claude episode ran.
No model or benchmark retry was used to select a better result. Dedicated tools
retain the official oracle/parity and private evidence roles; execution calls
the installed `axrun.cli` entrypoint, not a second runner or caller-built adapter
selection. This is not generic SWE-bench, a suite, or leaderboard eligibility.

- Baseline: merged PR #11, `a984b9b226f8eee4aa0984978d9ad931d2bad13c`.
- Accepted code: `b178e2a3ea023b922370598d6b63708946262e1f`, branch
  `feat/flask-cli-admission`. Subsequent documentation does not change that code.
- Released Axern CLI and local stack: `0.12.0`; public `axern-sdk==0.12.0`
  installed from the locked public PyPI package, with no source/path dependency.
- Node image: `ghcr.io/cofy-x/axern/node-all-in-one@sha256:991ce2e78126625ab99a7eae657ffc894bc9a6ad1e624c726fa22e8572715b26`.
- Existing stack and unrelated containers stayed running. No Forge, Axern,
  Openbench or official benchmark source changed in this task.
- Full logs, rows, patches, per-test maps and artifacts remain caller-private in
  ignored evidence directories; this document contains identities and digests,
  not hidden test bodies, provider bodies, headers, credentials or secret paths.

The [previous acceptance](2026-09-28-swebench-flask-5014-axern-v0.12.0.md) remains
historical dedicated-tool evidence, not this new CLI run.

## Immutable inputs and admission

- Instance: `pallets__flask-5014`.
- Dataset: `SWE-bench/SWE-bench_Verified`, commit
  `78f471bf655a3137b2e8a75af1501690ec009ec3`, converted `enriched-v1` row.
- Official scorer/harness commit: `f7bbbb2ccdf479001d6467c9e34af59e44a840f9`.
- Complete row digest: `36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e`.
- Seed digest: `077cf80a3e58c24d38ab8124db646a70b4f0a5d3ad389685d0f52d1b466835eb`.
- Eval script SHA-256: `a752d2d3520db71513c263dd476e8da457395a447a346f6b5c18782dc0faf034`.
- Locked native oracle receipt SHA-256: `e16e32a970bf18028ca37f186440d1c064203525f909ad034d8a16c59c18856c`.
- Source platform image: `docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4`.
- Imported runtime image: `index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:98b8b97b38b834eb5a9dad6a42a0380278a911afc74c7025b893ea79294a7da3`.
- Claude readonly rootfs: `index.docker.io/library/axrun-claude-code-rootfs@sha256:df44581291434e694b4f9f054be19df394653d0e1fc5c1e893ed754cbe3fb13b`.

Source and runtime are different manifest identities. The public image-import
record is provenance, not a proof of filesystem equality. Admission scans the
actual imported runtime in a separate model-free, deny-all Run. Its exact private
request is removed before scanning; hidden signature inputs never enter the
real-Claude Allocation, prompt, StagePlan, trajectory or CandidateBundle.

| Admission evidence | Value |
| --- | --- |
| Environment | `env-c94fdf7b-cdaf-41e1-a9d1-06dcaff47a43` |
| Run | `run-cb03c82a-8bcb-4a31-acf0-15dcd82b163d` |
| Allocation | `alloc-d80a51f1-9f8f-4db1-bd08-dc36040fa001` |
| Receipt SHA-256 | `6792f6d87e007eca6fc00d78f76a9a0861174991604952a9796c53f92f2569e2` |
| Scanner implementation SHA-256 | `31b062490ec5e4f0f7c5fdd0714f431d081bc94b6338be1e6a76392f08db024e` |
| Import provenance digest | `60b267c2b18acd5c6e9c3488d84724dcfa2a19081df84e5b4a71f08d8e0d7a49` |
| Sealed audit size / SHA-256 | 1,425 bytes / `d762a453fc575e3293cbd9f8fa13e9409799e36caea3b46e85ef684b9da695ef` |

The audit verified `x86_64`, a clean locked HEAD, complete filesystem and all-Git-
object scans, and no reachable locked patch signatures. It counted 77,258
filesystem entries, 59,757 regular files / 3,353,887,390 bytes, and 23,268 Git
objects / 152,379,907 bytes, including unreachable objects. No unscanned extra
repository or incomplete scan was accepted.

The receipt binds source/runtime, platform, raw row/seed, prompt, evaluation and
test selection/patch digests, import record, scanner implementation, public
execution and independently verified sealed bytes. Status is recomputed from
closed scan details, not accepted from a `passed` flag. Missing, corrupt,
old-contract or mismatched evidence fails closed even on resume/report or caller
adapter override. A caller who can rewrite **all** local state can forge that
state; receipt SHA alone is not a signature or trusted provenance. Absence of
these locked signatures is not proof of absence of every unknown secret.

### Retained pre-acceptance failure

At code `3a08626`, the initial audit requested CPU/memory hard limits. The released
stack correctly rejected Run creation with `FAILED_PRECONDITION`,
`capability_unsupported`; no audit Run, benchmark episode or model request was
created. The unresolved submission intent is retained, not resubmitted.

A fixed two-request public-SDK diagnostic used identical image, environment,
deny-all, finite `exit 0` and scheduling requests (`1` CPU / `2Gi` memory):
with hard limits it was rejected; requests-only succeeded as
`run-304669dd-f138-420a-a020-8b753601465b` /
`alloc-1be8ad64-37f7-459a-8851-bec9684a1893`. Axern's documented memory-hard-limit
capability requires deployment conformance. This is not evidence of a platform
defect.

Axrun's trusted scanner now makes explicit scheduling requests, keeps its closed
byte/count limits, and enforces a 600-second in-process deadline. These are **not
cgroup hard limits**. There is no capability-dependent fallback or network/scan
policy relaxation. After that evidence-backed fix, a new audit state produced
the accepted receipt above; the three benchmark controls then ran once each.

## Deterministic normal-CLI parity

Environments (same immutable runtime image, different stage definitions):

- Inference: `env-c94fdf7b-cdaf-41e1-a9d1-06dcaff47a43`.
- Verification: `env-ac3fe9b7-7da1-4cd5-8cf7-5330a4d307f1`.

| Control | Official ↔ Axrun | Verdict / score | Diagnostic |
| --- | --- | --- | --- |
| Gold | Every status/category and all 60 expected tests match; 60 passed, 0 failed | passed / 1.0 | empty |
| Known-bad | Every status/category and all 60 expected tests match; 59 passed, 1 failed | failed / 0.0 | `SWEBENCH_TESTS_FAILED` |
| Empty | Official unscored/no test execution semantics match; no fabricated map or denominator | failed / null | `SWEBENCH_EMPTY_PATCH` |

Each control independently passed completed resume, verify-record and JSON
report. Parity compares full status maps, test category arrays, missing expected
tests, resolution, score, classification, diagnostic and evaluation exit code,
not just a floating score. The model gate additionally locks official oracle
SHAs, the scored 60-test denominator and all deterministic result identities.

| Control / stage | Run | Allocation |
| --- | --- | --- |
| Gold / inference qualification | `run-7d18ddc2-1c26-499f-b328-1556980fd2e8` | `alloc-7276693f-6022-4b0b-9f62-669d25de10f5` |
| Gold / verifier qualification | `run-3d6cea07-a3fb-40ed-9669-6d8e1bae8166` | `alloc-adc299fb-61af-4f66-abe2-a498b3a1d46f` |
| Gold / inference | `run-cb016fbc-b39c-4595-958e-8a1ac7e11237` | `alloc-f125d7b7-2111-4f74-98cd-55f127a033d3` |
| Gold / verifier | `run-32fa2dbc-955f-4394-ab86-709c154ad7a8` | `alloc-39d05a6f-9879-44a7-b7ea-9cddad13c725` |
| Known-bad / inference qualification | `run-60b75e91-eb98-4c45-8b0a-0df2c5b7134a` | `alloc-f965e4d0-2f9c-4ff9-895f-0e13b3d7a14e` |
| Known-bad / verifier qualification | `run-15f03502-7697-4072-8190-c9e8ae290872` | `alloc-41ae0344-0861-4286-9f98-76ed97517098` |
| Known-bad / inference | `run-3079b708-7c73-42ad-9a18-387f77bac562` | `alloc-dab1b06c-6856-4891-87e4-3f86d8d7ecb5` |
| Known-bad / verifier | `run-1685df38-a56e-46a5-a2a6-98bd06acdbcd` | `alloc-71a2fe82-13e7-485a-b53a-547035d355dd` |
| Empty / inference qualification | `run-0b5f1491-95c7-430a-8c5c-1d8996f27746` | `alloc-ef0a0845-3d44-427b-b687-be53a52c5404` |
| Empty / verifier qualification | `run-db572baf-4fc4-4886-ac4d-5042ae5a04bd` | `alloc-ef5098cf-7e2c-4193-b4c7-1937dee7e031` |
| Empty / inference | `run-ae58774d-084a-4bfa-8855-6b7ca57e2a7d` | `alloc-e1435f3c-4467-4c98-8e2e-203b70a0bfe8` |
| Empty / verifier | `run-c8acba68-ffa4-433e-8780-06864a9e7d8a` | `alloc-35ea55b0-c1b3-410c-af55-b1d194a4a863` |

| Control | CandidateBundle digest | VerificationResult digest |
| --- | --- | --- |
| Gold | `04343a54c3917b22708dac218dd702bcf2a397a0254d55750acea80a73dfba5d` | `5744e2865c3793fb552850df85426ecde0656431bbfecf67f789299f18b86f21` |
| Known-bad | `dfd22332a2602c526ab22799601a35882ec7470161ece03e3290a0f19d8f17c5` | `28a65283e566f2e064dce51e4048a8df075f752377d0606422699d9625f9372e` |
| Empty | `92518b375b2372b485c416b1657b49426d68d7abaaf0ae76f347339a928a96e7` | `36ca308f8c5425c39fecdf13cc6e5a78d85d0ceb18c8c4e5381df42056d025ff` |

The complete private `axrun.swebench-flask-axern-parity@2` receipt SHA-256 is
`d9863bfc1120de33cda522cd0284c6a097a07dc3f7ca27e13c95767258797908`.
It includes every deterministic sealed file's size/SHA and report SHA. No static
trajectory is fabricated.

## One new real Claude candidate

Episode: `flask-5014-claude-f2fbda1dbd4843178514e12e3fb3a336`.

- Inference Environment: `env-867a3165-6654-4bba-a7a4-f5239eb03d2b`.
- Verification Environment: `env-55e955f8-6bd0-4393-a871-076e7257111c`.
- Claude `2.1.205`, Node `v22.23.2`, matching amd64 readonly `/__claude_code`
  ImageMount, `/testbed` task workspace, no runtime harness installation.
- Upstream: `https://api.deepseek.com/anthropic`; caller credential variable
  `DEEPSEEK_API_KEY`, checked for presence only before acceptance.
- Main / Haiku / subagent: `deepseek-flash`; Opus / Sonnet:
  `deepseek-flash[1m]`; effort `max`; auto compact `786432`; max turns `40`.
- Inference/verifier deny-all; WebFetch/WebSearch disabled. The Allocation Tunnel
  exposes only the caller-side ModelProxy. Sandbox auth is the fixed
  `ANTHROPIC_AUTH_TOKEN=axrun-local-tunnel`, not the upstream credential.

| Stage | Run | Allocation |
| --- | --- | --- |
| Inference qualification | `run-1c9b505f-fe54-4c2c-a90d-15e28ec4c17c` | `alloc-8d8928b4-d709-49f0-a488-321b17adfc89` |
| Verifier qualification | `run-3bd37546-d7fa-423e-a61f-077159739482` | `alloc-c47b2d7a-cfd3-4a5c-9766-c77fc962231b` |
| Inference | `run-32ed606e-d1d5-48de-bb93-1602448b9b3c` | `alloc-75587ea7-5ad4-47c8-bea0-1f92b6904fb5` |
| Fresh verifier | `run-7978ab17-f8d9-415e-b1df-9d5504741a4e` | `alloc-b74591a1-33b4-412b-9198-28c3338e0711` |

| Independently verified sealed output | Bytes | SHA-256 |
| --- | ---: | --- |
| candidate.patch | 1,493 | `ad0a676a960347d38f4f17348634fcd8b5ad43c3ad38bb0ada387f9e54f6fd7f` |
| trajectory.jsonl | 39,554 | `042cd4405cf0ddab025143bc0ee67cecc2570efca27dbf068599b4561336e067` |
| harness.log | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| usage.json | 146 | `79c494b99ac6c79cebba358349a45ab56f821adcb02480fc13370448a1b5c587` |
| verification.json | 8,752 | `7e1ea2b23759e09bac2cb32936d96962c8dd3ab66c384b1bb31864a659474f05` |
| verifier.log | 19,977 | `c7ad278e2bed53b51ea6c29b414748d93d207939c5433c7e8359362eaf3f5c48` |

- CandidateBundle: `3fa1d3884f6c4f38c584f62e125fc4c47dc4f51cdbcac0f2fbc55baee8e576db`.
- TrajectoryBundle: `059ab816159f7637c3dd7f0c5bfc6de51aa007efd7d4e2b922797d9678604ea1`,
  58 canonical events.
- VerificationResult: `c44389c3d25d6f7f491ba41cd28281e7463619b5dec9a371c4f86884cd693ffc`.
- JSON report SHA-256: `f6ea27761720fe31d29c61ab138beada1273b0b0427aa6751cf787efa41b313e`.
- Final verdict **passed**, score **1.0**, 60 expected / 60 observed / 60 passed /
  0 failed; diagnostic empty. The model was not required to solve the task.

Run creation/persistence, Allocation readiness, ModelProxy, Tunnel connector,
health and model preflight precede inputs-ready. Normal CLI success proves this
mandatory lifecycle and failure-propagating cleanup contract. Safe progress
recorded 14 proxy requests and a final Anthropic POST `/v1/messages?beta=true`,
HTTP 200 / `upstream_response`; no request/response body or sensitive header is
recorded. This is **not** an independent post-hoc TunnelSession query: SDK 0.12.0
does not enumerate sessions by Allocation. The CLI lifecycle's revoke completed
and the caller subprocess exited; neither session identity nor token is durable.

## Integrity, recovery and cleanup

Both static and Claude use the same catalog, runner, qualification and report.
Resume of each completed episode returned the identical result without a new
inference Run. Unit regressions cover caller disconnect after Run persistence,
qualification recovery, interrupted downloads, original-Run-only recovery,
missing/changed sealed metadata, byte/SHA mismatch, partial-start/cleanup failure,
cancel versus late results, and candidate/result/trajectory provenance mismatch.
Active Claude cannot recreate a lost caller Proxy/Tunnel; this restriction is
explicit, not a promise of live model-session recovery.

- Credential scan of the entire new private Claude evidence tree: **0 matches**.
- No real credential or Tunnel token in StagePlan, sandbox env, Run spec,
  trajectory, CandidateBundle or durable episode records.
- All 18 owned workloads (13 deterministic/audit, 4 Claude/qualification and
  1 resource diagnostic) were `RUN_STATUS_SUCCEEDED` with exact Allocation IDs.
- Public SDK dataplane reads for all 18 Allocations were rejected with
  `FAILED_PRECONDITION: allocation is not active`.
- Both static and both Claude Environments were deleted and confirmed absent by
  the public SDK, only after terminal-state checks. Shared stack/images and other
  tasks were not removed. Immutable Run/sealed evidence remains retained.
- If qualification/inference/verifier is active or its status is unknown, the
  tool now retains Environments for original-Run recovery rather than deleting.

Evaluator/assets/transport/sealing/integrity errors remain infrastructure
failures, not score 0. Empty official unscored semantics are separate from scored
candidate test failure. No Axern platform defect was demonstrated, so no Axern
issue was filed for the optional hard-limit rejection.

## Reproduction and quality

Use fresh owned amd64 Environments and new episode IDs, the exact locked assets,
an explicit SDK context, and the [normal CLI commands](../../README.md#locked-flask-cli-vertical).
Do not copy credentials into config or argv. For the reviewed private acceptance
config schema, the registered native profiles execute these product entrypoints:

```bash
uv run python tools/validation/swebench_flask_axern_parity.py --config "$FLASK_PARITY_CONFIG"
# Only after complete parity; caller already has DEEPSEEK_API_KEY securely set:
uv run python tools/validation/swebench_flask_claude_axern.py --config "$FLASK_CLAUDE_CONFIG"
```

The second config references the first receipt's exact digest. Its closed fields
contain non-sensitive paths/IDs/model settings only. Official oracle assets and
test bodies stay private. Completed resume and verify-record need no model key.

All prescribed quality gates passed locally; native CI on accepted `b178e2a`
also passed with **528 tests**, 0 typing errors. `uv build` produced sdist/wheel.

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
git diff --check
```

Changes were committed with sign-off on the local feature branch. No Mac push,
devbox publication, PR, merge, tag or release was performed. Source/runtime full
official environment equivalence and leaderboard eligibility remain unproven;
the scoped scan/parity does not replace those reviews. Terminal-Bench 2.1 remains
unsupported. Axrun #3's tty-clock partial parity is still unverified and #6's
ProgramBench provenance still needs human submission review; their not-planned
closures are not fixes or qualification evidence.

## PR review follow-up and cold-start boundary

The native acceptance above remains evidence for `b178e2a`; its identities and
results were not rewritten or rerun during [PR #12](https://github.com/cofy-x/axrun/pull/12)
preparation. Focused independent review identified additional caller-side
identity and partial-cleanup gaps, addressed in signed follow-up commits:

- `a627e0c`: reject adapter plans outside the resolved Environment before
  execute/recover, reject persisted/bound/result identity drift, and verify the
  actual public SDK Run identity before reading logs or sealed outputs.
- `f696ed2`: retain real Proxy/socket and observer-thread handles after failed
  cleanup so the next close retries the actual resource, not an empty wrapper.
- `ca022ef`: directly close a Proxy socket when its serving thread never
  started; avoid blocking `BaseServer.shutdown` or an invalid join in that case.
- `3700b9d`: reject running/successful Runs without a public Allocation identity,
  preserving unallocated placed/failed/cancelled Run handling.

Regression tests cover the original adapter-override bypass, recovery identity
substitution, the SDK's empty-string Allocation default, real HTTP server
shutdown/socket-close failures, and real observer/Proxy thread join retries.
These fixes do not change benchmark inputs, scoring, timeout, model configuration
or network semantics. Final local quality gates pass with **569 tests**, zero
typing errors, and successful sdist/wheel construction. Publication of this PR's
head uses devbox-x only; it is not a merge, tag or release.

Independent wheel installation and cold-start acceptance remain **pending**.
After merge, install the built wheel in a clean directory outside the source
checkout. Use an explicit public SDK context, fresh owned amd64 Environments,
new admission evidence, a new episode, and a fixed static candidate. Invoke only
the installed formal CLI for admission, resolve, qualify, run, completed resume,
verify-record and report; then confirm terminal Runs/inactive Allocations and
clean up owned Environments. Do not rely on validation tools, historical caller
state, source-checkout imports, or implicit environment configuration. That
separate acceptance requires no model credential and does not add a benchmark,
harness or scheduler.
