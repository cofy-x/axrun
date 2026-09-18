# Architecture

Axrun is caller-side orchestration. Axern remains the sole owner of Environment, Run, Allocation, node binding, execution leases, runtime identity, process transport, output sealing and cleanup.

## Fact ownership

| Fact | Owner | Durable location |
| --- | --- | --- |
| Episode task, harness and verifier selection | Axrun caller | immutable `spec.json` |
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

Inference declares exactly the candidate patch, trajectory and harness log. Axrun accepts files only through Axern's sealed-output API and independently rechecks the downloaded byte length and SHA-256. It copies the accepted bytes into a temporary CandidateBundle directory, fsyncs the manifest, and atomically renames the directory.

Verification gets a new Environment/Run/Allocation and receives only the candidate patch plus its digest. It gets no inference filesystem, process, Secret projection, TunnelSession or runtime identity. Its default network policy is deny-all. The verifier output must name the exact CandidateBundle digest before Axrun publishes the result.

## SDK boundary

`AxernBackend` imports only the released `axern_sdk` package and uses public `create_run`, `watch_run`, `allocation`, File/Archive upload, `read_run_output`, `wait_run`, cancel, sealed manifest and sealed download operations. Inputs never include Node or runtime targets. Output capture is capped at 16 MiB per stdout/stderr stream; declared outputs remain the durable result path.

Axrun reuses one SDK client per CLI invocation. Connection loss after a Run ID is persisted is intentionally recoverable rather than hidden by creating a replacement Run.

## Credential boundary and current limitation

Episode schemas contain no provider credential fields. The intended live inference boundary is a caller-side model service exposed through an allocation-scoped, finite-lived Axern Tunnel, so the sandbox never receives the provider key. That Tunnel/model-gateway integration and its revocation E2E are not part of the current implementation. Until they exist, only deterministic harness execution—not live model inference—is validated end to end.
