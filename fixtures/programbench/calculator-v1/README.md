# ProgramBench calculator compatibility fixture

This fixture is a closed Axrun compatibility vertical derived from ProgramBench 1.2.4's own
`testorg__calculator.abc1234` test fixture. It is not one of the 200 official benchmark instances
and must not be reported as a ProgramBench leaderboard result.

It exercises the real ProgramBench-shaped boundaries that matter to Axrun:

- inference starts with one execute-only reference program at `/workspace/executable`;
- the harness runs with deny-all networking and produces a complete project;
- `workspace-archive@1` removes the reference executable before candidate publication;
- a different verification Environment starts empty, extracts the archive, removes any stale
  `executable`, runs `compile.sh` offline, and grades behavior;
- gold passes, while empty and known-bad candidates produce legitimate failed verdicts.

Both Dockerfiles accept only `linux/amd64` and `linux/arm64`. The former remains the canonical
benchmark platform; arm64 exists for local Axern source-cluster development. Expanding this adapter
to a real ProgramBench instance requires a fixed official cleanroom image, test-blob revision, and
official-evaluator parity evidence. Openbench is reference material only and is not a runtime
dependency.
