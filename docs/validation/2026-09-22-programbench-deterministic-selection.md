# Deterministic ProgramBench case selection

Status: read-only screening complete; native qualification entrypoint prepared, execution pending. This record does not replace the retained tty-clock evidence or resolve Axern issue 177 / Axrun issue 3. The proposed self-maintained TUI harness patch is paused; none was implemented.

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

## Execution prerequisites and unresolved input boundary

The inspected official metadata/test store and submission index did not provide ready-to-run gold and empty/compile-failure archives for these cases. The available public model candidate is not a gold implementation. Do not invent an official baseline or mutate this candidate to create one.

The user authorized an unmodified fixed upstream seqtk source archive plus an explicitly disclosed build-only `compile.sh` that invokes its Makefile and copies `seqtk` to `executable`. This is a local reference-build fixture, not an official supplied gold candidate. A separately labeled synthetic compile-failure fixture exits 42. The public partial archive remains byte-for-byte unchanged. The bounded native entrypoint is `tools/validation/programbench_seqtk_native.py`; its evidence is private under `/data/forge-artifacts/seqtk-native.*`.

Axrun's current official resolver explicitly accepts only the locked tty-clock contract; it cannot honestly run seqtk by changing the task name. A narrow second immutable case contract and dependency-closed verification image are needed. Existing Forge PR178 profiles are also frozen to tty-clock inputs; use a reviewed controlled entrypoint for the new native/SDK comparison, not arbitrary remote mutation or relabeling old results.

After input approval: predeclare two native repetitions per available candidate, preserve every full test map, and stop to investigate any difference. Pin evaluator dependencies at image build, preserve timeout methods/values and official test/scoring semantics, and explicitly account for moving install commands out of execution. Only then run the same candidates through the public SDK using Axern `029f651a55e9387fad9169660c7877e883c3d75f` and its previously built node manifest `sha256:079cb2f9c746f289f666fff5489517d07167b660f625c6ec14af2477101d95e2` after rechecking deployment identity.

## Independent acceptance state

| Evidence | Current conclusion |
| --- | --- |
| Axern issue 177 original workload | Previous exact-candidate execution reached SUCCEEDED/0; retained original Run and rootfs evidence remains valid. |
| tty-clock gold | Previous 281/281 exact test-level parity remains valid. |
| tty-clock partial | Previous 261/20 differs from historical 262/19; TUI/time-dependent risks and native Docker discrepancy remain open. |
| New native baseline | Not run; image/dependency qualification and gold/failure input boundary pending. |
| New Axrun/Axern vertical | Not run; no new Run, Allocation, derived Environment or cleanup evidence. |

PR178 was freshly checked: all 12 checks succeeded at `029f651a`, and it remains Draft. Screening does not justify closing an issue, marking the complete vertical accepted, merging, tagging or publishing. No product code, official tests, candidates or external checkout files were modified in this screening. No remote containers were started and no Git refs were published.
