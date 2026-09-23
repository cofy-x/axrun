# Deterministic ProgramBench case selection

Status: seqtk native repetition and public-SDK vertical passed. This record does not replace the retained tty-clock evidence or resolve Axern issue 177 / Axrun issue 3. The proposed self-maintained TUI harness patch is paused; none was implemented.

## Inputs and inspection

ProgramBench checkout is `963063c9271cc40fa179977356782ea4582e0b0c` (1.2.4). Its existing uncommitted `uv.lock` was preserved and not used to update dependencies. Test blobs were inspected in memory at dataset revision `de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5`; no test or candidate contents were changed or vendored.

All active branches of the three candidates were inspected for evaluator entrypoints, imports, subprocess fixtures and timing/network/TUI indicators. Absence of a textual indicator is not proof of deterministic behavior. Native repetition and dependency closure remain required.

| Rank | Instance | Active branches / tests | Observed behavior and risks |
| --- | --- | --- | --- |
| 1 | `lh3__seqtk.94e7070` | 2 / 429 | File/stdin/stdout subprocess fixtures with 5/30-second deadlines; pytest, timeout and xdist setup. No TUI, wall-clock or external-network indicator found. Sampling tests generally specify seeds; a test checks default seed 11. Random-base/heterozygous behavior still needs native qualification. Fixed source Makefile compiles C with GCC, zlib and libm. |
| 2 | `wfxr__code-minimap.0ddeea5` | 8 / 313 | File/stdin CLI behavior, encoding, shell completion and broken-pipe cases. No TUI/wall-clock/network indicator found in inspected scripts. Multiple pip-upgrade/install entrypoints; dependency plugin used in one branch. Rust offline build closure remains unverified. |
| 3 | `wgunderwood__tex-fmt.3f1aef6` | 8 / 455 | File formatting, but test assets also import Pillow and Matplotlib. Two URL occurrences require semantic classification, not an assumption of network dependence. More dependency and resource uncertainty; public result includes two test errors. |

Seqtk is provisionally preferred for its two genuine independent branches, small C build surface and bounded file-oriented fixtures. Test count alone was not the selection criterion. No CPU, memory or duration measurement has yet been performed for any candidate.

## Frozen identities

Seqtk source commit: `94e707082d39b0a038f234df676e32d9802c0dc7`. Its upstream Makefile uses `gcc ... seqtk.c -o seqtk -lz -lm`; it does not supply a ProgramBench `compile.sh` submission contract.

| Seqtk test branch | Compressed bytes | SHA-256 |
| --- | ---: | --- |
| `e592c32aec70` | 107995 | `3a9ba4e29bf1eed9cc80b8c8eab537af092fc0b559f8f05eac326b8f5a7943a0` |
| `5d974fdda794` | 73593 | `b908e8eda5bdbb72b338c20a80ec7f18a086a92ee4f5e34a56b72303cb650d11` |

Registry manifest lookup resolved `programbench/lh3_1776_seqtk.94e7070:task_cleanroom_v6` to `sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0` (875064597 compressed layer bytes). Code-minimap resolved to `sha256:9e0f3eab44f2ed0b5a28eeea0a0b63a0790bcfce3f09dc610ec92bb679bcc332` (917065968 bytes). These were manifest-only observations: image config architecture, installed dependencies and offline execution are not yet validated. Tex-fmt registry lookup failed with a TLS EOF; no image identity is asserted for it.

The official submission index was read at `794fa30bbfd65059d5c67e192ceb6da659c9ef51`. Its GPT-5.4 pointer fixes the public submission repository to `f43ff067bfcf052c8d3fa37cf7a580d65fde4d17`. For seqtk:

- Candidate dataset revision: `23f521694f9f5f6310d736ff9a7af16cd4cb49ce`.
- Downloaded candidate archive: 6630 bytes; SHA-256 `e13533d16886d84814f3fe45975c8d255a7333f17028ca606da1e011e231cdaa`, matching the public checksum.
- Original compile script copies `seqtk.py` to `executable` and sets executable permission; no dependency installation.
- Published eval JSON SHA-256: `d0e7b65c16e5709208d1cd1ae73b33f0d7475eb9cbc07c0d89d06c240bb782a5`.
- Published executable hash: `09fb0650707f0e9b10c91252a18c0f1b4a8d5f513eeb69dc7041c5b070a4eab0`.

