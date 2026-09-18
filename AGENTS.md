# Axrun Agent Contract

## Product boundary

Axrun is a thin, recoverable episode runner built exclusively on the released Axern SDK. It owns episode orchestration, agent and verifier adapters, CandidateBundle delivery, VerificationResult parsing, and caller-side durable records. It does not implement a sandbox runtime, scheduler, node control plane, model registry, dataset platform, or general workflow engine.

The execution boundary is always:

```text
ResolvedEpisode
  -> inference Run / Allocation
  -> immutable CandidateBundle
  -> fresh verification Run / Allocation
  -> VerificationResult
```

Inference and verification never share a writable filesystem. SSH and Terminal remain diagnostic capabilities. A finite Allocation-scoped Tunnel may expose a caller-owned model endpoint during inference, but the session, token, and connection never become durable episode facts. Axrun stores only public Axern identities (`environment_id`, `run_id`, and `allocation_id`) and must not import Axern internal protobuf packages or depend on an Axern source checkout.

## Design rules

- Python is the first-class implementation language. Keep persisted JSON contracts language-neutral and versioned.
- Agent adapters describe commands, immutable runtime requirements, inputs, and declared outputs. They do not create a second execution lifecycle.
- The CandidateBundle is the only bridge from inference to verification. Never pass an inference workspace, credential, session, or live connection to a verifier.
- Model credentials remain in the caller process. If a sandbox needs model access, expose only a caller-owned loopback TCP endpoint through a finite Allocation-scoped Axern Tunnel. Credentials and Tunnel tokens must not appear in argv, Run metadata, logs, trajectories, manifests, or durable episode records.
- Prefer official upstream agents and verifier semantics. Do not fork an upstream project unless its public interface cannot satisfy a demonstrated lifecycle or security requirement.
- Do not add a plugin marketplace, daemon, queue, database server, or local sandbox backend without a proven consumer requirement.
- Recovery is explicit. Persist a public Run identity before performing further data-plane operations, and never silently rerun an inference stage after its outcome becomes ambiguous.

## Development

- Preserve existing changes and inspect `git status --short --branch` before non-trivial work.
- Use `uv` for environments, locking, linting, typing, and tests.
- Run `uv run ruff check .`, `uv run pyright`, `uv run pytest`, and `git diff --check` for code changes.
- Never commit credentials, local Axern contexts, task inputs, candidate artifacts, or episode state.
