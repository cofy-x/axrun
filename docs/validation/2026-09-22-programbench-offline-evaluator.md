# Dependency-closed ProgramBench evaluator acceptance

## Frozen inputs

- Axrun implementation: `c6455f59139e0229e961c045966793ae66aa064d`, dependency refinement: `0cedd1db6643c932d047b0b98afef0dc1d833c5a`; signed local commits, not yet published.
- Released public client: `axern-sdk==0.11.2`; no SDK or Axern product code changed in this round.
- Axern PR 178 candidate: `029f651a55e9387fad9169660c7877e883c3d75f`; all 12 GitHub checks passed.
- Native linux/amd64 node manifest: `sha256:079cb2f9c746f289f666fff5489517d07167b660f625c6ec14af2477101d95e2`.
- Evaluator manifest: `sha256:8c5c4c87ff3420e34c189ea34917128f8837b3eb1b6ba248f6a8866067b6df0f`.
- Dependency lock: `9b14aaddb4cd53fe338a8bf4391b0eed12ea264c49a4c47e7b774d54735f4777`; image build preserves installed official-base versions and adds the missing timeout/rerun plugins.
- Official instance, source image, branch blobs, candidates and official eval JSON remain unchanged. Runtime networking remains deny-all.

## Fix and local checks

Static dependencies now belong to the canonical verification image, not each compile or branch Run. The resolver requires a separate immutable verification image. Compile and branch preflight verify installed versions and the expected lock digest. The branch adapter removes only explicitly matched package-install commands from each locked official setup script; it preserves test bodies, pytest arguments, rerun policy, CPU count and scoring.

Missing dependencies, invocation failures and missing/invalid/empty result XML produce body-free infrastructure diagnostics. The caller retains the sealed diagnostic, cleans the derived Environment and raises InfrastructureError instead of publishing a benchmark score. A persisted infrastructure failure cannot silently restart verification.

Ruff, formatting, Pyright, diff/staged checks and staged Gitleaks passed. The implementation passed all 197 unit tests; the subsequent dependency-only refinement passed all 22 directly affected tests. A broad working-directory Gitleaks scan also found two pre-existing ignored local benchmark logs; those files were not staged, copied into the candidate or published. The scanned staged patch had no findings.

## Real candidate results

Private evidence is retained on the registered KVM host under `/data/forge-artifacts/pr178-acceptance.3TsJqAzy`. The source Compose project was `axern-pr178-3tsjqazy`; node container `23d7dc042492a4897d5eeda09e7e11e16bc100c4cb115ed8597e933286fd1dda` used the exact node manifest above. The published stack was not replaced.

| Check | Result |
| --- | --- |
| Issue 177 original branch `89bbe1810fa3` | SUCCEEDED/0; Run `run-df9adb81-e3cd-4ba9-8d6d-f791191456df`, Allocation `alloc-0ab1378a-b372-468c-ae4f-072b6c34ca41`; unchanged gold executable digest `02a20572293650b3337efd8e20e6ea9a0bc1be69cec0ca3e94954dc54b27fe3c` |
| Gold | All six fresh branch Runs terminal; 281 passed, 0 failed, 0 not_run; exact official test-level parity and executable digest |
| Partial | All six fresh branch Runs terminal; 261 passed, 20 failed, 0 not_run; **not** parity with the frozen 262/19 baseline |

Gold compile Run `run-68566ee6-3b97-40ad-83c6-cc92ae323e5b` / Allocation `alloc-860e85e7-dd9b-4820-ba08-a73baed7e933` succeeded, then produced rootfs READY `sha256:391e58bb2961c25a8b125f0007b167c0b62fabda6022063f7a6126aad063268a`, derived Environment `env-d7949856-ee0e-52b5-aa0c-c39df4b1af30`.

