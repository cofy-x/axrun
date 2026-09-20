# Benchmark and harness extension model

This document defines Axrun's long-term extension model. It complements the
[system architecture](../architecture.md) and the normative
[CandidateBundle contract](../contracts/candidate-bundle.md).

Axrun is a thin episode runner, not a benchmark platform or a harness framework.
Its stable center is a small set of explicit, versioned contracts. New benchmarks
and harnesses extend those contracts through repository-owned adapters and a
closed catalog; they do not add benchmark-specific branches to the runner.

## Canonical flow

```text
dataset-native row
  -> explicitly selected DatasetAdapter / resolver (exactly once)
  -> ResolvedEpisode v1
       TaskSpec
       inference + verification EnvironmentBinding
       HarnessSpec
       CandidateSpec
       VerifierSpec
  -> closed catalog lookup and stage-specific qualification
  -> HarnessAdapter + CandidateCapturePlan
  -> fresh inference Run / Allocation
  -> sealed outputs and independent SHA-256 verification
  -> immutable CandidateBundle
  -> fresh verification Run / Allocation
  -> content-addressed VerificationResult
```

The raw dataset row ends at the resolver boundary. The resolver validates it,
commits it to a stable seed digest, and materializes every execution-relevant
default. Neither the runner nor an Axern Run reparses the native row.

## Responsibility boundaries

| Component | Owns | Must not own |
| --- | --- | --- |
| DatasetAdapter / resolver | Native row validation, stable seed digest, canonical episode construction | Remote dataset services, runtime execution, implicit defaults after resolution |
| TaskSpec | Task mode and task-adapter configuration | Harness launch or candidate representation |
| EnvironmentBinding | Exact Environment, OCI digest, platform, and working directory for one stage | Mutable image tags or inferred platform identity |
| HarnessAdapter | Agent launch, harness configuration, native output collection, trajectory normalization | Git diff, workspace archive, or benchmark grading semantics |
| CandidateAdapter | Candidate setup/finalization, declared candidate outputs, CandidateBundle construction | Agent startup, model protocol, or verdict calculation |
| VerifierAdapter | Fresh-stage inputs, offline verifier launch, VerificationResult interpretation | Inference filesystem or harness telemetry |
| Model protocol adapter | Closed protocol surface, credential-header replacement, streaming and bounded safe summaries | Harness semantics, durable credentials, Tunnel lifecycle |
| Model Tunnel lifecycle | Per-inference ModelProxy, Allocation-scoped Tunnel, preflight, release, idempotent cleanup | Provider-specific request semantics or durable tokens |
| EpisodeRunner | Recoverable ordering and publication of contract boundaries | Benchmark-specific branching, scheduling, or sandbox implementation |

`HarnessRuntimeRequirements` is a small, non-sensitive capability declaration,
not a general plugin API. The current terminal mode is deliberately limited to
non-interactive execution. Model protocol, Tunnel, canonical trajectory, and
progress requirements are composed into qualification without carrying secrets.

## Harness and candidate composition

Harness and candidate are orthogonal. A harness launches an agent; a candidate
adapter defines what the agent produced and how that result crosses the
inference/verification boundary.

The current closed catalog supports these compositions:

| Harness | `git-patch@1` | `workspace-archive@1` |
| --- | --- | --- |
| `static-candidate@1` | deterministic synthetic gold/empty/known-bad paths | deterministic greenfield gold/empty/known-bad paths |
| `claude-code@2.1.205` | real Claude Code patch inference | real Claude Code greenfield inference |

`CandidateCapturePlan` is the bridge between the two adapters. It contributes
bounded packaged inputs, optional setup, a post-agent finalizer, and declared
outputs. The harness executes that plan without inspecting candidate-specific
configuration. The CandidateAdapter alone interprets the independently verified
sealed outputs.

Adding a second harness therefore should not copy Git or archive logic. It should
implement its own launch/configuration/output normalization, declare its runtime
requirements, and compose with existing candidate adapters where their semantics
fit.

## Closed catalog, not a plugin system

Axrun selects task, harness, candidate, verifier, and model-protocol adapters by
explicit identity and version from a repository-owned catalog. Unknown pairs fail
closed. There are no Python entry points, runtime-downloaded adapters, arbitrary
imports, or provider marketplaces.

This choice keeps benchmark runs reviewable and reproducible. Extending the
catalog is a code change with tests and qualification evidence. If scale later
requires generated catalog data, generation must still produce a closed,
reviewed artifact rather than runtime discovery.

## Qualification is part of composition

