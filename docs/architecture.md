# Architecture

Axrun is caller-side orchestration. Axern remains the sole owner of Environment, Run, Allocation, node binding, execution leases, runtime identity, process transport, output sealing and cleanup.

## Document map

This document defines system ownership, lifecycle, isolation, and security invariants. See the
[benchmark and harness extension model](design/benchmark-extension-model.md) for how new adapters
compose without adding benchmark-specific runner branches, and the
[CandidateBundle contract](contracts/candidate-bundle.md) for the normative inference-to-verifier
artifact boundary.

## Fact ownership

| Fact | Owner | Durable location |
| --- | --- | --- |
| Canonical seed, task, harness, candidate and verifier selection | Axrun resolver/caller | immutable `spec.json` |
| Task image and mount qualification evidence | Axrun + Axern Run | content-verified qualification record |
| Task semantics and adapter-owned configuration | Axrun dataset adapter | immutable `spec.json` |
| Task repository, tools and optional base commit | task OCI image | Axern Environment rootfs |
| Run specification, lifecycle and terminal exit | Axern | Run |
| Concrete sandbox identity | Axern | Allocation |
| Inference workspace | Axern runtime | allocation-local filesystem |
| Accepted typed candidate artifacts | Axrun | content-verified CandidateBundle |
| Canonical trajectory and usage | Axrun | content-verified TrajectoryBundle |
| Benchmark grading semantics | verifier image | verifier command |
| Accepted verdict and score | Axrun | content-addressed VerificationResult |
| Optional seed build request and receipt | Axrun caller | local preparation record, outside episode state |
| Build execution and immutable image result | Kova | public Service API build identity and results |

The execution record stores only the specification digest, public Run/Allocation references,
phase, qualification evidence, CandidateBundle and TrajectoryBundle manifest references/digests, result reference, and
diagnosis. It never embeds trajectory events. Allocation status is queried from Axern and is never
copied into a second local state machine.

## State machine

```text
new -> inference_running -> candidate_ready -> verification_running -> completed
                         \                              \
                          +-> failed                     +-> failed
running/candidate_ready -> cancelled
```

The Run ID is persisted from the backend's binding callback before further data operations. A crash in a running phase is recovered by querying that Run, downloading sealed outputs again, and committing the next boundary. A crash after CandidateBundle publication but before the record update reuses the already verified bundle for the same episode, task, Run and harness. Verification always has a different Run ID.

The file lock protects short local transitions. It is not held while waiting for a remote Run. Cancellation serializes its bounded Axern control call with terminal publication so a late stage result cannot overwrite the accepted local cancellation.

Qualification is a precondition on `new`, not another inference phase. The static catalog composes task, harness, candidate, and verifier requirements into separate bounded inference and verification targets. Each target binds the exact Environment, OCI digest, platform, working directory, public Run/Allocation, sealed evidence digest, and checks. Git requirements apply only to Git tasks; no-Git greenfield tasks require an empty working directory. Claude mount checks apply only to inference, the archive finalizer is checked only where candidate capture occurs, and verifier prerequisites are checked in the verification Environment. Qualification is deny-all, model-free, credential-free, and reusable only for the identical episode contract.

## Output and isolation boundary

Inference declares an adapter-specific bounded output set. Candidate production is a separate
adapter contract: `CandidateCapturePlan` contributes bounded setup, packaged inputs, a post-agent finalizer, and declared outputs to the harness plan. The harness invokes that contract without inspecting CandidateSpec or knowing Git/archive semantics; the CandidateAdapter then interprets independently verified sealed outputs.
Each CandidateBundle records candidate identity/version, and each file has a unique semantic role;
verifiers select roles rather than guessing filenames. `git-patch@1` owns clean-base validation and canonical patch export. `workspace-archive@1` owns deterministic whole-workspace capture and publishes role `workspace`. Claude composes with either candidate adapter and separately declares canonical trajectory, harness log, and usage outputs.
Claude's native stream-json is temporary Allocation state and is normalized before sealing. Axrun
accepts declared files only through Axern's sealed-output API and independently rechecks downloaded
length and SHA-256.

Candidate and trajectory publication are distinct. CandidateBundle contains only files needed to
grade the candidate. TrajectoryBundle contains strict `axrun.trajectory@1` JSONL and usage, copies
them into a temporary directory, validates every event and relationship, fsyncs files and manifest,
and atomically publishes by canonical digest. Static inference produces no fake empty trajectory.

