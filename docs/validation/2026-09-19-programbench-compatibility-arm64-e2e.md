# ProgramBench compatibility fixture arm64 E2E

Date: 2026-09-19

This acceptance used Axrun `13917f2551d8e7a798f7ee2c47ee9c565e731a5a`, Axern
`0294033e870647e0dde5777b298d437c1d4bb5bc`, and released `axern-sdk==0.9.1`
from Axrun's `.venv/site-packages`. Axrun used no Axern source Python package or private Proto.

The selected task is ProgramBench 1.2.4's repository-owned
`testorg__calculator.abc1234` compatibility fixture. It is not one of the 200 official benchmark
instances and this record is not ProgramBench leaderboard evidence.

## Runtime inputs

| Role | Local arm64 image ID | Axern canonical digest | Environment |
| --- | --- | --- | --- |
| inference | `sha256:bae74b07353ebd6cafb0da18b29e0ec620557d68ae38aea68acb567fddfa727e` | `index.docker.io/library/axrun-programbench-calculator-inference@sha256:924b1543eaccdf3ad696e9a3affa02a31f77eee67f4e7f147c471e484a6b4c30` | `env-ab8e1429-3981-458b-b050-a67aca07e712` |
| verification | `sha256:5a4fbc0b6d72087d2b2ef89e26d2d31b3e231925070a024971ab8cbbb0cfc744` | `index.docker.io/library/axrun-programbench-calculator-verification@sha256:c7f9c50639d49db7204ad866b14098721642008b4eb9d51972ff06152ab4c389` | `env-76fa9fee-bdfd-4673-90be-0628f7754afa` |

The same Dockerfiles also built and passed no-network container smoke on `linux/amd64`:
inference `sha256:0d464e73698e2c83677f9f370f23a0ba489fc2e897439929b03cb43b44f1daab`
and verification
`sha256:568cad8223febcddd2102198a2b0a26fa3f7810ae88293c96c57376c93f68349`.
amd64 remains the canonical benchmark platform; this Axern E2E used the local arm64 source cluster.

Inference qualification observed `aarch64`, Python `3.11.16`, and exactly one workspace file:
`executable` with mode `0111`. Verification qualification observed a distinct, empty `/workspace`.
Both stages used immutable canonical image digests.

## Results

All rows used seed digest
`ea2ca93097cf1d52e29d4f2e8ee38667f6a2e21905724d326568952466e5c866`.

| Candidate | Inference Run / Allocation | Verification Run / Allocation | CandidateBundle | VerificationResult | Verdict |
| --- | --- | --- | --- | --- | --- |
| gold | `run-d1da0b02-c3a7-4969-ae94-5daacef9f1d2` / `alloc-f12bb73a-53d1-49c9-8795-6b16472004f0` | `run-62093d32-cc07-4e51-ae38-057896b72a10` / `alloc-821289b3-7c40-4456-9172-f126ba21e90c` | `c9dac23e93bd7a1de71990f963d2202298f44f6218cef18d28d0bc49abab0621` | `5adef3f243566f49c25bd11783fb557e846d1fb5df1c25898d53eb4852d1e8dc` | passed / 1.0 |
| empty | `run-87ddd150-fccb-4baa-a952-a5572eae32f5` / `alloc-121d0804-2edf-4eec-b85c-7be55dfe3915` | `run-215e146a-e977-40a8-b906-13288bc11483` / `alloc-831b4683-85c1-4039-919d-b9a9f42d680c` | `c2acc5a1060b4f4cd38ae280b3f6f0143c5bd7c85bf40bd0f031ace619660ddb` | `1d04c17b7871ae4dea449fc07c8fcf43aec47a3da58afbd57cc969bcb22f0e1b` | failed / 0.0 / `programbench_behavior_failed` |
| known-bad | `run-9b89e9b6-53a6-4804-ada2-5abe553c667f` / `alloc-d3839919-6383-40c8-b0f0-95be875bc23c` | `run-61b3477f-7e9c-4951-9e0c-1e51e90be894` / `alloc-11f04788-f0d4-448b-bdf8-88640bf8d96b` | `f4d0cdb4dd4878c2ebd3e01b0c625a850fce8fbdba75d44842ac48514914a6b8` | `e04eea77f095368096fe4637f5d5b43cedf8591ce5f2d683c4d709cd79928327` | failed / 0.3333333333333333 / `programbench_behavior_failed` |

