# Flask independent-wheel cold start — 2026-09-28

## Outcome and bounded scope

**Independent installation passed; the fresh CLI vertical is not accepted.**
The first runtime-image admission Run failed with Axern's
`CAPABILITY_ENFORCEMENT_LOST`. Axrun failed closed: no admission receipt,
resolved episode, qualification, inference, CandidateBundle or VerificationResult
was published. It must not be reported as a benchmark `failed` verdict or a new
60/60 result.

The acceptance plan was one fixed gold static candidate, three new caller-owned
Environments and one new caller state directory, using only the installed normal
CLI. After the failure, exactly two tiny public-SDK diagnostic controls were
planned and executed. Neither reruns the scanner or benchmark, and neither
substitutes for admission. No acceptance retry selected a better outcome.

The platform evidence is tracked in
[Axern #190](https://github.com/cofy-x/axern/issues/190). No Axrun adapter defect
was demonstrated; no policy fallback, added sleep, relaxed assertion, runtime
source change or benchmark workaround was introduced.

## Clean installation

- Consumer code: merged PR #12,
  `7e917204ee2df5907791f0d817ec4d44013a5831`.
- Local follow-up branch: `feat/flask-wheel-cold-start`.
- Native platform: `linux/amd64`, Python `3.12.3`.
- Built through the registered native build profile, then copied into a new
  private directory outside all source checkouts.
- Wheel: `axrun-0.1.0.dev0-py3-none-any.whl`, SHA-256
  `6d2f0b9859ad7c141a1be301210fc7ec4a2934da721cd32eed863d34b9457cfc`.
- Installed non-editably into a new virtual environment using
  `uv pip install --no-cache --index-url https://pypi.org/simple`.
- Public SDK: `axern-sdk==0.12.0`, no `direct_url.json`, local path dependency,
  source checkout package or private Proto import.
- Resolved production dependencies: `grpcio==1.84.0`, `protobuf==7.36.2`,
  `PyYAML==6.0.3`, `typing_extensions==4.16.0`. No dev or optional Kova package
  was installed. `uv pip check` passed for all six distributions.

All 79 wheel Python assets were compared byte-for-byte with their installed
files. The wheel contains no `tools/validation`. The console entrypoint is
`axrun.cli:main`, and both Axrun and SDK modules resolve inside the new virtual
environment. The caller runs with `python -I`, no source-checkout `sys.path`, and
a closed subprocess environment containing only PATH, LANG and
PYTHONNOUSERSITE. It supplies no model credential, proxy or implicit Axern/Axrun
environment configuration.

The copied caller context is explicit; its TLS files belong to the existing
caller-owned runtime configuration, not the source checkout. TLS bytes and
secret paths are not included here. Fixed row, import provenance, candidate,
oracle grade and wheelhouse are copied as explicit inputs before execution.
No historical episode, admission, qualification or caller execution state is
reused. The oracle grade is a locked expected-result input, not a new oracle run.

## Released runtime and immutable inputs

- Axern CLI/local stack: released `v0.12.0`.
- Rechecked release tag commit:
  `c6bbc9d12350e1df48acf15d233ca9683b83c308`.
- Node image:
  `ghcr.io/cofy-x/axern/node-all-in-one@sha256:991ce2e78126625ab99a7eae657ffc894bc9a6ad1e624c726fa22e8572715b26`.
- Instance: `pallets__flask-5014`, the existing locked official enriched-v1 row.
- Full canonical row SHA-256:
  `36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e`.
- Fixed gold patch SHA-256:
  `087d51d66413bfa35111ac0eca31f1db1636572702cfd967c428049b453f451d`.
- Locked official gold grade SHA-256:
  `bddca4fbdf735900724faee6494a3c3acdeb6e78fcf813e7ef6147dc7659cd51`.
- Source platform manifest:
  `docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4`.
- Actual imported runtime:
  `index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:98b8b97b38b834eb5a9dad6a42a0380278a911afc74c7025b893ea79294a7da3`.
- Offline wheels remain exactly setuptools `70.0.0` and wheel `0.45.1`, with
  the existing locked byte lengths and SHAs.

Read-only host/resource checks confirmed sufficient capacity and the existing
released stack. No shared service or other task container was stopped, replaced
or reset. Forge, Axern, Openbench and official benchmark source were not changed.

## Original admission failure

| Owned role | Environment |
| --- | --- |
| Audit | `env-4f0dcf8c-ddf3-45f6-b189-0d05b379486c` |
| Intended inference; unused | `env-f6519d6d-4344-4ec8-b320-9fefbd9d5dc6` |
| Intended verification; unused | `env-df886d73-db1f-486c-961d-3799be6ee4ec` |

- Run: `run-6a6e71b7-6719-41f4-8bfb-2bc7f01603c0`.
- Allocation: `alloc-aeaa03c7-ccc6-4765-8e4c-19c1eb584fbf`.
- Terminal: `RUN_STATUS_FAILED`, exit code `0`.
- Diagnostic: `WORKLOAD_DIAGNOSTIC_CODE_CAPABILITY_ENFORCEMENT_LOST`.
- Public message: `allocation capability enforcement was lost`.
- CLI exit: `1`, safe error `Flask model-free runtime audit failed closed`.
- Sealed audit output was available and independently downloaded/verified at
  1,425 bytes / SHA-256
  `d762a453fc575e3293cbd9f8fa13e9409799e36caea3b46e85ef684b9da695ef`.
  It remains debug evidence only: a failed public Run cannot become accepted
  admission. No receipt or bundle digest exists.

The effective resources are CPU request `1`, memory request `2Gi`, and
platform-default ephemeral request/limit `256Mi`. Axrun did not request
CPU/memory hard limits. Public observations show healthy pre-start bridge and
runsc storage enforcement conditions, not the final lost-condition reason.

The documented node daemon log establishes an ordered startup sequence:
at `12:44:46Z`, `capability_reconcile` initiates fail-stop **before** OCI spec
creation, `runsc create` and stored container metadata. At `12:44:55Z`, container
wait returns exit `0`; the public Run remains infrastructure-failed.

Read-only review of the exact released platform commit suggests admitted,
not-yet-activated intents can enter capability reconciliation before runtime
preparation is complete, without the startup lifecycle fence. This is a source
hypothesis supported by the ordering, not confirmation of the exact failed
condition. The Issue requests deterministic lifecycle-barrier regression tests
and a phase-aware/fenced correction that retains real enforcement. It does not
request longer retries or weaker policies.

## Two fixed diagnostic controls and cleanup

Both controls use the same runtime image and **identical effective resources**
to the failed audit. They write only a small declared JSON output, not benchmark
content. Unrestricted is a diagnostic comparator only; the task/audit policy
was not changed.

Diagnostic Environment: `env-f56100fa-7115-4ab6-868f-2b1df570fd87`.

| Control | Run | Allocation | Terminal |
| --- | --- | --- | --- |
| deny-all | `run-eed737b3-2d0e-49f6-98c7-a4de59a9b2f8` | `alloc-3743dfe7-8d19-4d3b-883d-98389c5c4e86` | succeeded, exit 0 |
| unrestricted | `run-6e380203-ed21-4532-8a2d-8ff66f2c2bc0` | `alloc-cc14c5de-6936-4dad-aa5b-fd06c0c44fe6` | succeeded, exit 0 |

Each sealed control output was downloaded via the public SDK and independently
verified at 12 bytes / SHA-256
`e5f1eb4d806641698a35efe20e098efd20d7d57a9b90ee69079d5bb650920726`.
These are not HTTPS/egress enforcement tests and do not revalidate #181.

All three owned Runs were terminal. Allocation reads returned
`FAILED_PRECONDITION`, confirming inactive dataplanes. All four new owned
Environments were deleted and independently confirmed `NOT_FOUND`. No model
proxy, connector, Tunnel or trajectory was created. No model credential was read
or supplied; this is not a real-Claude credential-scan acceptance.

Original private summary SHA-256:
`10035d41213c9b14e43ed51e08a78b2aa8d7f2425df5e17d08bf9b4e5d692b68`.
Full private input/log/artifact evidence remains retained outside source checkout;
the original failed Run is not reused or rewritten.

## Remaining acceptance and reproduction

The single remaining blocker is the platform startup enforcement failure in
#190. After a reviewed platform correction, create new owned Environments,
new state/admission/assets and a new episode; install a newly identified wheel.
Invoke only the installed CLI, not `uv run` from a checkout or validation tools:

```bash
"$AXRUN_CLI" --state-dir "$NEW_STATE" --context-file "$CALLER_CONTEXT" \
  admit-swebench-flask-image "$LOCKED_ROW" --environment "$NEW_AUDIT_ENV" \
  --task-image "$RUNTIME_DIGEST" --image-import-receipt "$IMPORT_RECEIPT" \
  --output "$NEW_ADMISSION"

"$AXRUN_CLI" resolve-swebench-flask-official "$LOCKED_ROW" \
  --episode-id "$NEW_EPISODE_ID" --harness static-candidate \
  --candidate-file "$FIXED_GOLD_PATCH" --assets-dir "$NEW_ASSETS" \
  --wheelhouse-dir "$LOCKED_WHEELHOUSE" --task-image "$RUNTIME_DIGEST" \
  --image-import-receipt "$IMPORT_RECEIPT" --admission-receipt "$NEW_ADMISSION" \
  --inference-environment "$NEW_INFERENCE_ENV" \
  --verification-environment "$NEW_VERIFICATION_ENV" --output "$NEW_EPISODE"

"$AXRUN_CLI" --state-dir "$NEW_STATE" --context-file "$CALLER_CONTEXT" qualify "$NEW_EPISODE"
"$AXRUN_CLI" --state-dir "$NEW_STATE" --context-file "$CALLER_CONTEXT" run "$NEW_EPISODE"
"$AXRUN_CLI" --state-dir "$NEW_STATE" --context-file "$CALLER_CONTEXT" resume "$NEW_EPISODE_ID"
"$AXRUN_CLI" --state-dir "$NEW_STATE" verify-record "$NEW_EPISODE_ID"
"$AXRUN_CLI" --state-dir "$NEW_STATE" report "$NEW_EPISODE_ID" --format json
```

The outstanding checks are installed-verifier path resolution, two fresh
qualifications, immutable candidate/result publication, complete 60-test map,
completed replay identity stability and precise cleanup for the full five-Run
flow. They are not claimed passed by this record. Completed resume is evidence
replay, not proof of a live-disconnect recovery scenario.

The original main code passed every prescribed quality gate with **569 tests**,
zero typing errors, successful wheel/sdist and `git diff --check`. This follow-up
changes documentation only. No Mac push, devbox publication, PR, merge, tag or
release was performed. No new benchmark/harness/scheduler is added; prior
single-instance acceptance and Terminal-Bench/ProgramBench integrity limits
remain unchanged.
