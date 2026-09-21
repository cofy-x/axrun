# ProgramBench 1.2.4 tty-clock deterministic vertical

Date: 2026-09-21

This record covers the bounded official-instance implementation and the real linux/amd64 HK
acceptance for `xorg62__tty-clock.f2f847c`. The deterministic empty path has full official parity.
Gold and partial reached an immutable CandidateBundle, successful compile Run, rootfs result,
derived Environment, and fresh branch Run, but exact branch parity is blocked by Axern issue
[#174](https://github.com/cofy-x/axern/issues/174). This record therefore does **not** claim three-path
parity, a solved benchmark instance, complete ProgramBench support, or leaderboard support.

## Fixed versions and identities

| Component | Identity |
| --- | --- |
| Axrun implementation under test | `633a0bb` plus this documentation-only commit |
| Forge | `0595fcd1dd5af95b7b6b202b46fbaf819b465d5e` |
| Axern source/release runtime | `18d26de041d043126a885dc5860334f238eb28d6`, release `0.11.0` |
| Released SDK | `axern-sdk==0.11.0` |
| Kova | `916d795350f1b7305d00ae8b90a5a41e99d776bd` (not used by this acceptance) |
| Openbench | `a666534e83d8a4615d1b5841fb1475d9ab5b64a9` (read-only reference) |
| ProgramBench | package `1.2.4`, git `963063c9271cc40fa179977356782ea4582e0b0c` |
| Instance | `xorg62__tty-clock.f2f847c`, repository `xorg62/tty-clock`, commit `f2f847cf2cc2949c8a8b7779a778f366d3743474` |

Axrun used only the released public SDK. Axern, Kova, Openbench, and Forge were not modified.

The official cleanroom platform is `linux/amd64` at manifest digest
`sha256:7c070e64a44e0b7dc2a032acf02159da43a0a4993a154b5fd98c4ab997726272`;
its config digest is
`sha256:d433c4a48704aee0b45a0f97b43f8bfee5a76bd4299bdeb1133b649e3e151820`.
The HK runtime used a verified mirror reference ending in that exact platform digest, never a
mutable tag or manifest-list digest.

## Evaluator and test asset lock

The v3 single-instance evaluator contract closes two ambient ProgramBench 1.2.4 defaults:

- `pytest-rerunfailures==16.7` is a verifier input with wheel SHA-256
  `edf1886209c2b7dafe35b5bf1708d6ec40ccf6c6b357f0f02807efcec0204c99` and is installed
  offline during the deny-all compile Run. The official evaluator otherwise installs an unpinned
  package from the network after compilation.
- the official 10-container-CPU default is materialized as Allocation `limit_cpu=10` and
  `PYTEST_XDIST_AUTO_NUM_WORKERS=10` for every branch.

| Asset | SHA-256 |
| --- | --- |
| asset lock | `25492e3e109c8f8432e25b8f8a9516c12f96d4da38d39a20eda5f574601beccd` |
| task metadata | `7b84b5c8042b33afed1597a92bd527a4163bb354a89f29a2f2d5e8b24676d36d` |
| tests metadata | `ec1760221921b7614f2c85215b8739203093c1faee45dad70ec6f9d55f8017d6` |
| compile evaluator | `f6221868172e87e0c1587d500f7bd1e17d14a4a34e2d1b277fa8c661c9f6c0dd` |
| branch evaluator | `634395a4b0cd0ca14c9f90dcfe4ed42e72e9a0144e37cbdfb7c84d86ebedad9e` |

The six branch blobs use revision `de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5`; their lengths and
digests remain in `asset-lock.json`. The locked denominator is six active branches, 281 active
tests, zero ignored branches, and 38 ignored tests. Hidden blob bodies were not committed, placed
in a prompt, trajectory, CandidateBundle, or durable episode record.

## Environments and qualification

The acceptance created separate official-image Environments:

- inference: `env-02851ccc-7317-4216-a07e-e66f8bc5ebf7`;
- verification: `env-d696bf84-14a0-4e25-aa46-ca13489ab1a3`.

Both qualified as `linux/amd64`/`x86_64`, preserved `/workspace`, and verified the seed-owned
regular `executable` with execute mode `0111`. Final v3 qualification Runs were:

| Variant | Inference Run / Allocation | Verification Run / Allocation |
| --- | --- | --- |
| gold | `run-75a82253-ec0e-4e22-b159-5f5fae11eb8e` / `alloc-17455655-b6d7-4002-ae65-d136d9767a02` | `run-c51013d1-3b2c-4dd7-a787-c552c2ca3474` / `alloc-42f6c517-00e0-499b-9aa9-9962af8bbe27` |
| empty | `run-835e7b31-32ff-424a-a708-cf59fea475a8` / `alloc-29588425-8692-4645-8636-5bc3716a7598` | `run-2e513755-1107-4a5b-acc8-7aaddb8645b5` / `alloc-f2b15ea7-8d69-4ecf-84ac-0eb38374db62` |
| partial | `run-376f54d4-b946-495d-9954-ed2291fd5232` / `alloc-3a4bcad9-77bc-4fd7-bab7-50ea121b4903` | `run-036bedb6-97ef-42d1-9267-573f79868074` / `alloc-4ac808ae-57d0-42cb-87c6-eab84e1822d5` |

## Candidate and compile evidence

Each inference Run used static-candidate plus canonical `workspace-archive@1`; the seed-owned
reference executable was excluded by its exact top-level path.

| Variant | Inference Run / Allocation | CandidateBundle digest | workspace.tar bytes / SHA-256 |
| --- | --- | --- | --- |
| gold | `run-e0ae8728-654b-409b-940d-7948ab7f6b0a` / `alloc-116e0452-13fc-40e8-810c-9b4c5cf62ca0` | `82b5c992b33fa2a94fac6a48bc2b65920d78f606e7bc40d0b50721b12cd3613c` | 102,400 / `c8f6ad45e921d2af64291fb6263f3b72b58ff8690fe0114aca8305969076f0b6` |
| empty | `run-60887c8e-e6fd-4114-8b5d-ababfc1bd2b8` / `alloc-de3dd221-5f8a-4485-b886-3dd6231bee0e` | `8b88d57feef2ce042206d2a0ad89c4a2f6888134d9d3fba63f3affcf51312732` | 71,680 / `896d58983dd5b8814c3f8b392768f2ccc88de6f8717bb7ec0667929473ad1d36` |
| partial | `run-e8cbea8c-6f3b-4821-a49a-72a83d32c9c3` / `alloc-61e6ef0d-c030-4baa-ac8f-d2326bc97827` | `4e36401780a8677cfd6c59388555e742af815456db8fddd910b252d9576c7ba1` | 102,400 / `20614bf97fd64dbc57b87f10166119ec40e232a4f4595913c55c762f669db778` |

Gold compile Run `run-dcf0929f-1a9a-4c71-9af2-12a7eab6e285` / Allocation
`alloc-febb7757-fe06-46d1-9c74-ba98e9bdd689` produced executable SHA-256
`02a20572293650b3337efd8e20e6ea9a0bc1be69cec0ca3e94954dc54b27fe3c` and derived
Environment `env-6d93eba8-5432-5711-a83f-73f160b80fc3`.

Partial compile Run `run-7d71379b-299c-40db-ada4-e0875597000c` / Allocation
`alloc-c76f8779-5b1a-41f9-a6d9-55c39c9af425` produced executable SHA-256
`5f139009858310f008dbbc9165ff0b5c99e3a7968a1dbe2651c9b8f6e1d18d77` and derived
Environment `env-d63c6c1d-60c9-5b79-9489-64beb86c48bb`.

The empty compile Run `run-76e7b81f-16e9-44fb-8f35-600428d60c0a` / Allocation
`alloc-54199ecd-f795-4f67-a033-3722755ed590` produced the legitimate business failure
`compile_script_missing`; no derived Environment was created.

## Official baseline and parity

ProgramBench 1.2.4 official evals ran in Docker with the locked linux/amd64 image. Inputs and evals
were content-hashed:

| Variant | Submission SHA-256 | Official eval SHA-256 | Official result | Axrun result |
| --- | --- | --- | --- | --- |
| gold | `8f43444ec761d582df3ba1d0bb5c18edb5bad812bb3e63e5335ba784cc2e66c3` | `f752a49cacf622e9938826dfa3a6769966335ad60fe7c2c51b13861171c84bca` | 281 passed, score 1.0, resolved | blocked in first fresh branch; no VerificationResult |
| empty | `32b77b51d0cb07099afc59fe28f370890ca0816352ec20c1aad2a1df1512c371` | `3fd6f54ef991679f274a38c7a38ce6fc8e99cbb405670bd72fc7810ca6842941` | 281 not_run, score 0.0, unresolved | exact parity |
| partial | `014c53e0d729889be17fea2505940a798a504610224df7085a9dce39caeca238` | `d6fd3c3312f85f331d43113930b2a366f981014542309885b41844b450ac73d7` | 262 passed, 19 failed, score 0.9323843416370107, unresolved | blocked before accepting first branch result; no VerificationResult |

The empty VerificationResult digest is
`1b405f6595c8a7d01168358aadc63acbfd9667659ef7989ad0ef64c7eb6f10ff`; verdict `failed`,
score `0.0`, diagnostic `PROGRAMBENCH_COMPILE_FAILED`. Its benchmark details digest is
`8855356e43a50a6d4ca3a067124732e441b9456c0c36fc02a5f35c2505ead214`. The parity comparator
reported equality for executable hash, active branch/test counts, passed/failed/not_run, ignored
handling, branch errors, score, resolved, and every expected test status.

No business verdict was generated for the blocked gold or partial paths. The canceled Runs were
not converted into `failed` scores.

## Resume acceptance

Before the official rerun-wheel and CPU defaults were locked, a real interruption/resume exercise
proved durable multi-Run identity reuse. Caller termination happened after branch
`9951be903ea4` persisted Run `run-54acc4d4-b7bb-4977-a7fa-36f7e7d07700` / Allocation
`alloc-b1067f33-73b6-47db-a3b8-75c23cef87ee`. `axrun resume` reused that exact Run and completed
all six branch records without duplication. The compile Run was
`run-5bf618e9-0ad5-4b64-a763-14220a4e844e` / `alloc-7c587085-fac3-47c4-b7aa-31966a5f07b1`,
and execution cleanup reached `completed`.

That pre-v3 run scored 237/281 and is retained only as resume evidence. It is not parity evidence:
it exposed the missing official rerun-wheel and CPU defaults that v3 now locks.

## Axern blocker and Docker control

Final v3 gold branch Run `run-3d35a3d2-dae6-4efb-813a-f2d735cd7524` / Allocation
`alloc-892745b3-11bb-461a-9536-e29b2ec9078e` used the successful derived Environment, 10-CPU
limit, 10 xdist workers, locked rerun wheel, exact executable, and exact branch blob. It remained
running while one tty-clock child consumed a CPU core and did not converge under
`pytest --timeout=5 --timeout-method=signal`.

An ordinary Docker control with the same locked inputs, `--init`, `--cpus 10`, and 10 xdist workers
completed that branch in about 32 seconds with 20 passed and zero failed. This is recorded in
Axern issue [#174](https://github.com/cofy-x/axern/issues/174). The partial first branch reproduced
the same boundary and was canceled without waiting for another hang.

## Security and cleanup

- A text scan of the complete episode state for credential/header markers returned zero files.
- A scan of all CandidateBundle manifests for a locked branch-blob digest returned zero matches.
- No model credential or Tunnel was used by these static-candidate paths.
- Hidden test bodies are present only in ephemeral verifier asset storage, not durable Axrun
  episode/candidate records.
- The resume-derived Environment was auto-deleted. All blocker-reproduction branch Runs were
  explicitly canceled and their owned derived Environments were deleted through the public SDK.
- Terminal branch infrastructure failures now perform the same idempotent derived-Environment
  cleanup before surfacing the error; ambiguous caller interruption still preserves state for
  resume.
- The two base official Environments were deleted after evidence collection. The task-scoped
  acceptance directory was moved out of the active artifact namespace into recoverable trash. All
  50 recorded owned Runs were terminal at cleanup: 43 succeeded, four failed, and three canceled.

No credential, token, private address, kubeconfig, hidden test body, or private API appears in this
record.

## Reproduction boundary

After Axern issue #174 is fixed, create new episode IDs from the locked v3 row, qualify them, and
run gold and partial again against the same official image and asset digests. Exact parity requires
all 281 test-level statuses for gold and all 281 statuses for partial to match the fixed official
evals; a final float score alone is insufficient. Until then the only accepted parity result in
this record is empty.
