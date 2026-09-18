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

## First supported path

The initial path uses the official `mini-swe-agent` 2.4.6 CLI contract and one image-owned verifier command. A `ResolvedEpisode` selects two pre-created Axern Environments, pins the harness and verifier commands, and may set explicit CPU, memory and ephemeral-storage requests and limits for each stage. Axrun uploads the prompt, starts the inference Run, consumes bounded retained stdout/stderr, downloads declared outputs, verifies their size and SHA-256, and publishes an immutable CandidateBundle. It then uploads only the candidate patch into a new verification Run with deny-all networking.

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

Without `--context-file`, remote commands use the explicit Axern SDK environment configuration. `status`, `inspect`, `validate`, and `export` are local and do not open an SDK channel.

## Credentials and network access

Provider credentials belong to the caller process and are not accepted by `ResolvedEpisode`, projected as sandbox environment variables, or persisted in records and bundles. A future live model path must expose a caller-owned loopback model endpoint through an allocation-scoped Axern Tunnel with bounded TTL. That path is not implemented or claimed by this release. The current deterministic architecture smoke therefore does not validate live model inference or Tunnel revocation.

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

The test suite covers domain contracts, atomic publication, integrity checks, recovery without duplicate Runs, fresh verification identity, bounded output capture, and deterministic cancellation races. The optional harness dependency validates that the official mini-swe-agent CLI can be installed and started. A live Axern + model endpoint + benchmark verifier E2E remains an explicit deployment acceptance test, not a claim made from fake tests.

## License

Apache-2.0.