The historical eval contains an additional branch not in the current task metadata. Its raw 611 results must not be compared with a 429-test denominator. Projecting by exact `(branch, test name)` onto the fixed current metadata, applying its ignored tests, yields 173 passed / 256 failure, with no missing active result. This is a historical reference projection, **not** a new native baseline or a newly measured score.

The same projection of that public model submission gives code-minimap 119 passed / 194 failure and tex-fmt 251 passed / 202 failure / 2 error. Neither has been rerun. Test bodies, assertions, expected values and scoring have not been changed.

## Approved execution inputs and boundary

The inspected official metadata/test store and submission index did not provide ready-to-run gold and empty/compile-failure archives for these cases. The available public model candidate is not a gold implementation. Do not invent an official baseline or mutate this candidate to create one.

The user authorized an unmodified fixed upstream seqtk source archive plus an explicitly disclosed build-only `compile.sh` that invokes its Makefile and copies `seqtk` to `executable`. This is a local reference-build fixture, not an official supplied gold candidate. A separately labeled synthetic compile-failure fixture exits 42. The public partial archive remains byte-for-byte unchanged. The bounded native entrypoint is `tools/validation/programbench_seqtk_native.py`; its evidence is private under `/data/forge-artifacts/seqtk-native.*`.

At screening time Axrun's official resolver accepted only the locked tty-clock contract. The implementation now selects between two explicit frozen case contracts, with task qualification and the existing verifier consuming the same case identity. Seqtk has its own locked metadata and evaluator assets; there is no new backend or durable execution lifecycle. Separate Forge `seqtk-native` and `seqtk-sdk` profiles invoke the bounded native entrypoint and existing public-SDK CLI respectively, without repurposing the tty-clock acceptance result.

Two native repetitions per candidate were declared before execution and every complete test map was retained. Dependencies are installed from the existing hash-locked 1.2.4 evaluator closure at image build time. Native scripts retain their pip setup lines with `PIP_NO_INDEX=1`; already installed dependencies satisfy them. SDK helpers remove only those exact setup lines after preflight. Both preserve the official 1.2.4 evaluator's thread-to-signal timeout adaptation and `--max-worker-restart=4 --reruns=2 --reruns-delay=1` policy. There are no additional outer retries, sleeps, assertion changes or best-of-run selection. Official test bodies and the published partial archive remain unchanged.

## Independent acceptance state

| Evidence | Current conclusion |
| --- | --- |
| Axern issue 177 original workload | Previous exact-candidate execution reached SUCCEEDED/0; retained original Run and rootfs evidence remains valid. |
| tty-clock gold | Previous 281/281 exact test-level parity remains valid. |
| tty-clock partial | Previous 261/20 differs from historical 262/19; TUI/time-dependent risks and native Docker discrepancy remain open. |
| New native baseline | Two reference-build runs: 429/429 each; two public partial runs: 173 passed / 256 failure each; two synthetic compile-failure runs exit 42. Full mappings and executable hashes agree between repetitions; partial agrees with the fixed published active-test projection. |
| New Axrun/Axern vertical | Reference-build 429/429; partial 173/256; both exactly match native test maps and executable hashes. Failed compile yields no derived Environment or branch execution. Fresh write isolation and cleanup passed. |

PR178 was freshly checked: all 12 checks succeeded at `029f651a`, and it remains Draft. The new bounded deterministic verifier vertical is accepted; this is not an end-to-end model inference run or acceptance of every remaining TUI issue. No Axern or ProgramBench source, official test, public candidate or external checkout file was modified. No Git refs were published, no issue was closed, and no merge/tag/release was performed.

## Native execution evidence

Registered host: `wayne-hk-kvm`, native Linux amd64. Private evidence: `/data/forge-artifacts/seqtk-native.0398np4n`; profile receipt: `/data/forge-artifacts/20260922T085603Z-1cf0c6298387-57125/forge/seqtk-native.meta`. Axrun native tool commit: `a2c30fb47878154fb09889ede2ce3cfb98f03368`.