Qualification is stage-specific and model-free. Requirements from the task,
harness, candidate, and verifier are combined separately for inference and
verification, because those stages may use different immutable images and
Environments.

Examples:

- Git cleanliness and base-commit checks apply only to Git tasks.
- An empty workspace check replaces Git requirements for greenfield tasks.
- Claude's read-only rootfs mount is qualified only for inference.
- Candidate finalizer prerequisites are checked only where capture occurs.
- Verifier prerequisites are checked in the verification Environment.

A successful qualification target is reusable only for the identical resolved
episode contract. It never proves a mutable tag, a different platform, or another
stage image.

## Adding a benchmark

A benchmark integration should be the narrowest vertical that proves the
benchmark's real contract:

1. Define a versioned resolver that validates one official row shape and computes
   the seed digest before discarding the raw row.
2. Express task semantics in TaskSpec and bind exact inference and verification
   images, platforms, working directories, and Environments.
3. Reuse an existing CandidateSpec when its artifact faithfully represents the
   benchmark result; add a new candidate type only when the boundary is genuinely
   different.
4. Implement an offline verifier that consumes only semantic CandidateBundle
   roles and benchmark-owned inputs in a fresh deny-all Run.
5. Add the adapters and their requirements to the closed catalog.
6. Prove deterministic gold and valid-failed paths before adding a real model.
7. Prove a real harness path, sealed-output integrity, fresh verification, failure
   classification, credential scanning, and cleanup on the canonical platform.

Do not generalize a single benchmark's row schema into core fields. Do not build a
dataset service, scheduler, workflow engine, or plugin marketplace as a side
effect of adding an adapter.

## Benchmark families

| Family | Candidate boundary | Current status |
| --- | --- | --- |
| SWE-bench-style repository repair | `git-patch@1` | Synthetic vertical and one deliberately closed SWE-bench Verified instance are implemented |
| Greenfield repository creation | `workspace-archive@1` | Static and real Claude Code verticals are implemented and accepted on the local arm64 development path |
| ProgramBench-style file/project output | `workspace-archive@1` with an explicit seed-owned reference exclusion; verifier-internal setup may request a 0.10.0 rootfs result | The 1.2.4 calculator compatibility fixture is implemented; one real tty-clock contract and the public derived-Environment boundary are validated, while official multi-Run evaluator parity remains unimplemented |
| Terminal benchmark, file-only subset | `workspace-archive@1` may be sufficient | Requires explicit task selection and a benchmark adapter; not implemented |
| Terminal benchmark with packages or system-file changes | A successful finite setup Run may publish a 0.10.0 derived Environment | Requires benchmark-specific phase semantics; mounts, secrets, processes, sockets, kernel state, and live services are not captured |
| Text/API answer benchmarks | Future bounded `text-response` candidate | Not implemented; add only with a concrete benchmark and verifier |

Openbench may supply reference tasks, official semantics, and parity evidence, but
it is not an Axrun runtime dependency.

## Mini-SWE-agent policy

Mini-SWE-agent is not an Axrun architecture target and is not required for
benchmark extensibility. Claude Code currently proves the real-harness boundary.
If an official benchmark later requires mini-SWE-agent baseline parity, integrate
it as another HarnessAdapter with a self-contained, versioned, read-only,
multi-platform mount using the same mount ABI principles as the Claude rootfs.
Do not bake it into task images, copy its candidate logic, or make its native data
model canonical.

## Current implementation and deferred work

Implemented now:

- canonical `ResolvedEpisode v1` with task, stage bindings, harness, candidate,
  verifier, and stable seed digest;
- closed adapter catalog and composed stage qualification;
- independent harness and candidate contracts;
- `git-patch@1` and `workspace-archive@1` CandidateBundles;
- a closed ProgramBench 1.2.4 calculator compatibility vertical with deterministic passed/failed paths;
- a fail-closed ProgramBench 1.2.4 official tty-clock asset lock and resolver, plus a released-SDK
  reproducer and live validation for the 0.10.0 post-compile derived-Environment boundary;
- static candidate and Claude Code harness paths;
- canonical trajectory, per-inference-stage ModelProxy/Tunnel lifecycle, fresh offline
  verification, recovery, safe progress, and record verification.

Deliberately deferred:

- executable official-instance/general ProgramBench or Terminal-Bench support;
- benchmark-owned multi-Run compile/branch orchestration and official ProgramBench evaluator parity;
- dynamic plugins, multi-tenant model proxying, a shared harness service, dataset
  hosting, suite scheduling, and leaderboard orchestration;
- a second real harness without a benchmark-driven acceptance case.
