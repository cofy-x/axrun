# Axrun

Axrun is a thin, recoverable episode runner built on the released [Axern](https://github.com/cofy-x/axern) Python SDK. Axern owns isolated execution; Axrun owns the caller-side sequence:

```text
ResolvedEpisode
  -> inference Run / Allocation
  -> sealed canonical trajectory + patch
  -> immutable TrajectoryBundle + CandidateBundle
  -> fresh verification Run / Allocation
  -> sealed VerificationResult
```

Axrun does not provide a scheduler, sandbox runtime, agent registry, provider marketplace, dataset service, or workflow server. Its durable records contain public Environment, Run and Allocation IDs only—never Node IDs, runtime IDs, leases, credentials or private protocol state.

## Canonical episode contracts

`ResolvedEpisode v1` selects harness and verifier adapters by explicit identity/version, carries adapter-owned validated configuration, and binds the execution to a lowercase SHA-256 `seed_digest`. A dataset-native row is parsed exactly once by an explicit resolver; inference and verification consume the resulting canonical episode rather than reparsing the original row.

Axrun includes a small `axrun.synthetic.code-task@1` fixture for deterministic qualification. It is not a dataset registry or download service. The gold and known-bad candidates pass through the same immutable CandidateBundle and fresh verification Run boundary used by remote execution.

The fixture seed is a repository-owned [task image](fixtures/synthetic/code-task-v1/README.md), not a set of files uploaded into an arbitrary Environment. Its Dockerfile installs Git and Python, creates `/workspace` as a clean repository, and asserts the exact base commit during the image build. Build and import the variant matching the Axern node, then create both selected Axern Environments from the imported digest. Inference and verification may reference the same immutable Environment definition; Axrun still creates an independent Run and Allocation for each stage. The task image and the separate Claude Code rootfs both support amd64 and arm64.

Resolve either candidate into canonical episode JSON with:

```bash
uv run axrun resolve-synthetic fixtures/synthetic/code-task-v1/row.json \
  --episode-id synthetic-gold \
  --candidate-file gold.patch \
  --inference-environment ENVIRONMENT_ID \
  --verification-environment ENVIRONMENT_ID \
  --output /tmp/synthetic-gold.json
```

The synthetic verifier does not upload or reconstruct the repository. In its fresh Allocation it verifies the task image's clean base commit, receives only the immutable CandidateBundle patch plus the Axrun-owned verifier entrypoint, applies the patch, runs `unittest` with deny-all networking, and publishes a normal passed or failed `VerificationResult`.

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

The Claude Code harness fixes the mount ABI at `/__claude_code/usr/local/bin/claude`, requires a digest-pinned rootfs image, and emits `candidate.patch`, canonical `trajectory.jsonl`, `harness.log`, and `usage.json` as bounded declared outputs. Claude's native stream-json remains an Allocation-local temporary file. A Claude-specific adapter maps it into the strict provider-neutral `axrun.trajectory@1` contract before sealing. It uses the same synthetic seed and fresh no-network verifier as the static patch qualification path. Resolve a live synthetic episode with:

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

Canonical trajectories and candidate code have separate ownership. `CandidateBundle v1` contains
only verifier-required files; Claude currently contributes only `candidate.patch`.
`TrajectoryBundle v1` contains canonical `trajectory.jsonl` plus its derived `usage.json`, with an
independent content-addressed manifest. Static patch episodes have no TrajectoryBundle. The fresh
verifier never receives trajectory, usage, harness logs, ModelProxy summaries, or the inference
workspace. See [the trajectory contract](src/axrun/trajectories/README.md).

The task prompt is recorded as canonical context with `axrun_task_prompt` provenance, content, and
SHA-256. A system message is recorded only when the harness explicitly exposes its content. Axrun
does not inspect ModelProxy bodies, reconstruct Claude Code's hidden system prompt, or claim that
prompt is visible. Raw thinking text and signatures are excluded by default; only bounded
reasoning metadata such as occurrence or an explicitly supplied token count is durable.

The verifier writes `/outputs/verification.json` containing at least:

```json
{"candidate_digest":"<sha256>","resolved":true,"score":1.0}
```

An unresolved result is a valid `failed` verdict. Transport errors, missing outputs, non-zero verifier exit, and digest mismatches are infrastructure failures and never become a score.

## Install and CLI

Axrun pins the released `axern-sdk==0.9.1`; it does not use an Axern source checkout or private generated modules.

```bash
uv sync --all-groups
uv run axrun validate episode.json
uv run axrun --context-file ~/.config/axern/config.json run episode.json
uv run axrun status EPISODE_ID
uv run axrun --context-file ~/.config/axern/config.json wait EPISODE_ID
uv run axrun --context-file ~/.config/axern/config.json cancel EPISODE_ID
uv run axrun inspect EPISODE_ID
uv run axrun export EPISODE_ID ./exported-result
```

## Claude Code rootfs

The repository-owned [Claude Code rootfs build](docker/claude-code-rootfs/README.md) fixes Claude Code `2.1.205`, runtime identity `2.1.205-20260812-234142`, and Node.js `22.23.2`. The same Dockerfile builds amd64 and arm64 variants with the identical read-only mount `/__claude_code` and entry `/__claude_code/usr/local/bin/claude`, including their own platform glibc loader and libraries without a global `LD_LIBRARY_PATH`. It is an image mount layered onto the task-image Environment; it is not the task seed and does not own `/workspace`. The caller must select a digest matching the Environment platform. Production and benchmark acceptance remain amd64; arm64 is for local Axern source-cluster development. A rebuilt or copied image must be imported or published and then selected by its resolved digest; this repository does not claim or embed a registry digest.

Without `--context-file`, remote commands use the explicit Axern SDK environment configuration. `status`, `inspect`, `validate`, and `export` are local and do not open an SDK channel.

## Credentials and network access

Provider credentials belong to the caller process and are not accepted by `ResolvedEpisode`, projected as sandbox environment variables, or persisted in records and bundles. One short-lived `ModelProxy` is created per inference stage. Its Anthropic protocol adapter exposes only `/v1/messages` and `/v1/messages/count_tokens`, with either no query or exactly `beta=true`, from a bounded loopback listener. Unknown paths, queries, and fragments fail closed. The adapter strips sandbox authentication headers and injects the real credential only on the caller-side upstream hop. Safe in-memory request summaries contain metadata and a stable reason code but no headers or bodies, distinguishing local protocol rejection, upstream transport failure, and upstream HTTP response. `ModelTunnelLifecycle` creates one finite-lived, Allocation-scoped Tunnel after the Run and Allocation identities have been persisted, proves `/healthz`, and performs a protocol-owned model preflight from inside that Allocation before releasing the staged process. Failed stages may persist only the allowlisted safe summary and stable reason code in Axrun's diagnostic record; successful request detail is not added to CandidateBundle, trajectory, or sealed output. The connector token and TunnelSession are held in memory and discarded during unconditional cleanup; neither is a durable episode fact.

## Persistence, recovery, and cancellation

Each episode has an immutable normalized `spec.json` and a small `execution.json`. Candidate,
trajectory, and result manifests are atomically published and digest checked. The execution record
stores only trajectory manifest path and digest, never the trajectory body. `inspect` exposes those
references, while `export` writes CandidateBundle, optional TrajectoryBundle, and
VerificationResult as separate outputs. Stage Run IDs are stored immediately after creation.
`recover` and `wait` query only those public Run IDs; they never create another Run for an in-flight
stage. A different specification digest cannot reuse an episode ID.

The local lock covers state transitions and the bounded cancel control call, not the lifetime of a remote Run. Consequently another process can inspect or cancel a running episode. Once `completed`, `failed`, or `cancelled` is committed, late stage results cannot replace it.

Axrun cancellation requests cancellation of the active Axern Run; it does not treat a dropped stdout connection as workload cancellation. Axern retains ownership of Run termination and Allocation cleanup.

## Development and verified boundary

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

The test suite covers the canonical episode and trajectory v1 contracts, Claude native-event
mapping, raw-thinking exclusion, trajectory size bounds, independent CandidateBundle and
TrajectoryBundle atomic publication, one-pass dataset resolution, task-image workspace contracts,
dual-platform Claude rootfs source contracts, real gold/known-bad patch application in fresh
simulated image workspaces, recovery without duplicate Runs, fresh verification identity, bounded
output capture, and deterministic cancellation races. Live Axern image-mount truth paths, a model
endpoint, and benchmark verifier E2E remain explicit deployment acceptance tests rather than
claims made from source tests.

## License

Apache-2.0.