Partial compile Run `run-db2f008e-dcac-43e0-a7cb-af3cd723ee7f` / Allocation `alloc-95fab764-fb63-470f-a5c2-856f5c73d67e` succeeded, then produced rootfs READY `sha256:c38daac75e97d62e9eea97b68e999347266e0061bd759eb4363d8ba112736570`, derived Environment `env-947d4086-eeee-5eaf-ad7f-3b062c8cbe79`. Its executable digest matched the official partial candidate. Every branch used a separate Allocation; earlier independent writable-isolation smoke remains valid and was not needlessly repeated.

The partial discrepancy is `ed5c2b1ffc48/tests.test_tui_interactive.test_case_insensitive_keys`. A single diagnostic branch execution using unchanged verifier bytes and the same sealed image passed that test, but `tests.test_tui_rendering.test_custom_format_with_twelve_hour` changed from the baseline's failure to passed. Last-occurrence-wins comparison was applied to repeated JUnit entries, matching the official scorer. Diagnostic traces and XML are private evidence, not replacement acceptance or a best-of-results score.

The Axern diagnostic was Run `run-54bce2b5-92ea-4b28-9541-f44c1a005dfe` / Allocation `alloc-505bcdc5-4355-4423-a5d7-ddcc72d5d9b2` (`pr178-diagnosis.dfFdYRl8`). One ordinary Docker control (`pr178-diagnosis.UzaNUhiO`) used the identical sealed rootfs, candidate digest, branch blob, verifier bytes, 10 CPUs, 10 workers and no network. It completed and reproduced the same remaining `test_custom_format_with_twelve_hour` baseline difference. This rules out attributing that difference solely to Axern; it does not establish the exact cause of the TUI variability. Neither diagnostic is a full partial rerun.

The full partial result remains failed acceptance, tracked separately in [the partial baseline stability issue](https://github.com/cofy-x/axrun/issues/3). Do not change expected scores, broaden timeouts or retry until green. No merge, tag, publication or issue closure is justified by the diagnostic run alone. All owned candidate services and the Docker control were stopped/removed after their bounded runs; evidence and state were retained.

## Follow-up: time-dependent test assumptions

Read-only inspection of the locked `ed5c2b1ffc48` asset identified two independent test-contract weaknesses. No upstream test, candidate, runtime or score was changed in this investigation.

1. The custom-date test normalizes weekday/month/day/meridiem text but retains the rendered leading spaces. The candidate centers its date window using the actual string width. Executing the asset's original normalization functions on the golden line and a correctly recentered Tuesday-to-Wednesday variant gave identical normalized date content but different equality results: 11 versus 10 leading spaces. This is a deterministic normalization counterexample, not a claim that a particular historical failure happened on a Wednesday.
2. The case-insensitive-key test compares the maximum per-row ANSI background-color-run count before and after toggling seconds, allowing only a difference of two despite elapsed wall time. A calculation using the unchanged candidate's digit matrix and draw layout gives a counterexample across `01:59:56` to `02:00:06`: 10 versus 13 color runs with seconds enabled at both endpoints. This is a rendering-model counterexample, not a new real-terminal acceptance result. The test also invokes a screen-stability helper that only warns when its deadline expires; screen stability is not proof of the intended application state.

These observations explain why a single historic partial score is not a universally stable oracle. They do not identify which assertion failed in the first full partial run, whose body-free result did not retain that assertion. The existing native Docker control remains evidence against assigning the entire discrepancy to Axern alone.

A long-term correction belongs in the benchmark test/harness: assert the intended key/state transition independently of changing clock digits, and validate centering against normalized content rather than a date-specific absolute offset. Do not freeze the Axern clock, add runtime-specific sleeps, relax the color tolerance, remove tests or change expected scores. A minimally patched harness requires an explicitly versioned contract, preserved original assets/results, upstream review and separate qualification; it cannot be labeled unchanged ProgramBench 1.2.4 parity. The subsequently authorized patch was paused by the user's deterministic-case selection decision before implementation. Existing tests and evidence remain unchanged; tty-clock is a separate TUI compatibility case.
