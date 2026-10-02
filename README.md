# Axrun

Axrun is a thin, recoverable episode runner built on the released [Axern](https://github.com/cofy-x/axern) Python SDK. Axern owns isolated execution; Axrun owns the caller-side sequence:

```text
ResolvedEpisode
  -> stage-specific model-free qualification Runs / Allocations
  -> inference Run / Allocation
  -> candidate finalization in the inference Allocation
  -> immutable TrajectoryBundle + CandidateBundle
  -> fresh verification Run / Allocation
  -> sealed VerificationResult
```

Axrun does not provide a scheduler, sandbox runtime, agent registry, provider marketplace, dataset service, or workflow server. Its durable records contain public Environment, Run and Allocation IDs only—never Node IDs, runtime IDs, leases, credentials or private protocol state.

## Design documents

- [System architecture](docs/architecture.md) defines ownership, lifecycle, isolation, recovery,
  model transport, trajectory, and security invariants.
- [Benchmark and harness extension model](docs/design/benchmark-extension-model.md) defines how
  tasks, harnesses, candidates, verifiers, qualification, and benchmark adapters compose.
- [CandidateBundle contract](docs/contracts/candidate-bundle.md) defines the immutable artifact
  boundary between inference and fresh verification.
- [Environment preparation contract](docs/contracts/environment-preparation.md) defines the
  explicit Kova build-to-Axern Environment boundary used before episode resolution.

## Canonical episode contracts

`ResolvedEpisode v1` selects task, harness, candidate and verifier adapters by explicit identity/version, carries adapter-owned validated configuration, binds each stage to an exact image/platform/working-directory contract, and binds the input to a lowercase SHA-256 `seed_digest`. Git and `base_commit` are task-adapter details rather than core fields. A dataset-native row is parsed exactly once by an explicit resolver; inference and verification consume the resulting canonical episode rather than reparsing the original row.

`ResolvedEpisode v2` adds explicit, closed inference and verification network policies (`deny_all` or `unrestricted`). V1 retains its original implicit deny-all semantics and serialized digest; new benchmark resolvers requiring public egress must emit v2 and materialize both policies. Harness plans cannot override the resolved inference policy, and single-Run verifier plans cannot override the verification policy. `StagePlan` defaults to deny-all and rejects unknown policy values. The released Axern SDK represents unrestricted egress by omitting a Run network policy; this is done only for an explicitly resolved `unrestricted` stage, never as an unrecognized fallback. Qualification Runs remain deny-all. A public sandbox policy does not change the caller-only model credential and Tunnel boundaries.

The versioned [v1](schemas/resolved-episode-v1.schema.json) and [v2](schemas/resolved-episode-v2.schema.json) schemas describe persisted ResolvedEpisode JSON; the [CandidateBundle v1 schema](schemas/candidate-bundle-v1.schema.json) describes its immutable manifest. Contract tests validate these schemas against Axrun's actual serialized artifacts.

Axrun core is not a Git patch runner. `HarnessSpec` selects how an agent is launched and how harness-native logs, usage, and trajectory are collected; `CandidateSpec` independently selects how the result is finalized and published. The curated catalog currently composes `claude-code@2.1.205` or model-free `static-candidate@1` with `git-patch@1` or `workspace-archive@1`. Unknown identity/version pairs fail closed; there are no dynamic entry points or runtime-downloaded adapters.

Axrun includes small Git and no-Git synthetic fixtures for deterministic qualification. They are not a dataset registry or download service. Gold, empty, and known-bad candidates pass through the same sealed-output, immutable CandidateBundle, and fresh verification boundary used by remote execution.

The fixture seed is a repository-owned [task image](fixtures/synthetic/code-task-v1/README.md), not a set of files uploaded into an arbitrary Environment. Its Dockerfile installs Git and Python, creates `/workspace` as a clean repository, and asserts the exact base commit during the image build. Build and import the variant matching the Axern node, then create both selected Axern Environments from the imported digest. Inference and verification may reference the same immutable Environment definition; Axrun still creates an independent Run and Allocation for each stage. The task image and the separate Claude Code rootfs both support amd64 and arm64.

Before inference, `run` performs or reuses bounded inference- and verification-side qualification Runs with deny-all networking and no model credential. Each target binds its exact Environment ID, OCI digest, platform, working directory, public Run/Allocation, sealed evidence digest, and adapter-owned checks. Git tasks check the clean base; greenfield tasks check an empty working directory without requiring Git; archive and verifier runtimes are checked only in the stages that use them; Claude checks its fixed runtime and read-only mount only on inference. Inference and verification images may differ.

Resolve either candidate into canonical episode JSON with:

```bash
uv run axrun resolve-synthetic fixtures/synthetic/code-task-v1/row.json \
  --episode-id synthetic-gold \
  --candidate-file gold.patch \
  --task-image REGISTRY/TASK@sha256:DIGEST \
  --task-platform linux/amd64 \
  --inference-environment ENVIRONMENT_ID \
  --verification-environment ENVIRONMENT_ID \
  --output /tmp/synthetic-gold.json
```

The synthetic verifier does not upload or reconstruct the repository. In its fresh Allocation it verifies the task image's clean base commit, receives only the immutable CandidateBundle patch plus the Axrun-owned verifier entrypoint, applies the patch, runs `unittest` with deny-all networking, and publishes a normal passed or failed `VerificationResult`.

The [greenfield fixture](fixtures/synthetic/greenfield-task-v1/README.md) starts with an empty, no-Git `/workspace`, archives the complete created project deterministically, and verifies it in a distinct verification Environment. Resolve a deterministic candidate with exact image digests:

```bash
uv run axrun resolve-greenfield fixtures/synthetic/greenfield-task-v1/row.json \
  --episode-id greenfield-gold \
  --candidate-variant gold \
  --inference-image REGISTRY/INFERENCE@sha256:DIGEST \
  --verification-image REGISTRY/VERIFICATION@sha256:DIGEST \
  --task-platform linux/amd64 \
  --inference-environment INFERENCE_ENVIRONMENT_ID \
  --verification-environment VERIFICATION_ENVIRONMENT_ID \
  --output /tmp/greenfield-gold.json
```

Axrun retains a single-instance `django__django-12419` development path under
`swebench-verified@1`. It checks the enriched-v1 row shape and materializes the prompt and
offline evaluation script, but it does **not** enforce an actual-runtime image admission or
official per-test parity in the normal CLI. The [arm64 source-Compose run](docs/validation/2026-09-19-swebench-django-12419-arm64-e2e.md)
is development evidence only. The pinned official amd64 image is the **source** for the
[derived clean-base seed](docker/swebench-verified/django__django-12419/README.md), not itself a
qualified clean-base task image; passing its digest to the legacy resolver does not make the
episode canonical.

The [locked asset preparer](tools/validation/swebench_django_assets.py) and
[native amd64 model-free oracle](tools/validation/swebench_django_native_oracle.py) are stage-zero
gates for that one instance. The [native Django stage-zero receipt](docs/validation/2026-10-02-swebench-django-12419-native-stage-zero.md)
records official gold, known-bad, and empty classifications on a derived clean-base amd64 seed;
the prior incomplete attempts remain separate. The same record includes one successful, model-free
admission Run against Axern's actual imported runtime. A separate, closed
`swebench-django-official@1` static-candidate task/verifier and
`resolve-swebench-django-official` CLI route are now implemented against that receipt. They
materialize verifier-only assets in a private directory and keep the expected test name out of
the resolved episode. Normal CLI fresh-verifier gold/known-bad/empty parity remains outstanding;
this does not add real-Claude, generic SWE-bench, or leaderboard support.

### Locked Flask CLI vertical

`pallets__flask-5014` is registered as the closed task/verifier pair
`swebench-flask-official@1`, with `git-patch@1` and either static-candidate or
Claude Code 2.1.205. Registration requires mandatory image admission and qualified
episode state; it does not enable other SWE-bench instances or a suite.

| Status | Flask scope |
| --- | --- |
| Implemented | Locked resolver, runtime image admission, qualification, execution/recovery, sealed outputs, and record/report verification |
| Accepted | Deterministic gold/known-bad/empty oracle parity and a real Claude CLI episode on released Axern v0.12.0; see [CLI admission acceptance](docs/validation/2026-09-28-flask-cli-admission.md). Independent-wheel static-gold and real Claude CLI episodes also passed on released v0.12.1; see the acceptances below. The [earlier dedicated-tool acceptance](docs/validation/2026-09-28-swebench-flask-5014-axern-v0.12.0.md) remains historical evidence |
| Registered | Normal CLI uses the same reviewed catalog and mandatory admission checks, without caller-built adapter selection |
| Not implied | Generic SWE-bench support, suite support, full official environment equivalence, or leaderboard submission eligibility |

The [v0.12.1 independent-wheel static-gold cold start](docs/validation/2026-10-02-flask-wheel-cold-start-v0.12.1.md) completed five fresh Runs, exact 60/60 oracle parity, and verified cleanup on a released local stack. A separate [v0.12.1 real Claude independent-wheel acceptance](docs/validation/2026-10-02-flask-claude-wheel-v0.12.1.md) completed five fresh Runs, 20 caller-side model requests, a fresh verifier, exact 60/60 gold-map parity, and verified cleanup. The earlier [v0.12.0 cold-start failure](docs/validation/2026-09-28-flask-wheel-cold-start.md) remains historical platform evidence; neither v0.12.1 acceptance broadens the registered benchmark scope.

The model-free admission command scans the **actual imported runtime image** in a
separate fresh SDK Run, not a source image assumed to be equivalent. The receipt
binds source and runtime digests separately, platform, complete row/asset digests,
import provenance, scanner implementation, public execution identity, and verified
sealed audit output. Missing, corrupt, mismatched, old-contract or incomplete-scan
evidence fails closed. Locked hidden-test/reference signatures are temporary
audit-only inputs, never inference inputs. Passing proves absence of those locked
signatures within the bounded scan, not absence of every unknown secret.

Receipts and episode state are caller-owned evidence, not signed attestations.
A receipt hash proves integrity, not provenance by itself; the runtime audit and
execution evidence establish the reviewed local path. Axrun does not defend
against a caller who can rewrite all local evidence. Import provenance also does
not prove source/runtime filesystem equality; runtime scanning remains mandatory.

The following flow assumes a locked row, the exact verifier wheelhouse, a public
image-import receipt, and three caller-created amd64 Environments from its
canonical runtime digest: a disposable audit Environment and distinct inference
and verification Environments. Set the named variables to your own paths/IDs;
`TASK_IMAGE` is the receipt's immutable runtime reference, never its source digest
or a mutable tag. Use a new episode ID for each execution.

```bash
uv run axrun --state-dir .axrun/flask-cli --context-file "$AXERN_CONTEXT_FILE" \
  admit-swebench-flask-image "$FLASK_ROW" \
  --environment "$AUDIT_ENVIRONMENT_ID" --task-image "$TASK_IMAGE" \
  --image-import-receipt "$IMAGE_IMPORT_RECEIPT" --output admission.json

uv run axrun resolve-swebench-flask-official "$FLASK_ROW" \
  --episode-id flask-cli-static-new --harness static-candidate \
  --candidate-file "$STATIC_PATCH" --assets-dir .axrun/flask-assets \
  --wheelhouse-dir "$FLASK_WHEELHOUSE" --task-image "$TASK_IMAGE" \
  --image-import-receipt "$IMAGE_IMPORT_RECEIPT" --admission-receipt admission.json \
  --inference-environment "$INFERENCE_ENVIRONMENT_ID" \
  --verification-environment "$VERIFICATION_ENVIRONMENT_ID" --output episode.json

uv run axrun --state-dir .axrun/flask-cli --context-file "$AXERN_CONTEXT_FILE" \
  qualify episode.json
uv run axrun --state-dir .axrun/flask-cli --context-file "$AXERN_CONTEXT_FILE" \
  run episode.json
uv run axrun --state-dir .axrun/flask-cli verify-record flask-cli-static-new
uv run axrun --state-dir .axrun/flask-cli report flask-cli-static-new --format json
```

For Claude, use a fresh episode/Environment pair, select `--harness claude-code`,
omit `--candidate-file`, and add `--claude-mount-image "$CLAUDE_AMD64_ROOTFS"`
and `--model "$MODEL_ID"` to the same resolver. Optional model aliases default to
that opaque model ID. Invoke `run` with caller-only
`--model-upstream-url "$MODEL_UPSTREAM_URL" --model-credential-env MODEL_API_KEY`,
with `MODEL_API_KEY` already set securely in the caller environment; do not put
its value in argv, the episode, or sandbox configuration. Flask remains deny-all
and requires both WebFetch and WebSearch disabled.

After a caller interruption, `resume flask-cli-static-new` with the same
`--state-dir` and Axern context queries the original Run; it does not create a
replacement inference. Running Claude cannot recreate its lost Proxy/Tunnel.
`resume`, `verify-record`, and `report` recheck mandatory evidence; `cancel` may
still cancel the original Run when evidence is damaged. These Environments remain
caller-owned: inspect Run terminal state and use the public SDK to clean them up
after collecting evidence. The CLI does not implicitly delete them.

## Supported harness paths

The Claude Code harness fixes the mount ABI at `/__claude_code/usr/local/bin/claude`, requires a digest-pinned rootfs image, and emits canonical `trajectory.jsonl`, `harness.log`, and `usage.json` plus the outputs declared by the selected CandidateAdapter. It contains no Git base, diff, patch, or workspace-archive implementation. The candidate finalizer runs after the agent in the same inference Allocation; finalization failure is infrastructure failure, including after an agent budget terminal state. Claude's native stream-json remains Allocation-local and its adapter maps it into `axrun.trajectory@1` before sealing.

```bash
uv run axrun resolve-synthetic fixtures/synthetic/code-task-v1/row.json \
  --episode-id synthetic-claude \
  --harness claude-code \
  --claude-mount-image REGISTRY/claude-code@sha256:DIGEST \
  --model MODEL_ID \
  --claude-default-opus-model OPUS_MODEL_ID \
  --claude-default-sonnet-model SONNET_MODEL_ID \
  --claude-default-haiku-model HAIKU_MODEL_ID \
  --claude-subagent-model SUBAGENT_MODEL_ID \
  --claude-effort-level max \
  --claude-auto-compact-window TOKEN_COUNT \
  --inference-environment ENVIRONMENT_ID \
  --verification-environment ENVIRONMENT_ID \
  --output /tmp/synthetic-claude.json

MODEL_API_KEY=... uv run axrun \
  --model-upstream-url https://api.anthropic.com \
  --model-credential-env MODEL_API_KEY \
  --context-file ~/.config/axern/config.json run /tmp/synthetic-claude.json
```

Model IDs are opaque strings. The primary model and four Claude model-selection aliases are recorded explicitly so internal model selection cannot silently change providers or tiers. When an alias is omitted, the resolver materializes the primary model into that field in canonical `spec.json`; StagePlan construction requires and consumes those resolved values without applying another hidden default. Effort and auto-compact settings are optional, validated runtime configuration.

The credential is read only from the selected caller environment variable when the per-stage `ModelProxy` is constructed. It is never copied into the episode or StagePlan. A fixed non-secret `ANTHROPIC_AUTH_TOKEN` sentinel satisfies Claude Code's client-side configuration and is stripped by the Anthropic protocol adapter before the proxy injects the real upstream credential as `x-api-key`.

Claude runs offline with `WebFetch` and `WebSearch` explicitly disabled by default through Claude
Code's `--disallowedTools` contract. `--claude-disallowed-tools` records a deterministic explicit
replacement; passing the option with no values deliberately removes the default tool restriction.
This tool policy is separate from Axern's deny-all network policy, which remains the sandbox
enforcement boundary. Locked Flask admission rejects configurations that remove
either WebFetch or WebSearch from the disallowed set.

Canonical trajectories and candidates have separate ownership. `CandidateBundle v1` records
the candidate adapter identity/version and contains only verifier-required files with unique semantic
roles. `git-patch@1` publishes role `patch`; `workspace-archive@1` publishes role `workspace` as `application/x-tar`. Claude can compose with either contract.
`TrajectoryBundle v1` contains canonical `trajectory.jsonl` plus its derived `usage.json`, with an
independent content-addressed manifest. Static candidate episodes have no TrajectoryBundle. The fresh
verifier never receives trajectory, usage, harness logs, ModelProxy summaries, or the inference
workspace. See [the trajectory contract](src/axrun/trajectories/README.md).

`workspace-archive@1` sorts paths, fixes ownership and mtime, preserves ordinary permission bits, and rejects symlinks, devices, FIFOs, sockets, absolute paths, traversal, duplicate entries, oversized paths, excessive entries, archives over 64 MiB, and extracted payloads over 512 MiB. Extraction repeats the closed validation in the fresh verification Allocation. The archive never includes `/inputs`, `/outputs`, `/run/axrun`, model transport state, or harness outputs because its root is the explicit task working directory.

This contract supports the closed ProgramBench single-instance adapters below.
ProgramBench uses a released rootfs result only **inside verification**, from a
fresh compile Run into independent branch Runs through a derived Environment;
it is not an inference-rootfs candidate. Mounts, secrets, processes, sockets,
kernel state and live services are not carried. Terminal-Bench 2.1's official
shared-verifier contract is unsupported by the accepted CandidateBundle → fresh
verifier boundary; a workspace archive or derived Environment must not be presented
as faithful support. Openbench remains read-only research/parity input, not a
runtime dependency. Axrun does not claim general ProgramBench or Terminal-Bench
support, and no second real harness is required for this vertical.

The repository now includes a closed ProgramBench 1.2.4 calculator compatibility fixture. It uses
ProgramBench's own `testorg__calculator.abc1234` fixture identity, not an official benchmark task,
and therefore is not leaderboard evidence. It proves an execute-only seed reference, explicit
seed-owned exclusion from `workspace-archive@1`, different inference/verification Environments,
offline compilation, partial scoring, and deterministic passed/failed verdicts:

```bash
uv run axrun resolve-programbench-compatibility \
  fixtures/programbench/calculator-v1/row.json \
  --episode-id programbench-calculator-gold \
  --candidate-variant gold \
  --inference-image REGISTRY/INFERENCE@sha256:DIGEST \
  --verification-image REGISTRY/VERIFICATION@sha256:DIGEST \
  --task-platform linux/amd64 \
  --inference-environment INFERENCE_ENVIRONMENT_ID \
  --verification-environment VERIFICATION_ENVIRONMENT_ID \
  --output /tmp/programbench-calculator-gold.json
```

The real `xorg62__tty-clock.f2f847c` vertical locks the ProgramBench 1.2.4 instance's six-branch
denominator, ignore decisions, hidden-blob revision/digests, and official `linux/amd64` cleanroom
platform manifest. Its benchmark-owned verifier clears and extracts the candidate, compiles
offline, seals the complete post-compile rootfs, and starts one fresh Run per active branch.
`axern-sdk==0.12.1` exposes the successful-Run rootfs result as an immutable derived Environment;
the linked earlier live validation on v0.11.4 proved fresh Runs preserve sealed state without sharing later mutations.
Aggregation preserves missing tests as `not_run`, ignored tests, branch errors, and ProgramBench's
last-result-wins behavior for duplicate full test names. A workspace archive remains an invalid
substitute for this boundary. See the
historical [stage-zero validation](docs/validation/2026-09-19-programbench-official-tty-clock-stage-zero.md),
the [0.10.0 capability validation](docs/validation/2026-09-20-axern-sdk-0.10.0-derived-environment.md),
and run the public-SDK reproducer with:

```bash
uv run python tools/reproducers/programbench_post_compile_snapshot.py
# exit 0 means the pinned released SDK exposes the request/wait contract
```

The separate locked `lh3__seqtk.94e7070` adapter has deterministic parity and a real Claude
Code 2.1.205 inference-to-verification acceptance on released Axern v0.11.3. See the
[deterministic acceptance](docs/validation/2026-09-23-programbench-seqtk-axern-v0.11.3.md) and
[Claude acceptance](docs/validation/2026-09-23-programbench-seqtk-claude-v0.11.3.md). These are
two closed official-instance verticals, not general ProgramBench, suite scheduling, leaderboard
support, or a generic workflow engine. The tty-clock partial TUI parity question
remains unverified; [#3](https://github.com/cofy-x/axrun/issues/3) was closed as
not planned, not fixed.

ProgramBench scorer parity is separate from upstream submission integrity. The locked seqtk `v2`
row makes the behavioral-observation-only policy explicit; after a completed Claude episode,
`axrun review-programbench-provenance EPISODE_ID` returns body-free risk counts from verified
bundles. Its status is always `human_attestation_required`, including when all counts are zero.
The historical `v1` Claude acceptance remains execution/scoring evidence, not an integrity
attestation or leaderboard submission claim. Closing
[#6](https://github.com/cofy-x/axrun/issues/6) as not planned did not remove the
human review required before an official submission.

An explicit Claude `error_max_turns` result is an agent-budget terminal state, not an execution
transport failure: Axrun seals its patch and trajectory and lets the fresh verifier determine the
business verdict. Every other non-zero Claude terminal subtype remains fail-closed infrastructure
failure.

The task prompt is recorded as canonical context with `axrun_task_prompt` provenance, content, and
SHA-256. A system message is recorded only when the harness explicitly exposes its content. Axrun
does not inspect ModelProxy bodies, reconstruct Claude Code's hidden system prompt, or claim that
prompt is visible. Raw thinking text and signatures are excluded by default; only bounded
reasoning metadata such as occurrence or an explicitly supplied token count is durable.

During live Claude inference, an Axrun-owned supervisor consumes complete native JSONL events
incrementally and writes through the same canonical trajectory state machine used by batch
normalization. The raw stream remains Allocation-local under `/run` and is neither declared nor
downloaded. A separate `axrun.progress@1` snapshot exposes only counts, canonical event kind, a
bounded tool name, byte counts, heartbeat state, and the caller-side ModelProxy's safe request
summary. `status` and `inspect` can read this local snapshot while inference is running. Progress
is diagnostic and non-authoritative: only sealed outputs that pass independent length and SHA-256
verification may produce CandidateBundle and TrajectoryBundle.

The verifier writes `/outputs/verification.json` containing at least:

```json
{"candidate_digest":"<sha256>","resolved":true,"score":1.0}
```

An unresolved result is a valid `failed` verdict. Transport errors, missing outputs, non-zero verifier exit, and digest mismatches are infrastructure failures and never become a score.

## Explicit Environment preparation

Environment preparation is a caller-selected operation before resolution. It is never invoked by `run`, a resolver, or a dataset adapter. V1 accepts one digest-pinned OCI source, asks Kova for one `linux/amd64` OCI target, verifies the returned manifest digest and immutable reference, then creates or exactly reuses an Axern Environment from that original reference. The ready receipt converts to the existing `EnvironmentBinding`; preparation fields do not enter `ResolvedEpisode`.

Install the optional released Kova client, prepare once, and inspect the resulting binding:

```bash
uv sync --extra kova
uv run axrun --state-dir .axrun prepare-kova-environment seed-build.json \
  --output environment-preparation.json
uv run axrun --state-dir .axrun preparation-status PREPARATION_ID
uv run axrun --state-dir .axrun preparation-binding PREPARATION_ID
```

If the caller loses a response after a mutation, resume the persisted identity rather than creating an ad hoc replacement:

```bash
uv run axrun --state-dir .axrun preparation-resume PREPARATION_ID
```

Kova endpoint and token remain in the caller environment used by `kova-client`; Axern connection settings remain in the selected public SDK context. Neither belongs in the preparation spec, record, receipt, episode, or evidence. Source packaging and publishing are outside Axrun.

## Install and CLI

Axrun pins the released `axern-sdk==0.12.1`; it does not use an Axern source checkout or private generated modules. Optional Kova preparation pins the released `kova-client==0.1.0rc9` extra.

```bash
uv sync --all-groups
uv run axrun validate episode.json
uv run axrun --context-file ~/.config/axern/config.json qualify episode.json
uv run axrun --context-file ~/.config/axern/config.json run episode.json
uv run axrun status EPISODE_ID
uv run axrun --context-file ~/.config/axern/config.json wait EPISODE_ID
uv run axrun --context-file ~/.config/axern/config.json resume EPISODE_ID
uv run axrun --context-file ~/.config/axern/config.json cancel EPISODE_ID
uv run axrun inspect EPISODE_ID
uv run axrun verify-record EPISODE_ID
uv run axrun report EPISODE_ID --format markdown --output acceptance.md
uv run axrun export EPISODE_ID ./exported-result
```

## Claude Code rootfs

The repository-owned [Claude Code rootfs build](docker/claude-code-rootfs/README.md) fixes Claude Code `2.1.205`, runtime identity `2.1.205-20260812-234142`, and Node.js `22.23.2`. The same Dockerfile builds amd64 and arm64 variants with the identical read-only mount `/__claude_code` and entry `/__claude_code/usr/local/bin/claude`, including their own platform glibc loader and libraries without a global `LD_LIBRARY_PATH`. It is an image mount layered onto the task-image Environment; it is not the task seed and does not own `/workspace`. The caller must select a digest matching the Environment platform. Production and benchmark acceptance remain amd64; arm64 is for local Axern source-cluster development. A rebuilt or copied image must be imported or published and then selected by its resolved digest; this repository does not claim or embed a registry digest.

Without `--context-file`, remote commands use the explicit Axern SDK environment
configuration. Resolver commands, `status`, `inspect`, `validate`, `verify-record`,
`report`, and `export` are local and do not open an SDK channel. Model-free image
admission and qualification use the SDK without a model credential.

## Credentials and network access

Provider credentials belong to the caller process and are not accepted by `ResolvedEpisode`, projected as sandbox environment variables, or persisted in records and bundles. One short-lived `ModelProxy` is created per inference stage. Its Anthropic protocol adapter exposes only `/v1/messages` and `/v1/messages/count_tokens`, with either no query or exactly `beta=true`, from a bounded loopback listener. Unknown paths, queries, and fragments fail closed. The adapter strips sandbox authentication headers and injects the real credential only on the caller-side upstream hop. Safe in-memory request summaries contain metadata and a stable reason code but no headers or bodies, distinguishing local protocol rejection, upstream timeout/transport failure, and upstream HTTP response. Connect and response bounds are explicit caller options (`--model-connect-timeout-seconds` and `--model-response-timeout-seconds`). `ModelTunnelLifecycle` creates one finite-lived, Allocation-scoped Tunnel after the Run and Allocation identities have been persisted, proves `/healthz`, and performs a protocol-owned model preflight from inside that Allocation before releasing the staged process. Failed stages may persist only the allowlisted safe summary and stable reason code in Axrun's diagnostic record; successful request detail is not added to CandidateBundle, trajectory, or sealed output. The connector token and TunnelSession are held in memory and discarded during unconditional cleanup; neither is a durable episode fact.

## Persistence, recovery, and cancellation

Each episode has an immutable normalized `spec.json` and a small `execution.json`. Qualification, candidate,
trajectory, and result manifests are atomically published and digest checked. The execution record
stores only trajectory manifest path and digest, never the trajectory body. `inspect` exposes those
references, while `export` writes CandidateBundle, optional TrajectoryBundle, and
VerificationResult as separate outputs. Stage Run IDs are stored immediately after creation.
`recover` and `wait` query only those public Run IDs; they never create another Run for an in-flight
stage. A different specification digest cannot reuse an episode ID.

`resume` is the explicit reconciliation command after a caller restart: it queries the persisted
authoritative Run and never synthesizes a replacement. `verify-record` independently rechecks the
complete qualification, bundle, execution-provenance, and result chain. `report` emits that safe
acceptance summary as canonical JSON or Markdown without candidate content, trajectories, secrets,
or Tunnel state.

For a running Claude stage, `execution.json` stores only the canonical local progress path and its
latest revision. The closed progress record excludes prompts, message content, tool arguments and
results, model bodies and headers, credentials, and Tunnel tokens. Malformed progress is an
infrastructure diagnostic and never a benchmark `failed` verdict.

The local lock covers state transitions and the bounded cancel control call, not the lifetime of a remote Run. Consequently another process can inspect or cancel a running episode. Once `completed`, `failed`, or `cancelled` is committed, late stage results cannot replace it.

Axrun cancellation requests cancellation of the active Axern Run; it does not treat a dropped stdout connection or caller wait timeout as workload cancellation. `status` exposes the latest safe progress reason, including model request in flight, tool activity, missing heartbeat, and model idle. The operator can then `resume`/`wait` the same Run or explicitly `cancel` it. Axern retains ownership of Run termination and Allocation cleanup.

## Development and verified boundary

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

The test suite covers the canonical episode and trajectory v1 contracts, static catalog fail-closed resolution, Claude native-event
mapping, raw-thinking exclusion, trajectory size bounds, independent CandidateBundle and
TrajectoryBundle atomic publication, one-pass dataset resolution, task-image workspace contracts,
dual-platform Claude rootfs source contracts, real gold/known-bad patch application in fresh
simulated image workspaces, deterministic greenfield gold/empty/known-bad archive verification, archive security limits, recovery without duplicate Runs, fresh verification identity, bounded
output capture, and deterministic cancellation races. Live Axern image-mount truth paths, a model
endpoint, and benchmark verifier E2E remain explicit deployment acceptance tests rather than
claims made from source tests.

## License

Apache-2.0.
