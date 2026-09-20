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

## Canonical episode contracts

`ResolvedEpisode v1` selects task, harness, candidate and verifier adapters by explicit identity/version, carries adapter-owned validated configuration, binds each stage to an exact image/platform/working-directory contract, and binds the input to a lowercase SHA-256 `seed_digest`. Git and `base_commit` are task-adapter details rather than core fields. A dataset-native row is parsed exactly once by an explicit resolver; inference and verification consume the resulting canonical episode rather than reparsing the original row.

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

Axrun also contains one deliberately closed SWE-bench Verified vertical for
`django__django-12419`. `SweBenchVerifiedResolver` accepts exactly the official enriched-v1
row shape, commits the entire row to the seed digest, then discards the native row after
materializing only the prompt and official offline evaluation script. The current adapter rejects
other instances and log parsers; this is one qualified path, not a dataset platform or a claim of
general leaderboard support. Resolve it with the amd64 platform manifest digest, never the mutable
official tag or the multi-platform index digest:

```bash
uv run axrun resolve-swebench-verified /path/to/django__django-12419.json \
  --episode-id swebench-django-12419 \
  --task-image docker.io/swebench/sweb.eval.x86_64.django_1776_django-12419@sha256:6c6b1fec0a323b9225564620cd34f2d39828cef8f32496ad4a6c9ca0f7256768 \
  --assets-dir /tmp/axrun-swebench-assets \
  --claude-mount-image REGISTRY/claude-code@sha256:AMD64_DIGEST \
  --model MODEL_ID \
  --inference-environment AMD64_ENVIRONMENT_ID \
  --verification-environment AMD64_ENVIRONMENT_ID \
  --output /tmp/swebench-django-12419.json
```

The official image owns `/testbed`, its repository, dependencies, and base commit. Claude's
working directory is explicit in the resolved harness configuration. The fresh verifier receives
only the CandidateBundle patch, the content-addressed official evaluation script, and Axrun's
packaged grader; it has deny-all networking and no inference mount, process, Tunnel, or credential.

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
enforcement boundary.

Canonical trajectories and candidates have separate ownership. `CandidateBundle v1` records
the candidate adapter identity/version and contains only verifier-required files with unique semantic
roles. `git-patch@1` publishes role `patch`; `workspace-archive@1` publishes role `workspace` as `application/x-tar`. Claude can compose with either contract.
`TrajectoryBundle v1` contains canonical `trajectory.jsonl` plus its derived `usage.json`, with an
independent content-addressed manifest. Static candidate episodes have no TrajectoryBundle. The fresh
verifier never receives trajectory, usage, harness logs, ModelProxy summaries, or the inference
workspace. See [the trajectory contract](src/axrun/trajectories/README.md).

`workspace-archive@1` sorts paths, fixes ownership and mtime, preserves ordinary permission bits, and rejects symlinks, devices, FIFOs, sockets, absolute paths, traversal, duplicate entries, oversized paths, excessive entries, archives over 64 MiB, and extracted payloads over 512 MiB. Extraction repeats the closed validation in the fresh verification Allocation. The archive never includes `/inputs`, `/outputs`, `/run/axrun`, model transport state, or harness outputs because its root is the explicit task working directory.

This contract is sufficient groundwork for a ProgramBench single-instance adapter and may cover a file-only Terminal-Bench subset. It does not represent services, package installation, system configuration, background processes, or VM state; full Terminal-Bench support still requires a public immutable Allocation snapshot-to-fresh-Allocation capability from Axern. Openbench remains a research and parity input, never an Axrun runtime dependency. Axrun does not claim full ProgramBench or Terminal-Bench support. A mini-SWE-agent readonly mount should be considered only if future official-baseline parity requires it; it is not a prerequisite for using Claude Code.

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

Expanding to a real ProgramBench instance requires a fixed official cleanroom image, test-blob
revision, and parity evidence against the official evaluator; Axrun does not reinterpret observed
tests as an equivalent score.

Stage-zero work now locks the real `xorg62__tty-clock.f2f847c` instance from ProgramBench 1.2.4:
its six-branch denominator, ignore decisions, hidden-blob revision/digests, and official
`linux/amd64` cleanroom platform manifest are content-addressed. The resolver can materialize and
validate this contract, but the closed catalog intentionally refuses to run it until the official
verifier adapter and parity suite exist. ProgramBench's official evaluator commits the complete
candidate-specific post-compile container and starts each test branch from that state.
`axern-sdk==0.10.0` now exposes the required successful-Run rootfs result as an immutable derived
Environment; live validation also proves two fresh Runs preserve the sealed state without sharing
later mutations. A workspace archive remains an invalid substitute for this boundary. See the
historical [stage-zero validation](docs/validation/2026-09-19-programbench-official-tty-clock-stage-zero.md),
the [0.10.0 capability validation](docs/validation/2026-09-20-axern-sdk-0.10.0-derived-environment.md),
and run the public-SDK reproducer with:

```bash
uv run python tools/reproducers/programbench_post_compile_snapshot.py
# exit 0 means the exact 0.10.0 request/wait contract is present
```

No official ProgramBench score, deterministic parity, or Claude acceptance is claimed until the
benchmark-owned multi-Run verifier orchestration reproduces the official evaluator without
weakening branch isolation.

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

## Install and CLI

Axrun pins the released `axern-sdk==0.10.0`; it does not use an Axern source checkout or private generated modules.

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

Without `--context-file`, remote commands use the explicit Axern SDK environment configuration. `status`, `inspect`, `validate`, and `export` are local and do not open an SDK channel.

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