Verification gets a fresh Run/Allocation rooted in the explicit immutable verification
EnvironmentBinding and receives only the CandidateBundle payload plus verifier-owned inputs and the
Axrun-owned verifier entrypoint. The verification binding may intentionally differ from inference.
It gets no inference filesystem, process, Secret projection, TunnelSession or runtime identity. Its
default network policy is deny-all. The verifier output must name the exact CandidateBundle digest
before Axrun publishes the result.

The archive v1 format is an uncompressed deterministic PAX tar with stable path order, uid/gid zero, empty owner names, mtime zero, and preserved ordinary permission bits. Creation and extraction reject symlinks and special files, absolute/non-canonical/traversing/duplicate paths, more than 10,000 entries, paths over 240 characters, archives over 64 MiB, and extracted payloads over 512 MiB. Output must live outside the archive root. Fresh verification manually extracts only validated files and directories and rejects pre-existing symlink traversal.

## Trajectory boundary

`axrun.trajectory@1` is harness- and provider-neutral. Every JSONL line has a closed top-level
shape, continuous sequence, deterministic event ID, closed kind and actor, optional UTC timestamp,
opaque model ID, explicit turn/earlier-parent relationship, and kind-specific validated data. V1
supports session start, context, user/assistant messages, tool calls/results, reasoning metadata,
usage, final result, and error. Unknown versions, fields, kinds, forward parents, duplicate IDs,
broken tool relationships, and size-limit violations fail closed.

Claude Code 2.1.205 has the first concrete adapter. It preserves visible text and tool ordering,
maps the Axrun task prompt to reproducible context, and records exposed runtime identity, model,
tools, permission mode, and whether skills/MCP are enabled. Claude-specific UUIDs and provider
payload fields do not enter the common contract. Hidden system prompts are not inferred from model
traffic. Raw thinking and signatures are discarded; a thinking block becomes only
`reasoning_metadata`. Future harnesses require their own explicit native-to-canonical adapter.

The harness interprets only Claude's explicit `error_max_turns` native result as a completed
agent-budget outcome with a candidate. It still canonicalizes and seals that result before a fresh
verifier judges the patch. Other non-zero Claude exits remain infrastructure failures. The
allowlist is intentionally closed so authentication, protocol, transport, and unknown runtime
errors cannot become benchmark `failed` verdicts.

ModelProxy summaries are a separate failure-diagnostic contract. ModelProxy never contributes
request/response bodies, system prompts, tool payloads, or reasoning to a successful agent
trajectory.

## Dataset boundary

Dataset-native rows never enter the runner or execution backend. An explicitly selected, versioned resolver validates one row once and produces canonical `ResolvedEpisode v1` with a stable seed digest. The contract contains `TaskSpec`, stage-specific `EnvironmentBinding`, `HarnessSpec`, `CandidateSpec`, and `VerifierSpec`. Git commits belong only to Git task configuration; they are not core episode or CandidateBundle fields. Adapter-owned configuration may contain fixed local artifact references needed to create StagePlans, while core contracts remain free of benchmark-specific fields.

Resolvers also materialize harness defaults that affect execution semantics. For Claude Code, one primary model fills any omitted Opus, Sonnet, Haiku, and subagent aliases, and the default turn limit and absolute working directory are made explicit before `spec.json` is written. The reusable harness canonicalizer owns this validation so later dataset resolvers do not duplicate Claude runtime semantics. The harness adapter therefore receives five explicit opaque model IDs and does not reinterpret missing aliases while building a StagePlan.

The repository-owned synthetic resolver demonstrates this boundary without introducing a dataset service. The raw row declares and content-checks the task-image build inputs; the resulting image owns the Git repository, required tools and fixed base commit. Its deterministic inference adapter seals a chosen fixture patch. Its verifier receives only the CandidateBundle and verifier entrypoint in a fresh Allocation rooted in that task image, checks the clean base commit, applies the patch, runs an offline test contract, and returns either a valid passed or valid failed result.

The greenfield resolver proves the orthogonal case: an empty no-Git inference image, a distinct verification image, static or Claude harness, `workspace-archive@1`, and an offline verifier consuming only role `workspace`. Its gold candidate passes, while empty and known-bad workspaces produce valid failed verdicts. The fixture images support amd64 and arm64; benchmark acceptance remains canonical on amd64, while arm64 supports local Axern source-cluster development.

