# Architecture

Axrun is caller-side orchestration. Axern remains the sole owner of Environment, Run, Allocation, node binding, execution leases, runtime identity, process transport, output sealing and cleanup.

## Fact ownership

| Fact | Owner | Durable location |
| --- | --- | --- |
| Canonical seed, harness and verifier selection | Axrun resolver/caller | immutable `spec.json` |
| Task image and mount qualification evidence | Axrun + Axern Run | content-verified qualification record |
| Task repository, tools and base commit | task OCI image | Axern Environment rootfs |
| Run specification, lifecycle and terminal exit | Axern | Run |
| Concrete sandbox identity | Axern | Allocation |
| Inference workspace | Axern runtime | allocation-local filesystem |
| Accepted candidate patch | Axrun | content-verified CandidateBundle |
| Canonical trajectory and usage | Axrun | content-verified TrajectoryBundle |
| Benchmark grading semantics | verifier image | verifier command |
| Accepted verdict and score | Axrun | content-addressed VerificationResult |

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

Qualification is a precondition on `new`, not another inference phase. A bounded, model-free,
deny-all Run confirms that inference and verification Environments resolve to the same immutable
task image, that the workspace has the expected clean Git base, and that a suitable control Python
exists. Claude episodes additionally prove Claude 2.1.205, Node 22.23.2, the canonical mount/entry,
and read-only ImageMount behavior. Its sealed result digest and public Run/Allocation are committed
before inference may bind a Run. Repeating qualification reuses the bound evidence instead of
spending another Run.

## Output and isolation boundary

Inference declares an adapter-specific bounded output set. Code-task adapters include a candidate
patch; live Claude additionally declares canonical trajectory, harness log, and usage outputs.
Claude's native stream-json is temporary Allocation state and is normalized before sealing. Axrun
accepts declared files only through Axern's sealed-output API and independently rechecks downloaded
length and SHA-256.

Candidate and trajectory publication are distinct. CandidateBundle contains only files needed to
grade the candidate. TrajectoryBundle contains strict `axrun.trajectory@1` JSONL and usage, copies
them into a temporary directory, validates every event and relationship, fsyncs files and manifest,
and atomically publishes by canonical digest. Static inference produces no fake empty trajectory.

Verification gets a fresh Run/Allocation rooted in the same immutable task image contract and receives only the CandidateBundle payload plus the Axrun-owned verifier entrypoint. It gets no inference filesystem, process, Secret projection, TunnelSession or runtime identity. Its default network policy is deny-all. The verifier output must name the exact CandidateBundle digest before Axrun publishes the result.

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

Dataset-native rows never enter the runner or execution backend. An explicitly selected, versioned resolver validates one row once and produces canonical `ResolvedEpisode v1` with a stable seed digest. Adapter-owned configuration may contain fixed local artifact references needed to create StagePlans, while core contracts remain free of benchmark-specific fields. Static qualification and Claude Code use the same adapter-neutral episode contract.

Resolvers also materialize harness defaults that affect execution semantics. For Claude Code, one primary model fills any omitted Opus, Sonnet, Haiku, and subagent aliases, and the default turn limit and absolute working directory are made explicit before `spec.json` is written. The reusable harness canonicalizer owns this validation so later dataset resolvers do not duplicate Claude runtime semantics. The harness adapter therefore receives five explicit opaque model IDs and does not reinterpret missing aliases while building a StagePlan.

The repository-owned synthetic resolver demonstrates this boundary without introducing a dataset service. The raw row declares and content-checks the task-image build inputs; the resulting image owns the Git repository, required tools and fixed base commit. Its deterministic inference adapter seals a chosen fixture patch. Its verifier receives only the CandidateBundle and verifier entrypoint in a fresh Allocation rooted in that task image, checks the clean base commit, applies the patch, runs an offline test contract, and returns either a valid passed or valid failed result.

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
