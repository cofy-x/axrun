# Axrun

Axrun is a thin, recoverable runner for agent evaluation on [Axern](https://github.com/cofy-x/axern). It keeps agent and benchmark concerns outside the execution platform while using Axern for isolated, allocation-scoped execution.

## Execution model

```text
ResolvedEpisode
  -> inference Environment / Run / Allocation
  -> sealed and digest-verified CandidateBundle
  -> fresh verification Environment / Run / Allocation
  -> sealed VerificationResult
  -> caller-owned durable publication
```

Axrun intentionally does not provide a scheduler, model registry, dataset service, general workflow engine, or second sandbox lifecycle. It persists only public Axern resource identities and caller-owned artifact metadata.

## Initial adapters

- `ClaudeCodeMountAdapter` runs a pinned Claude Code OCI rootfs at `/__claude_code` and exports a canonical Git patch plus structured trajectory and result files.
- `MiniSweAgentAdapter` is a small official mini-swe-agent conformance path proving that the runner is not coupled to Claude Code.
- `SweBenchVerifierAdapter` applies a CandidateBundle in a fresh verifier Allocation and invokes a pinned, image-owned SWE-bench verifier entrypoint.

The Claude adapter follows the proven isolation boundary from `swe-cc-mount`, but Axrun does not copy its Agent Service, Kafka, Akernel, generation, proxy-ledger, or reward lifecycle.

## Current SDK requirement

Axrun depends only on the released `axern-sdk`. Claude rootfs mounts and secret projections require the SDK's public `create_run()` surface to accept `image_mounts`, `secret_env`, and `secret_files`. Axrun checks this capability explicitly and fails before creating a Run when the installed SDK does not expose it; it never imports internal generated protobuf modules as a workaround.

## Development

```bash
uv sync --all-groups
uv run ruff check .
uv run pyright
uv run pytest
```

The initial test suite uses an in-memory execution backend and does not require an Axern deployment or model credential. Live acceptance will be added against a released SDK and a dedicated Axern environment after the public mount and Secret parameters are available.

## Security boundary

- Inference receives only the task input and a short-lived model credential.
- Verification receives only the immutable CandidateBundle and trusted verifier configuration.
- Verification has no Claude mount, model credential, inference tunnel, or inference filesystem.
- Candidate and result files are accepted only after Axern sealed-output digest verification.
- Infrastructure failure is distinct from a valid unresolved benchmark result.

## License

Apache-2.0.