The candidate files were independently downloaded and SHA-256 verified before publication:

| Candidate | Bytes | Workspace SHA-256 | Archive members |
| --- | ---: | --- | --- |
| gold | 10,240 | `956a98eeeee643bcf3eba8e7fc37911a6de377ed1a00b1c7509ea6bf88a357f2` | `calculator.py`, `compile.sh` |
| empty | 10,240 | `84ff92691f909a05b224e1c56abb4864f01b4f8e3c854e4bb4c7baf1d3f6d652` | none |
| known-bad | 10,240 | `83f02a9787b914dab6e3ebaa3b88cd8c4bb67eb759d8db482d7b2012fc6fb90f` | `calculator.py`, `compile.sh` |

No CandidateBundle contains the seed-owned reference `executable`. Each verifier ran with deny-all
networking in a fresh Run/Allocation and exited zero; empty and known-bad are legitimate benchmark
failures, not infrastructure failures. `verify-record` returned `integrity_verified=true` for all
three episodes.

## Real Claude Code composition

Episode `programbench-calculator-claude-arm64-20260919-01` used Claude Code 2.1.205 from readonly
rootfs mount
`index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633`.
It used the same provider-neutral DeepSeek configuration as the accepted greenfield vertical and a
caller-only `DEEPSEEK_API_KEY`; no credential value is recorded here.

- inference: `run-adf75c63-3628-451b-8502-41149d5e4b29` /
  `alloc-1b9da627-3ae0-4349-87c4-ff2b1ef8bc81`
- verification: `run-ea7b66c2-d5ac-46b5-b6d3-4d039662dffc` /
  `alloc-19c0b86a-a0e2-420c-bf19-e703251e5088`
- CandidateBundle: `cec006fbdd75fec3aae64db4884b22c57cc33c376e923f59972d9f095b58c1f3`
- TrajectoryBundle: `223e03a9ccaf0549541cbc7d1f0293d5db4d23e17917d2d4e8b64a242212d9f7`
  with 169 canonical events
- VerificationResult: `7cf870139e2b3396c2a72c78498aaeff48e6a074112458e13350a8da84099800`
- terminal reason: `max_turns`
- verdict: legitimate failed / 0.0 / `programbench_behavior_failed`

The agent exhausted 40 turns without publishing `compile.sh`; the candidate archive was empty after
the seed reference exclusion. This is a model/task outcome, not a model transport, Axern, capture,
or verifier infrastructure failure. It proves that the unchanged Claude harness, ModelProxy/Tunnel,
canonical trajectory, workspace candidate, and fresh verifier compose with the new task adapter,
but it does not claim the model solved the fixture.

| Sealed output | Bytes | SHA-256 |
| --- | ---: | --- |
| `workspace.tar` | 10,240 | `84ff92691f909a05b224e1c56abb4864f01b4f8e3c854e4bb4c7baf1d3f6d652` |
| `trajectory.jsonl` | 81,888 | `52f1fa858e6b211776beeed5d97f2677931b794b5932deec53ecb520a22788bd` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 148 | `de76e8c83aac6ac3ab614a3a82c276b12a431400ddf2845f0f23436ccd524124` |

`verify-record` returned `integrity_verified=true`. A fixed-value credential scan of the caller
state directory returned zero matches. After all four episodes, the source cluster reported zero
running or active Allocations and zero running containers, confirming lifecycle cleanup.

## Reproduction

```bash
uv run axrun resolve-programbench-compatibility \
  fixtures/programbench/calculator-v1/row.json \
  --episode-id NEW_EPISODE_ID \
  --candidate-variant gold \
  --inference-image "$INFERENCE_DIGEST" \
  --verification-image "$VERIFICATION_DIGEST" \
  --task-platform linux/arm64 \
  --inference-environment "$INFERENCE_ENVIRONMENT_ID" \
  --verification-environment "$VERIFICATION_ENVIRONMENT_ID" \
  --output /tmp/programbench-calculator.json

uv run axrun --state-dir /tmp/axrun-programbench-validation \
  --context-file /Users/wayne/.config/axern/config.json --context compose \
  run /tmp/programbench-calculator.json
```