- Native evaluator OCI **index** identity: `sha256:7b48e4b8974712a1eed58b139db15a8f2c956c4aeb5bd97d91a8b32dcb1abd6c`, inspected as linux/amd64; not mislabeled as a single-platform manifest.
- Base platform config: `sha256:742ff17f7c2fb045550e0545750ba44c698a9801bfffe0cdb13c9ad9610801ac`.
- Dependency lock: `9b14aaddb4cd53fe338a8bf4391b0eed12ea264c49a4c47e7b774d54735f4777`.
- Upstream source archive: 24058 bytes, SHA-256 `db2126519e0f1a8ff7a924c11a575a5719e86690919238281736109410004157`.
- Reference executable: `348c6e08241681487a4031afd1c34c6970409209adaed9e8a04330be0c0b1e7b`.
- Partial executable: `09fb0650707f0e9b10c91252a18c0f1b4a8d5f513eeb69dc7041c5b070a4eab0`, also equal to the published result.
- Resources: Docker `--cpus 10 --memory 8g --network none`; 10 xdist workers. Base image environment and complete Docker commands/phase logs are reproducible from the frozen entrypoint and image inspect receipt.

All six candidate executions were retained. Both reference runs passed every active test; both partial results contained 429 outcomes with zero missing tests; synthetic failure was never scored as an officially supplied candidate. Created containers and temporary post-compile images were removed; base/evaluator cache and private artifacts remain intentionally retained. `cleanup_errors` is empty. The image build took 8.97 seconds with existing cache. Recorded Docker wait intervals were about 0.91 seconds for reference compile and 1.72/2.17 seconds for its branches; partial branches took about 40.7/18.1 seconds. These are local phase-wait measurements, not cold-build costs or production capacity claims.

## Public SDK execution evidence

Evidence: `/data/forge-artifacts/seqtk-sdk.GEWqqEy0`; profile receipt: `/data/forge-artifacts/20260922T091541Z-dc915c84a961-65868/forge/seqtk-sdk.meta`, exit 0. Axrun executed commit `714df76af8d2d68afe6e9a581c0ebdde0ee7cceb` through released `axern-sdk==0.11.2`. Axern stayed at `029f651a55e9387fad9169660c7877e883c3d75f` with node registry digest `sha256:079cb2f9c746f289f666fff5489517d07167b660f625c6ec14af2477101d95e2`. The previously recorded exact-source build was reused, not a release image.

Deployment: `axern-pr178-gewqqey0`; node container `bb04cdbc0028cf4e9cb93bafdcdae69db2e64c852d57d671f6e1e1478b2f5e88`. Evaluator single-platform registry manifest: `sha256:9e8eadb4a0a124474e76287748f1111b95f5e033ecf0030064afb0e5efb24e4b`. Native and SDK evaluator identities are recorded separately; both use the same base and dependency lock. Go was 1.26.8 and the candidate's required toolchain was checked.

| Stage | Run | Allocation | Outcome |
| --- | --- | --- | --- |
| Reference compile | `run-4095c18b-a202-4e3d-a5b8-992b30ad1ad6` | `alloc-4937d485-cf71-4f41-851e-32bcae645e96` | SUCCEEDED/0, then rootfs READY |
| Reference branch 1 | `run-62c3adce-7d7a-46a8-98e3-c80b42a9ecbf` | `alloc-b2d444ac-d147-4310-a131-3174577efa0b` | SUCCEEDED/0 |
| Reference branch 2 | `run-7c901b5f-19ad-4948-b2e5-425bd6864429` | `alloc-8f82278c-20a8-4998-ae18-fceef53e9753` | SUCCEEDED/0 |
| Partial compile | `run-763b35f4-1963-4c93-a7b8-efa687a21dba` | `alloc-d5a9093b-5755-47ca-b895-b25eb6a779cc` | SUCCEEDED/0, then rootfs READY |
| Partial branch 1 | `run-bb5db470-0901-4834-9612-89d94a933da4` | `alloc-4d5218c0-76fb-44f8-9747-778e2fc00aec` | SUCCEEDED/0; candidate test failures remain structured results |
| Partial branch 2 | `run-ec45e68e-8d61-4dfd-b745-97756628fad5` | `alloc-c4510101-8a27-4b47-9718-6cc49d1b70b4` | SUCCEEDED/0; candidate test failures remain structured results |
| Synthetic compile failure | `run-14f7ff3e-4730-4e0d-9ef3-1cab547de6e8` | `alloc-cdc9e566-a7d7-436a-b8b5-90e1bdf1fbc0` | FAILED/23: adapter's compile_failed code for the script's exit 42; rootfs FAILED, no Environment |

