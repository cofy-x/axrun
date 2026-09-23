# ProgramBench official single-instance verification

`programbench-official-single@1` is a benchmark-owned verifier for the locked ProgramBench 1.2.4
instance `xorg62__tty-clock.f2f847c`. It is not a generic workflow facility or a claim of complete
ProgramBench support.

## Boundary

The only inference-to-verification input is an immutable `workspace-archive@1` CandidateBundle.
The archive excludes the seed-owned `executable`. Test metadata, hidden branch blobs, the reference
executable, inference processes, trajectory, credentials and runtime identity never enter the
candidate.

Verification uses a separately built, digest-pinned `linux/amd64` evaluator image based on the locked official cleanroom image. The fixture's `Dockerfile.verification` installs all pinned evaluator dependencies and checks the installed versions during construction. The resolver requires `--verification-image` separately from the unchanged inference `--runtime-image`; the base image alone is not a valid evaluator. A fresh compile Run clears
`/workspace`, safely extracts the archive, removes the exact locked upstream clean-hash set and any
stale `executable`, runs `compile.sh` with deny-all networking, validates the result and stashes its
SHA-256. Static dependencies are never installed in a Run. Compile and branch preflight reject a missing or inconsistent evaluator environment. The adapter removes only the exact known online pip commands for each locked branch setup; upstream setup drift fails closed. Pytest arguments, the existing signal-timeout adaptation, rerun policy and scoring remain unchanged. A successful finite Run requests an Axern rootfs result. The returned
ordinary derived Environment is verifier-internal state and does not change the candidate identity.

Each of the six active test branches runs in a distinct Run and Allocation from the same derived
Environment. Its blob is supplied explicitly after independent length and SHA-256 verification.
The official default of 10 container CPUs is materialized as both the Allocation CPU limit and
`PYTEST_XDIST_AUTO_NUM_WORKERS=10`; it is part of the verifier contract digest rather than an
ambient host default. No branch depends on another branch's writable layer.

## Durable execution record

The caller persists one canonical execution record before the first remote mutation. It binds the
CandidateBundle digest and verifier-contract digest to the compile Run/Allocation, derived
Environment, executable digest, every branch Run/Allocation and result digest, aggregation state,
and cleanup state. Resume reuses persisted external IDs. A `running` mutation without a persisted
external ID is ambiguous and fails closed instead of creating a duplicate Run.

After the details artifact is durably published, the adapter deletes its derived Environment and
marks cleanup complete. The backend treats an already-absent Environment as success, so a resume
across the delete/record-write boundary is idempotent. A branch Run that reaches a terminal
infrastructure failure also deletes the derived Environment before surfacing the error. An
ambiguous caller interruption keeps it for explicit resume instead.

The bounded coordinator knows only how to create, recover, wait for and cancel Runs, and how to
obtain a successful Run's rootfs result. The ProgramBench adapter alone understands compile steps,
branches, assets and scoring.

## Result semantics

The content-addressed ProgramBench details artifact contains test-level results. Ignored tests are
removed, missing expected tests become `not_run`, and branch evaluator errors mark that branch's
expected tests `not_run`. The published 1.2.4 scorer keys results by `branch/name`; if pytest emits
duplicates after a worker restart, the last occurrence wins. Unexpected unique observed tests are
not silently discarded.

An evaluator invocation failure, missing/invalid/empty XML or invalid dependency environment produces a sealed body-free `infrastructure_error` diagnostic. The adapter retains that artifact, cleans up the derived Environment and raises `InfrastructureError`; it never publishes a score or automatically reruns a failed verification. Raw hidden-test output is not copied into public diagnostics.

Compile and test failures are benchmark outcomes. Run transport failures, rootfs sealing failures,
asset-integrity failures, malformed evaluator output, and incomplete recovery state are
infrastructure failures and cannot be converted into a business `failed` verdict.