The first ProgramBench-shaped integration is deliberately limited to ProgramBench 1.2.4's own
`testorg__calculator.abc1234` compatibility fixture. Inference qualification proves the workspace
contains exactly one execute-only reference `executable`; verification qualification proves a
different Environment starts empty. The candidate finalizer removes that seed-owned reference and
publishes only the reconstructed project, then the fresh verifier removes any stale executable,
runs `compile.sh` offline, and grades behavior. This proves composition but is not one of the 200
official tasks and is not leaderboard evidence. A real instance still requires fixed official
cleanroom and evaluation images, test-blob revision, and official-evaluator parity.

The official-instance vertical locks `xorg62__tty-clock.f2f847c`, the upstream
1.2.4 commit, its official amd64 cleanroom platform manifest, all six test-branch blob digests, and
the complete expected/ignored test metadata. The benchmark-owned verifier snapshots the whole
post-compile container and
starts every branch from it. `axern-sdk==0.11.3` exposes that boundary as an explicitly requested
successful-Run rootfs result whose content-addressed image backs an ordinary derived Environment.
Fresh Runs from that Environment receive isolated writable layers. Re-uploading only `/workspace`
would still lose candidate build effects outside that path and is not official parity. A bounded
coordinator creates or recovers the compile Run and branch Runs while the adapter alone owns
ProgramBench assets, failure taxonomy and scoring. The public-SDK-only reproducer audits the exact
request/wait contract rather than guessing from method names.

A file-only Terminal-Bench subset may also reuse workspace archives. Tasks that preserve package
or system-file changes across finite setup and test phases may use the rootfs-result
boundary, but mounts, secrets, processes, sockets, kernel state, and services are deliberately not
captured and require benchmark-specific modeling. Openbench is read-only research and parity input
rather than a runtime dependency. Axrun intentionally has no dataset platform, scheduler, general
workflow engine, plugin marketplace, or second real harness.

The first benchmark resolver is intentionally narrower than the contract. It accepts only the
official enriched-v1 row for `django__django-12419`, validates its fixed repository, base commit,
official image name, evaluation type, and Django log parser, and binds the complete native row into
the seed digest. It then materializes a content-addressed prompt and evaluation script and discards
the row. The episode contains neither the gold patch nor a native dataset object. The official
amd64 task image owns `/testbed`; both inference and verification select the immutable platform
manifest digest. Verification uploads only the candidate patch, evaluation script, and Axrun-owned
grader into a fresh deny-all Allocation. Expanding to another instance requires an explicit parser
and offline-image qualification rather than shape-based acceptance.

The task image and harness image have separate ownership. An Environment is created from the task image. Claude inference additionally attaches the versioned Claude Code rootfs read-only at `/__claude_code`; static inference and verification do not. The task image and Claude rootfs each publish amd64 and arm64 variants, and a Run must select matching platform digests. Benchmark and production acceptance are canonical on amd64; arm64 exists for local source-cluster validation and does not change episode semantics. Both Claude variants expose the same mount ABI. This keeps benchmark state in the task image and reusable harness tooling in the mount image.

Axrun-owned control code does not run under the repository's benchmark interpreter. The closed
arm64 Django task image retains Conda Python 3.6 for official tests and separately provides
`/usr/bin/python3` for Tunnel probes and trajectory normalization. Axrun control launchers prefer
that system path, preventing task-level `PATH` activation from changing the control runtime, and
fall back to the task-image `python3` only for qualified Python base images such as the synthetic
fixture.

## SDK boundary

### Optional preparation boundary

Kova-backed Environment preparation is a separate caller-side state machine, not an episode phase. A strict `SeedBuildSpec` and stable idempotency key are atomically persisted before the first Kova mutation. Axrun then uses only released public clients to obtain one immutable OCI result and create or exactly reuse one Axern Environment. A ready `EnvironmentPreparationReceipt` materializes the existing `EnvironmentBinding`; no preparation-specific field is added to `ResolvedEpisode`.

Build and Environment waits happen without a long-held local lock. An uncertain build submission can only replay the identical request with its persisted idempotency key. An uncertain Environment create first recovers through public label-filtered list/get calls: zero matches permits create, one exact image/digest/namespace/platform match permits reuse, and any mismatch or multiple match fails closed. Endpoint, token, context, registry credential, response body, and remote runtime identity are not durable preparation facts.

