# Axrun

Axrun is a thin, recoverable episode runner built on the released [Axern](https://github.com/cofy-x/axern) Python SDK. Axern owns isolated execution; Axrun owns the caller-side sequence:

```text
ResolvedEpisode
  -> inference Run / Allocation
  -> sealed, digest-verified CandidateBundle
  -> fresh verification Run / Allocation
  -> sealed VerificationResult
```

Axrun does not provide a scheduler, sandbox runtime, agent registry, provider marketplace, dataset service, or workflow server. Its durable records contain public Environment, Run and Allocation IDs only—never Node IDs, runtime IDs, leases, credentials or private protocol state.

## Canonical episode contracts

`ResolvedEpisode v1` selects harness and verifier adapters by explicit identity/version, carries adapter-owned validated configuration, and binds the execution to a lowercase SHA-256 `seed_digest`. A dataset-native row is parsed exactly once by an explicit resolver; inference and verification consume the resulting canonical episode rather than reparsing the original row.

Axrun includes a small `axrun.synthetic.code-task@1` fixture for deterministic qualification. It is not a dataset registry or download service. The gold and known-bad candidates pass through the same immutable CandidateBundle and fresh verification Run boundary used by remote execution.

Resolve either candidate into canonical episode JSON with:

```bash
uv run axrun resolve-synthetic fixtures/synthetic/code-task-v1/row.json \
  --episode-id synthetic-gold \
  --candidate-file gold.patch \
  --inference-environment ENVIRONMENT_ID \
  --verification-environment ENVIRONMENT_ID \
  --output /tmp/synthetic-gold.json
```

The selected Axern environments must provide `/bin/sh`, Git, and Python 3. The synthetic verifier uploads the fixed seed into a fresh Allocation, reconstructs and checks the full base commit, applies only the CandidateBundle patch, runs `unittest` with deny-all networking, and publishes a normal passed or failed `VerificationResult`.

## Supported harness paths

The mini-swe-agent adapter uses the official `mini-swe-agent` 2.4.6 CLI contract and an explicitly selected verifier adapter. A canonical episode selects two pre-created Axern Environments, pins the adapters, and may set explicit CPU, memory and ephemeral-storage requests and limits for each stage. Axrun uploads the prompt, starts the inference Run, consumes bounded retained stdout/stderr, downloads declared outputs, verifies their size and SHA-256, and publishes an immutable CandidateBundle. It then uploads only the candidate patch and fixed verifier seed into a new verification Run with deny-all networking.

The verifier writes `/outputs/verification.json` containing at least:

```json
{"candidate_digest":"<sha256>","resolved":true,"score":1.0}
```

An unresolved result is a valid `failed` verdict. Transport errors, missing outputs, non-zero verifier exit, and digest mismatches are infrastructure failures and never become a score.

## Install and CLI

Axrun pins the released `axern-sdk==0.8.1`; it does not use an Axern source checkout or private generated modules.

```bash
uv sync --all-groups --extra harness
uv run axrun validate episode.json
uv run axrun --context-file ~/.config/axern/config.json run episode.json
uv run axrun status EPISODE_ID
uv run axrun --context-file ~/.config/axern/config.json wait EPISODE_ID
uv run axrun --context-file ~/.config/axern/config.json cancel EPISODE_ID
uv run axrun inspect EPISODE_ID
uv run axrun export EPISODE_ID ./exported-result
```

## Claude Code rootfs

The repository-owned [Claude Code rootfs build](docker/claude-code-rootfs/README.md) fixes Claude Code `2.1.205`, runtime identity `2.1.205-20260812-234142`, Node.js `22.23.2`, and `linux/amd64`. It provides the canonical read-only mount `/__claude_code` and entry `/__claude_code/usr/local/bin/claude`, including its own glibc loader and libraries without a global `LD_LIBRARY_PATH`. A rebuilt or copied image must be published and then selected by its registry-returned digest; this repository does not claim or embed a registry digest.

Without `--context-file`, remote commands use the explicit Axern SDK environment configuration. `status`, `inspect`, `validate`, and `export` are local and do not open an SDK channel.

## Credentials and network access

Provider credentials belong to the caller process and are not accepted by `ResolvedEpisode`, projected as sandbox environment variables, or persisted in records and bundles. `ModelGateway` exposes only the required Anthropic-compatible message paths from a bounded loopback listener and injects the real credential only on the caller-side upstream hop. `AxernTunnelLifecycle` creates one finite-lived, Allocation-scoped Tunnel after the Run and Allocation identities have been persisted, proves `/healthz` from inside that Allocation, and only then releases the staged process. The connector token and TunnelSession are held in memory and discarded during unconditional cleanup; neither is a durable episode fact.

## Persistence, recovery, and cancellation

Each episode has an immutable normalized `spec.json` and a small `execution.json`. Candidate and result manifests are atomically published and digest checked. Stage Run IDs are stored immediately after creation. `recover` and `wait` query only those public Run IDs; they never create another Run for an in-flight stage. A different specification digest cannot reuse an episode ID.

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

The test suite covers the canonical v1 domain contract, one-pass synthetic resolution, real gold/known-bad patch application in fresh test workspaces, atomic publication, integrity checks, recovery without duplicate Runs, fresh verification identity, bounded output capture, and deterministic cancellation races. The optional harness dependency validates that the official mini-swe-agent CLI can be installed and started. A live Axern synthetic run, Linux read-only mount truth path, model endpoint, and benchmark verifier E2E remain explicit deployment acceptance tests rather than claims made from host tests.

## License

Apache-2.0.
