# Flask-5014 deterministic Axern parity (stage zero)

This record covers one locked SWE-bench Verified instance, `pallets__flask-5014`.
It is **not** a suite result, a model result, or evidence that an inference image
is free of hidden tests. The adapter remains unregistered while the latter
boundary and real Claude candidate are checked.

## Locked inputs and execution

- Axrun: `2dc4bf83bdd044b8151e9346d12959a22240f81e`, branch
  `feat/swebench-flask-stage-zero`; released `axern-sdk==0.11.4` from the
  installed package; released Axern CLI and local stack both `0.11.4` on native
  `linux/amd64` (`wayne-hk-dev`).
- Dataset `SWE-bench/SWE-bench_Verified` commit
  `78f471bf655a3137b2e8a75af1501690ec009ec3`; complete enriched row
  canonical SHA-256 `36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e`.
  Official harness commit `f7bbbb2ccdf479001d6467c9e34af59e44a840f9`.
- Official source `linux/amd64` platform manifest:
  `docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4`.
  Axern's canonical imported runtime image is the distinct immutable ref
  `index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:98b8b97b38b834eb5a9dad6a42a0380278a911afc74c7025b893ea79294a7da3`.
- Inference Environment `env-59fc947e-cd37-4027-b29a-2473ba59264e`;
  separate verification Environment `env-1de7c125-350e-4eaa-83d2-ada115158476`.
  Both were caller-created from that same imported digest. Each case used new
  qualification, inference, and verification Runs/Allocations with `deny_all`.
- Locked native official oracle receipt SHA-256
  `e16e32a970bf18028ca37f186440d1c064203525f909ad034d8a16c59c18856c`.
  Successful Axern parity receipt SHA-256
  `3a99c1af9f716307d56c2b5b8a2033fbd2dc8798faa5745ce7d111417bee46fb`.
  Complete per-test evidence and logs remain in Git-ignored private validation
  storage; this document contains no hidden test names or bodies.

## Exact comparison

The comparator checked every parsed test status, all four official category
arrays in order, the 60-test denominator for scored cases, missing expected
tests, classification, score, and resolution. All checks were true; no score
rounding or observed-test denominator was used.

| Case | Official / Axrun | Axrun result | Inference Run / Allocation | Verification Run / Allocation |
| --- | --- | --- | --- | --- |
| gold | 60/60, resolved / exact parity | passed, 1.0, `6d0852750d1bfd04a023e11ee8b172007e94946c64a50d8012ac2f47bb15ace0` | `run-5e465b1c-136f-4630-b49f-4000f974550a` / `alloc-1c7db9e1-aa2f-4ba9-aeb6-ec41dc85a48e` | `run-2dcb6d29-68a6-476b-8a5d-0ad0e9c73093` / `alloc-7ef85f90-6860-4ac3-9015-7c21a5488820` |
| known-bad | 59/60, unresolved / exact parity | failed, 0.0, `3353b29ccfe2577614c41d6f66a47e115617b1fccc50bd91c90b9cc5953613c5` | `run-0e8462cb-7ed2-43c3-854d-260bd19a3ba3` / `alloc-0374a689-4175-4bb1-8b17-8ddfc237fc20` | `run-e67c72d3-4a7b-4b6f-8c29-c9fe0385f403` / `alloc-6c8f66d2-52ef-456c-8776-2397690ff3f9` |
| empty | official unscored / exact parity | failed, score `null`, `SWEBENCH_EMPTY_PATCH`, `57fddfd001d3b4969ae8285226a5d04c467965ab27272d4b362654cbb8876a0e` | `run-dc3e2e9c-b65e-41d8-b769-966fc9df96b7` / `alloc-a834ed20-c09b-4ade-bcf7-4bd3e0a4afdb` | `run-f8dfea62-d69b-4967-85e7-b8aa75a90401` / `alloc-0236cbf0-89e7-4f23-ae01-b83c1ce42f87` |

All six principal Runs reached `RUN_STATUS_SUCCEEDED`; qualification Runs also
reached succeeded. Sealed downloads were independently checked against their
manifests and recomputed byte lengths and SHA-256. CandidateBundle digests were
`8c95dca9b768740249d08c5777553f291c69857da7daa0b3e48409f5ada5c29c`
(gold), `850ccd8c07d90f1a6ed4460663fbaeeba04f1a614a02980b2c1006f922d295fe`
(known-bad), and `7b734e166849533ec88e0d9c57b9df4b7dcfcab2533388708de0945d421b04f5`
(empty). Each VerificationResult references its exact CandidateBundle digest.

| Case | Sealed `candidate.patch` bytes / SHA-256 | Sealed `verification.json` bytes / SHA-256 | Sealed `verifier.log` bytes / SHA-256 |
| --- | --- | --- | --- |
| gold | 390 / `087d51d66413bfa35111ac0eca31f1db1636572702cfd967c428049b453f451d` | 8752 / `773aca235477855a328a725356ba6fbb026cfe9c518d70bdf92b277037208110` | 18857 / `d6c5b2ccf3a7fde331347dac300e0158ae8365cd7ddb64900459716888f4cb87` |
| known-bad | 215 / `174037c0c2018173a2fe413b5b8ec30bd4900365b488588fcec3243f433b8114` | 8774 / `757e6694811ab1c2c8b3035ebd9beeac701e4205d8651806e71a69924cb684be` | 18777 / `859e5a93d5b09ee04f0788c83fe14528e922401d769e4c706f9ecfbc2cfd65c2` |
| empty | 0 / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 561 / `3ebcbeaec6e7ab3da8f3e13997e63b5c0f80bc4dd0b60909157b45a57c8864be` | 0 / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The initial Axern gold attempt was **not** scored: a unary SDK `write_file`
request rejected the 863,432-byte offline build wheel before releasing the
verification workload. Its verification Run
`run-3221d800-4290-4971-8100-cc44ac8257ca` / Allocation
`alloc-d0c48684-3b3c-43ca-9472-f8cb1ec0248b` was cancelled. Axrun fixed the
general large-`InputFile` transport in `2dc4bf8` by using the public streaming
archive API. The successful cases above are new episodes, not retries of that
failed episode.

No model credential was required or used. The two parity Environments remain
caller-owned pending the hidden-test image audit and the separate real Claude
acceptance; their cleanup has not yet been claimed. The native oracle uses the
pinned upstream test script and scorer, but does not invoke upstream
`run_instance`; see the [native stage-zero record](2026-09-27-swebench-flask-5014-stage-zero.md)
for that precise boundary.
