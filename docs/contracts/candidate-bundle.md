# CandidateBundle contract

`CandidateBundle v1` is Axrun's immutable handoff from inference to fresh
verification. It contains only artifacts required to grade the candidate. It is
independent of harness-native trajectory, usage, logs, model transport, and the
inference filesystem.

This document is normative for the current contract. “Must” and “must not” state
requirements enforced by Axrun or required of new adapters.

## Three distinct contracts

- `CandidateSpec` selects a candidate adapter by explicit identity/version and
  carries adapter-owned validated configuration in `ResolvedEpisode`.
- `CandidateCapturePlan` contributes bounded packaged inputs, optional setup, a
  post-agent finalizer, and declared outputs to an inference StagePlan.
- `CandidateBundle` publishes independently verified sealed outputs under stable
  semantic roles after inference completes.

The HarnessAdapter executes the capture plan but must not interpret CandidateSpec
or implement Git/archive semantics. The CandidateAdapter owns finalization and
bundle construction.

## Manifest

A bundle records:

| Field | Meaning |
| --- | --- |
| `schema_version` | Closed CandidateBundle schema version |
| `episode_id` | Resolved episode identity |
| `task_id` | Canonical task identity |
| `seed_digest` | Lowercase SHA-256 committing the resolver input |
| `inference_run_id` | Public Axern Run that produced the sealed artifacts |
| `harness` / `harness_version` | Harness identity that ran inference |
| `candidate` / `candidate_version` | Candidate contract that produced the artifacts |
| `files` | Non-empty bounded list of accepted candidate files |
| `digest` | SHA-256 of the canonical bundle manifest |

Each file entry records its semantic `role`, original declared output path,
bundle-relative path, media type, byte length, and SHA-256. Roles must be unique.
Verifiers must select files by role, never by guessing a harness filename.

The bundle digest is content-addressed metadata, not an alias for a file digest.
The VerificationResult must cite the exact CandidateBundle digest it graded.

## Publication boundary

Publication follows this order:

1. The candidate finalizer runs after the agent in the same inference Allocation.
2. Axern seals only outputs declared before execution.
3. Axrun downloads each declared candidate output through the public sealed-output
   API.
4. Axrun independently checks the sealed manifest, byte length, and SHA-256.
5. The CandidateAdapter validates its artifact semantics and constructs the
   manifest.
6. Axrun writes files and canonical manifest to a temporary bundle directory,
   fsyncs them, and atomically publishes by digest.
7. A fresh verification Run receives only the accepted candidate payload and
   verifier-owned inputs.

A missing output, digest mismatch, finalizer failure, invalid artifact, or
publication failure is infrastructure failure. It must not be converted into a
benchmark `failed` verdict. A verifier that runs successfully and rejects a valid
candidate artifact produces a legitimate `failed` verdict.

## Isolation and exclusions

CandidateBundle must not contain:

- the inference filesystem outside explicitly accepted candidate artifacts;
- trajectory, usage, harness logs, progress, or ModelProxy summaries;
- credentials, Tunnel tokens, authentication headers, cookies, or model request
  and response bodies;
- Axern Node IDs, runtime IDs, leases, private protocol state, or mutable image
  identities;
- benchmark gold answers unless the benchmark contract explicitly defines them as
  candidate input, which current adapters do not.

Verification must use a different Run and Allocation. It must not reuse an
inference process, mount, Tunnel, credential, runtime identity, or writable
filesystem. Network is deny-all by default.

## `git-patch@1`

`git-patch@1` publishes one file with semantic role `patch`. Repository identity,
the clean base, and `base_commit` are TaskSpec and task-image concerns, not
CandidateBundle core fields.

The adapter owns clean-base validation and canonical patch export. The fresh
verifier obtains a clean repository from its explicit verification
EnvironmentBinding, consumes role `patch`, applies it, and runs the benchmark's
offline verification contract.

## `workspace-archive@1`

`workspace-archive@1` publishes one `application/x-tar` file with semantic role
`workspace`. V1 is an uncompressed deterministic PAX archive:

- paths are emitted in stable sorted order;
- uid and gid are zero, owner names are empty, and mtime is zero;
- ordinary permission bits are preserved;
- the archive is rooted at the explicit task working directory;
- `/inputs`, `/outputs`, `/run/axrun`, and harness outputs are outside that root.

Creation and extraction both fail closed on:

- symbolic links and special files, including devices, FIFOs, and sockets;
- absolute, non-canonical, traversing, or duplicate paths;
- paths longer than 240 characters;
- more than 10,000 entries;
- archives larger than 64 MiB;
- extracted regular-file payload larger than 512 MiB;
- output placed inside the archive root;
- extraction through a pre-existing symlink or outside the destination.

The verifier manually validates and extracts the archive into its fresh
verification Allocation. This contract represents a bounded project tree. It
does not represent installed packages, services, system configuration,
background processes, or VM state.

## Versioning

Candidate identity and version are an explicit pair. Unknown pairs fail closed.
A breaking change to a stable artifact contract requires a new candidate version.
During the current pre-stability phase, incomplete designs may instead be replaced
directly while keeping one canonical v1; Axrun must not retain a misleading legacy
schema solely for compatibility.

Schema and candidate versions are separate: the CandidateBundle schema describes
the common manifest, while `candidate_version` describes an artifact contract.

Potential future types such as a bounded `text-response` or immutable
`environment-snapshot` require concrete benchmark semantics, qualification, and
fresh-verification evidence before entering the catalog. In particular, an
environment snapshot must wait for a public Axern snapshot-to-fresh-Allocation
boundary and must not be emulated with a workspace tar.
