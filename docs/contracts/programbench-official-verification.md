# ProgramBench official single-instance verification

`programbench-official-single@1` is a benchmark-owned verifier for the locked ProgramBench 1.2.4
instance `xorg62__tty-clock.f2f847c`. It is not a generic workflow facility or a claim of complete
ProgramBench support.

## Boundary

The only inference-to-verification input is an immutable `workspace-archive@1` CandidateBundle.
The archive excludes the seed-owned `executable`. Test metadata, hidden branch blobs, the reference
executable, inference processes, trajectory, credentials and runtime identity never enter the
candidate.

Verification uses the locked official `linux/amd64` cleanroom image. A fresh compile Run clears
`/workspace`, safely extracts the archive, removes the exact locked upstream clean-hash set and any
stale `executable`, runs `compile.sh` with deny-all networking, validates the result and stashes its
SHA-256. A successful finite Run requests an Axern rootfs result. The returned ordinary derived
Environment is verifier-internal state and does not change the candidate identity.

Each of the six active test branches runs in a distinct Run and Allocation from the same derived
Environment. Its blob is supplied explicitly after independent length and SHA-256 verification.
No branch depends on another branch's writable layer.

## Durable execution record

The caller persists one canonical execution record before the first remote mutation. It binds the
CandidateBundle digest and verifier-contract digest to the compile Run/Allocation, derived
Environment, executable digest, every branch Run/Allocation and result digest, aggregation state,
and cleanup state. Resume reuses persisted external IDs. A `running` mutation without a persisted
external ID is ambiguous and fails closed instead of creating a duplicate Run.

After the details artifact is durably published, the adapter deletes its derived Environment and
marks cleanup complete. The backend treats an already-absent Environment as success, so a resume
across the delete/record-write boundary is idempotent.

The bounded coordinator knows only how to create, recover, wait for and cancel Runs, and how to
obtain a successful Run's rootfs result. The ProgramBench adapter alone understands compile steps,
branches, assets and scoring.

## Result semantics

The content-addressed ProgramBench details artifact contains test-level results. Ignored tests are
removed, missing expected tests become `not_run`, and branch evaluator errors mark that branch's
expected tests `not_run`. The published 1.2.4 scorer keys results by `branch/name`; if pytest emits
duplicates after a worker restart, the last occurrence wins. Unexpected unique observed tests are
not silently discarded.

Compile and test failures are benchmark outcomes. Run transport failures, rootfs sealing failures,
asset-integrity failures, malformed evaluator output, and incomplete recovery state are
infrastructure failures and cannot be converted into a business `failed` verdict.
