# Canonical trajectories

`axrun.trajectory@1` is Axrun's provider- and harness-neutral, line-delimited event contract.
`schema.py` owns strict event validation, `policy.py` owns redaction and size limits, harness-native
adapters own source interpretation, and `bundle.py` owns immutable publication.

Claude Code's `stream-json` file is temporary inside its inference Allocation. The
`ClaudeCodeTrajectoryAdapter` maps explicit init metadata, visible messages, tools, results, usage,
and completion into canonical events. It also inserts the Axrun-owned task prompt with content
digest. It does not use ModelProxy bodies and does not reconstruct Claude's hidden system prompt.

Thinking blocks become metadata stating that reasoning occurred. Their text and signatures are
never written to canonical JSONL. This default is not configurable in v1. A future raw-reasoning
research artifact would require a separate opt-in contract and is intentionally not anticipated
here.

TrajectoryBundle is not a verifier input. It contains only `trajectory.jsonl`, `usage.json`, and a
content-addressed manifest. CandidateBundle independently contains the code patch. The runner
persists only each bundle's manifest path and digest, and export keeps the two directories separate.

The checked-in `tests/fixtures/claude-code-2.1.205/` native streams and golden canonical files pin
the adapter compatibility boundary to Claude Code 2.1.205. They are artificial and contain no
captured model traffic or credentials. A Claude Code upgrade must deliberately update the adapter,
version, and fixtures; it must not silently change `axrun.trajectory@1` semantics.

Claude's explicit `error_max_turns` result is a bounded agent-budget terminal state: the harness
publishes the patch and canonical trajectory and lets the fresh verifier judge the candidate.
Other non-zero Claude exits remain inference infrastructure failures. This is a closed subtype
allowlist, not a general suppression of agent or provider errors.