Preparation remains intentionally narrow: Kova, OCI, one logical target, and `linux/amd64`. It is not a workflow engine, scheduler, dataset service, snapshot model, or implicit image cache. Source packaging and push remain caller/Forge responsibilities. CandidateBundle remains the only inference-to-verification bridge.

`AxernBackend` imports only the released `axern_sdk` package and uses public `create_run`, `watch_run`, `allocation`, File/Archive upload, `read_run_output`, `wait_run`, cancel, sealed manifest and sealed download operations. Inputs never include Node or runtime targets. Output capture is capped at 16 MiB per stdout/stderr stream; declared outputs remain the durable result path.

Axrun reuses one SDK client per CLI invocation. Connection loss after a Run ID is persisted is intentionally recoverable rather than hidden by creating a replacement Run.

## Credential and pre-start boundary

Episode schemas and StagePlans contain no provider credential or Tunnel token fields. Live inference uses one caller-side, loopback-only `ModelProxy` per inference stage, exposed through an allocation-scoped, finite-lived Axern Tunnel, so the sandbox receives only its fixed local endpoint and non-secret auth sentinel. Proxy transport is separate from protocol adapters; the current Claude Code path selects the Anthropic-compatible adapter. That adapter has a closed messages/count-tokens path and `beta=true` query allowlist, strips sandbox credentials, and records only bounded request metadata with stable local-rejection versus upstream-response reason codes. This capability is a runtime lifecycle object and is never serialized.

The backend persists the Run ID, waits for the unique Allocation, persists that Allocation ID, starts the proxy and connector, and performs Allocation-originated `/healthz` and protocol-owned model preflights before writing the input-ready marker. Setup failure cancels the unreleased Run. Normal completion and all post-release exits revoke the Tunnel and stop the proxy without treating Tunnel closure itself as Run cancellation. The short-lived connector token is never persisted, so a caller restart cannot silently reconstruct live model access or create a replacement inference Run; recovery must inspect the original Run and require an explicit operator decision if it is still live.

Model failures use a deliberately narrow diagnostic path rather than a telemetry subsystem. The proxy distinguishes `proxy_protocol_rejected`, `proxy_upstream_timeout`, `proxy_upstream_error`, and `upstream_response`; the lifecycle distinguishes `tunnel_health_failed` and `tunnel_model_preflight_failed`. Connect and response time limits are explicit caller-side ModelProxy bounds. A failed Axrun record may retain only method, protocol, allowed path/query, status, byte counts, latency, opaque model ID, numeric usage summary, and stable reason code. Headers, bodies, credentials, and Tunnel tokens are rejected by the durable diagnostic allowlist. Successful request summaries remain process-local.

## Runtime progress boundary

Claude's Allocation-local supervisor is the only component that reads native `stream-json`
stdout. It feeds a stateful normalizer one complete JSON line at a time, appends validated
canonical events to the declared trajectory file, atomically refreshes derived usage, and writes a
small heartbeat at `/run/axrun/progress.json`. The native stream is an undeclared temporary file.
Batch and online normalization share the same state machine, so final sealed trajectory semantics
do not depend on observation.

After model preflight, a caller-side `StageProgressObserver` polls that file through the public
Axern SDK and combines it with the in-memory `ModelProxy` snapshot. It persists only the closed,
bounded `axrun.progress@1` schema and updates `EpisodeRecord` with its canonical path and monotonic
revision. The schema contains identities, counters, safe event/tool labels, heartbeat age, request
metadata, numeric usage, and a stable state reason. It cannot contain prompts, messages, tool
arguments or results, thinking, signatures, headers, bodies, credentials, or Tunnel tokens.

Progress is a non-authoritative operational view. It never enters sealed output, CandidateBundle,
TrajectoryBundle, or verification. Run completion stops the observer before Tunnel cleanup;
cleanup is idempotent. Invalid observed progress terminalizes the episode as an explicit
infrastructure failure. Successful publication still requires sealed-output length and SHA-256
verification before any immutable bundle is created.

`status` and `inspect` provide the safe snapshot without controlling the Run. `wait` and `resume`
reconcile only the persisted Run identity; an expired caller wait does not imply cancellation.
`cancel` is the sole explicit operator path that requests cancellation. Completed acceptance can
be reconstructed by `verify-record`, which rechecks qualification evidence, bundle files and
manifests, execution provenance, fresh verification identity, and VerificationResult linkage;
`report` serializes only that verified summary.
