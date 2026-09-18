# Architecture

Axrun is caller-side orchestration. Axern remains the sole owner of Environment, Run, Allocation, node binding, execution leases, runtime identity, process transport, output sealing and cleanup.

## Fact ownership

| Fact | Owner | Durable location |
| --- | --- | --- |
| Canonical seed, harness and verifier selection | Axrun resolver/caller | immutable `spec.json` |
| Task repository, tools and base commit | task OCI image | Axern Environment rootfs |
| Run specification, lifecycle and terminal exit | Axern | Run |
| Concrete sandbox identity | Axern | Allocation |
| Inference workspace | Axern runtime | allocation-local filesystem |
| Accepted patch, trajectory and log | Axrun | content-verified CandidateBundle |
| Benchmark grading semantics | verifier image | verifier command |
| Accepted verdict and score | Axrun | content-addressed VerificationResult |

The execution record stores only the specification digest, public Run/Allocation references, phase, artifact references and diagnosis. Allocation status is queried from Axern and is never copied into a second local state machine.

## State machine

```text
new -> inference_running -> candidate_ready -> verification_running -> completed
                         \                              \
                          +-> failed                     +-> failed
running/candidate_ready -> cancelled
```

The Run ID is persisted from the backend's binding callback before further data operations. A crash in a running phase is recovered by querying that Run, downloading sealed outputs again, and committing the next boundary. A crash after CandidateBundle publication but before the record update reuses the already verified bundle for the same episode, task, Run and harness. Verification always has a different Run ID.

The file lock protects short local transitions. It is not held while waiting for a remote Run. Cancellation serializes its bounded Axern control call with terminal publication so a late stage result cannot overwrite the accepted local cancellation.

## Output and isolation boundary

Inference declares an adapter-specific bounded output set. Code-task adapters include a candidate patch; live Claude additionally declares trajectory, harness log, and usage outputs. Axrun accepts files only through Axern's sealed-output API and independently rechecks the downloaded byte length and SHA-256. It copies the accepted bytes into a temporary CandidateBundle directory, fsyncs the manifest, and atomically renames the directory.

Verification gets a fresh Run/Allocation rooted in the same immutable task image contract and receives only the CandidateBundle payload plus the Axrun-owned verifier entrypoint. It gets no inference filesystem, process, Secret projection, TunnelSession or runtime identity. Its default network policy is deny-all. The verifier output must name the exact CandidateBundle digest before Axrun publishes the result.

## Dataset boundary

Dataset-native rows never enter the runner or execution backend. An explicitly selected, versioned resolver validates one row once and produces canonical `ResolvedEpisode v1` with a stable seed digest. Adapter-owned configuration may contain fixed local artifact references needed to create StagePlans, while core contracts remain free of benchmark-specific fields. Static qualification and Claude Code use the same adapter-neutral episode contract.

The repository-owned synthetic resolver demonstrates this boundary without introducing a dataset service. The raw row declares and content-checks the task-image build inputs; the resulting image owns the Git repository, required tools and fixed base commit. Its deterministic inference adapter seals a chosen fixture patch. Its verifier receives only the CandidateBundle and verifier entrypoint in a fresh Allocation rooted in that task image, checks the clean base commit, applies the patch, runs an offline test contract, and returns either a valid passed or valid failed result.

The task image and harness image have separate ownership. An Environment is created from the task image. Claude inference additionally attaches the versioned Claude Code rootfs read-only at `/__claude_code`; static inference and verification do not. The task image and Claude rootfs each publish amd64 and arm64 variants, and a Run must select matching platform digests. Benchmark and production acceptance are canonical on amd64; arm64 exists for local source-cluster validation and does not change episode semantics. Both Claude variants expose the same mount ABI. This keeps benchmark state in the task image and reusable harness tooling in the mount image.

## SDK boundary

`AxernBackend` imports only the released `axern_sdk` package and uses public `create_run`, `watch_run`, `allocation`, File/Archive upload, `read_run_output`, `wait_run`, cancel, sealed manifest and sealed download operations. Inputs never include Node or runtime targets. Output capture is capped at 16 MiB per stdout/stderr stream; declared outputs remain the durable result path.

Axrun reuses one SDK client per CLI invocation. Connection loss after a Run ID is persisted is intentionally recoverable rather than hidden by creating a replacement Run.

## Credential and pre-start boundary

Episode schemas and StagePlans contain no provider credential or Tunnel token fields. Live inference uses one caller-side, loopback-only `ModelProxy` per inference stage, exposed through an allocation-scoped, finite-lived Axern Tunnel, so the sandbox receives only its fixed local endpoint and non-secret auth sentinel. Proxy transport is separate from protocol adapters; the current Claude Code path selects the Anthropic-compatible adapter. That adapter has a closed messages/count-tokens path and `beta=true` query allowlist, strips sandbox credentials, and records only bounded request metadata with stable local-rejection versus upstream-response reason codes. This capability is a runtime lifecycle object and is never serialized.

The backend persists the Run ID, waits for the unique Allocation, persists that Allocation ID, starts the proxy and connector, and performs an Allocation-originated `/healthz` preflight before writing the input-ready marker. Setup failure cancels the unreleased Run. Normal completion and all post-release exits revoke the Tunnel and stop the proxy without treating Tunnel closure itself as Run cancellation. The short-lived connector token is never persisted, so a caller restart cannot silently reconstruct live model access or create a replacement inference Run; recovery must inspect the original Run and require an explicit operator decision if it is still live.
