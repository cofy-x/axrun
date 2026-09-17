# Architecture

Axrun is a caller-side orchestration library. Axern remains the sole owner of Environment, Run, Allocation, node binding, execution leases, runtime identity, process transport, output sealing, and cleanup.

## Facts and ownership

| Fact | Owner | Durable location |
| --- | --- | --- |
| Resolved task, agent choice, verifier choice | Axrun caller | `ResolvedEpisode` |
| Execution specification and terminal result | Axern | Run |
| Concrete execution identity | Axern | Allocation |
| Agent workspace | Axern runtime | Allocation-local filesystem |
| Candidate patch, trajectory, agent result | Axrun caller after Axern sealing | `CandidateBundle` |
| Benchmark grading semantics | Verifier adapter / upstream benchmark | Verifier image and adapter |
| Verification result | Axrun caller after Axern sealing | `VerificationResult` |

Axrun stores public `environment_id`, `run_id`, and `allocation_id` only. Node identity, runtime/container identity, leases, grants, watch cursors, and node-local paths never enter an episode record.

## Stage boundary

Inference and verification are different Axern Runs and Allocations. The runner waits for inference termination, obtains the declared-output manifest, downloads every required output through the SDK, verifies the platform-provided size and SHA-256, copies the accepted files into a self-contained CandidateBundle directory, and only then creates verification.

The verifier is not given an inference filesystem, process, TunnelSession, model credential, Claude runtime mount, or writable shared volume. A verifier image owns the trusted benchmark entrypoint and hidden test material. Infrastructure failure is represented by an exception and diagnostic, never by a fabricated score of zero.

## Recovery

The local `EpisodeStore` uses atomic replacement and fsync. The Run identity is persisted as soon as creation succeeds and the Allocation identity is added once binding is observable. If a client operation becomes ambiguous, the phase remains `inference_running` or `verification_running`; a normal `run()` call refuses to duplicate the stage. `recover()` queries the persisted Run, accepts only a terminal result, re-downloads sealed outputs, and continues from the next committed boundary.

Axrun does not silently retry a failed episode. A policy layer may deliberately create a new episode or attempt, but that identity is outside the execution identity and must not reuse a previous CandidateBundle as if it were newly produced.

## Claude Code mount

The Claude adapter expects a digest-pinned OCI rootfs mounted read-only at `/__claude_code`, with `/__claude_code/usr/local/bin/claude` as the sole entrypoint. The task image owns `/workspace`, Git, language toolchains, and tests. The model credential is an Axern Secret projection and never appears in argv or persisted state.

After the CLI exits, trusted wrapper code exports the complete Git delta using a temporary index. This includes committed, staged, unstaged, deleted, and non-ignored untracked files without changing the agent's real index. Structured stdout, stderr log, patch, and result metadata are separate declared outputs.

## Current release gate

The published Axern SDK exposes the `ImageMount`, `SecretEnvVar`, and `SecretFile` value types, but version 0.8.0 does not yet accept these values in `AxernClient.create_run()`. `AxernBackend` detects the missing public parameters and fails before Run creation. The live Claude path must remain gated until a released SDK exposes those parameters; importing Axern internal protobufs is not an acceptable workaround.