Reference rootfs: `sha256:72c09d1080cc2661132d982ebf3fd509f71dcccf6b605db010706d9f9d16b925`, derived Environment `env-8f71788f-6a40-55c9-b6ba-0946513e89e5`. Partial rootfs: `sha256:caa888c92470019586cb9c2c789b1162ade042a1c61b36b661d8b9b12e9a6060`, derived Environment `env-2db725cf-d850-59d4-b332-38a2d8019f6b`. Both derived Environments were deleted by the existing adapter after their separate branch Allocations completed.

Two additional SDK probes rebound the reference's public immutable image into `env-899669dc-5f80-4943-9515-31777650b833`: `run-075274b6-342b-43c6-921b-ed82bc6ee18f` / `alloc-f009b667-3ae5-4366-b9b6-f652872f77b1` wrote a private marker; `run-75004671-5ee7-4167-ac6b-bb53281a8dc0` / `alloc-57339948-9627-404c-b501-06e14c9f5114` could not see it. Both succeeded. This explicitly uses a new Environment binding after the adapter's original derived binding was deleted; it does not claim reuse of a deleted identity.

SDK cleanup reported zero errors. Candidate Compose and registry stopped, and a final Docker inventory showed only the pre-existing published `axern-local` stack running. Logs, stopped deployment state and image cache remain for evidence, not as active episodes. No Node target, runtime identity, node socket or private Proto was consumed by the runner.

## Corrections, scope and remaining limits

Two unsuccessful setup attempts remain recorded:

1. `seqtk-sdk.kVVQouIp`: BuildKit's base cache was not a runnable Docker image-store entry. No benchmark Run started. The coordinator now explicitly pulls the fixed digest and verifies architecture before mirroring it.
2. `seqtk-sdk.Edw9KskO`: the first adapter revision incorrectly made the native probe's 8 GiB protection an obligatory workload hard limit. Compose explicitly uses `disabled_dev` cgroup enforcement and correctly rejected admission with `capability_unsupported`. Official 1.2.4 fixes CPU count but no such hard-memory capability. The invented requirement was removed, not bypassed in Axern. SDK requests retain official CPU concurrency; native Docker's 8 GiB cap and Compose's lack of per-Allocation hard-memory enforcement are different resource envelopes. This comparison establishes functional parity, not production resource isolation or equal memory-performance behavior.

After the successful SDK run, review found that the resolver returned a reference to its locked remove-hash list. `2254d16546b4463d7c0f79e3bbb2b843f09cc4da` copies that list and adds regression coverage; it does not change serialized episode data, verifier assets or Run payloads. Resolving both fixtures with the executed candidate and the hardened implementation produced identical full serialized contracts. The original candidate SHA remains the truthful real-run identity; the subsequent alias-safety change was verified locally rather than rerunning unchanged container workloads.

Validation: the final Axrun full suite passed **213 tests in 12.90 seconds**, with Ruff, formatting and Pyright passing. Six execute/recover tests cover unsuccessful workload refusal and sealing-error-to-InfrastructureError mapping; 24 directly affected tests also passed. These tests do not claim real registry-failure injection or a fresh real cancellation run. Existing Axern unit/race/OCI/PTY/SSH/restart evidence was reused; no Axern code changed. Forge profile checks, isolated tooling tests and lint passed, and the initial Forge suite passed all 90 tests. Staged diff checks and redacted Gitleaks scans passed.

The achieved scope is the first stable static CandidateBundle → compile → rootfs READY → derived Environment → isolated official branches → structured result → cleanup vertical. No new model inference, production memory qualification, broader benchmark suite, tty-clock patch or release is included. It is sufficient to request focused PR178 acceptance/merge review with the outstanding TUI limitation disclosed, not to claim every historical issue solved. Stop expanding this round's scope.
