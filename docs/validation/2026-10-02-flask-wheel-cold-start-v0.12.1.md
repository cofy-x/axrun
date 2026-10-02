# Flask independent-wheel cold start on Axern v0.12.1 — 2026-10-02

## Outcome and scope

The previously blocked formal cold start **passed** on the released Axern v0.12.1 stack. One new, independently installed Axrun wheel and one new caller-owned state directory executed the normal CLI path `admit → resolve → qualify → run → completed resume → verify-record → report`. All seven commands exited `0`. Exactly five fresh public Runs and Allocations were created: the admission scanner, two qualifications, static-candidate inference, and a fresh verifier. All five were `RUN_STATUS_SUCCEEDED`, exit code `0`; the completed report has `integrity_verified=true`, verdict `passed`, score `1.0`, and an exact 60/60 match to the locked official gold test map.

This is a single fixed `pallets__flask-5014` gold-candidate consumer acceptance, not a new oracle run, a real-Claude/model-credential test, generic SWE-bench support, a load or race-stress proof, or a rerun of network-egress and Tunnel qualifications. There was no selection among candidate outcomes and no retry of the old v0.12.0 failed Run. The [2026-09-28 failed cold start](2026-09-28-flask-wheel-cold-start.md) remains a separate historical record.

## Released platform and independent consumer provenance

- Axern CLI/local stack and public SDK: released `v0.12.1` / `axern-sdk==0.12.1`; annotated release tag and main commit `c0d8444964d21468d2e778a769570cc7b21b00ef` were verified before the retest. The HK-dev managed stack's node image was `ghcr.io/cofy-x/axern/node-all-in-one@sha256:a6711d0d8a2dbfec29789ba7f337c1cc0b245a0ae005b9f05d9a6380afcf52ed`; managed `up` and `doctor` completed healthy.
- Axrun consumer source: branch `feat/flask-wheel-cold-start`, commit `7d4bb5d263be7b591849c7b2d334636f77d6f341`. The registered native `linux/amd64` build profile completed successfully for that exact commit before the wheel was copied outside the source checkout. This commit pins the released SDK; the productized CLI baseline is merged PR #12, `7e917204ee2df5907791f0d817ec4d44013a5831`.
- Independent package: `axrun-0.1.0.dev0-py3-none-any.whl`, SHA-256 `25d7765d9fbedfd698a6fe87a4097406765f99e5b042448ae641c44e93c6c98e`, installed into a new Python `3.12.3` virtual environment on native `linux/amd64`. Preflight compared all 79 wheel Python assets byte-for-byte with the installed package, confirmed the `axrun.cli:main` console entrypoint, and rejected source-checkout imports and bundled `tools/validation`. After resolution, the acceptance confirmed the installed-wheel verifier path and rejected source paths in the episode. The public SDK had no `direct_url.json` source/path install.
- Installed distributions recorded in the acceptance summary: `axrun==0.1.0.dev0`, `axern-sdk==0.12.1`, `grpcio==1.84.0`, `protobuf==7.36.2`, `PyYAML==6.0.3`, and `typing_extensions==4.16.0`. The caller ran with `python -I`, an explicit local TLS context, and a closed subprocess environment containing only PATH, LANG and PYTHONNOUSERSITE; TLS material was not copied into this record. No model credential, caller-side ModelProxy, Tunnel or static trajectory was created.

HK-dev's old DEV-only Axern local state was intentionally reset without backup before the managed v0.12.1 upgrade; that host-local version switch is separate from the new acceptance's exact Run/Environment cleanup below. No old Run was revived, migrated, or presented as v0.12.1 evidence.

## Fixed task inputs

- Instance `pallets__flask-5014`: the locked `SWE-bench/SWE-bench_Verified` enriched-v1 row from dataset commit `78f471bf655a3137b2e8a75af1501690ec009ec3`, complete canonical row SHA-256 `36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e`, seed digest `077cf80a3e58c24d38ab8124db646a70b4f0a5d3ad389685d0f52d1b466835eb`.
- Fixed official gold patch SHA-256 `087d51d66413bfa35111ac0eca31f1db1636572702cfd967c428049b453f451d`; locked official gold grade input SHA-256 `bddca4fbdf735900724faee6494a3c3acdeb6e78fcf813e7ef6147dc7659cd51`. The grade is a pre-existing expected-result input, not a new upstream oracle execution. The official harness/scorer revision remains `f7bbbb2ccdf479001d6467c9e34af59e44a840f9`, eval script SHA-256 `a752d2d3520db71513c263dd476e8da457395a447a346f6b5c18782dc0faf034`, test patch SHA-256 `e16f06b260b5169a49397e9d571b5af70317cd23792e1437232fabf718fe8871`, and test-selection digest `392faac305a1d73591353568a1b2004c177f0a6fdc2f26339634717fd1444c4d`; the [native stage-zero record](2026-09-27-swebench-flask-5014-stage-zero.md) documents its independent oracle.
- Source platform manifest `docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4`; actual Axern-imported runtime `index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:98b8b97b38b834eb5a9dad6a42a0380278a911afc74c7025b893ea79294a7da3`. The canonical image-import receipt digest was `60b267c2b18acd5c6e9c3488d84724dcfa2a19081df84e5b4a71f08d8e0d7a49`. Source and runtime are distinct immutable identities, not interchangeable names.
- The offline verifier wheelhouse retained `setuptools==70.0.0` (863,432 bytes, SHA-256 `54faa7f2e8d2d11bcd2c07bed282eef1046b5c080d1c32add737d7b5817b1ad4`) and `wheel==0.45.1` (72,494 bytes, SHA-256 `708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248`). Inference and verification both resolved to `deny_all` network policy; the verifier came from the installed wheel, not the checkout.

The admission receipt was `passed`, reason `no_locked_patch_signatures_reachable`, receipt SHA-256 `4ac457f955742eba7b5c746f29edc0a4381305dec07ec135334148c6d9f514c0`, scanner SHA-256 `31b062490ec5e4f0f7c5fdd0714f431d081bc94b6338be1e6a76392f08db024e`. Its 1,425-byte sealed audit was independently downloaded and verified at SHA-256 `d762a453fc575e3293cbd9f8fa13e9409799e36caea3b46e85ef684b9da695ef`. As in the earlier admission contract, a `passed` receipt attests only the locked signatures and scanner scope, not the absence of every possible unknown secret.

## Public Run identities, terminal state and diagnostics

| Role | Environment | Run | Allocation | Terminal |
| --- | --- | --- | --- | --- |
| Admission | `env-b2d82b75-7659-4cf5-b00e-b595c0768f0f` | `run-238c082b-ccab-4d7b-a82d-2d63e71e3b55` | `alloc-a1ff3af2-3966-4908-b896-8761662d6c79` | succeeded, exit 0 |
| Inference qualification | `env-2c6e159f-5456-45da-93f8-300ab5673e49` | `run-ea944cde-fe00-49e0-bbd5-0a308271b4b1` | `alloc-8b60c250-1856-43b0-af5d-dce006a57e7f` | succeeded, exit 0 |
| Verification qualification | `env-fb8d2ac0-41b4-43a0-80fb-0c744da89b4d` | `run-0d317ed8-4d9e-4ac8-ab91-52f69f77fbbe` | `alloc-d7b6f726-5f05-46a8-8a92-33361dab62a3` | succeeded, exit 0 |
| Static inference | `env-2c6e159f-5456-45da-93f8-300ab5673e49` | `run-7f2dbae2-6a49-439f-afe1-064e5171bc0d` | `alloc-71a3618c-ee8a-4a00-a641-7ad4d4e70f8f` | succeeded, exit 0 |
| Fresh verification | `env-fb8d2ac0-41b4-43a0-80fb-0c744da89b4d` | `run-579755b8-dc80-46b4-ab50-5e6014de069f` | `alloc-5cbc5372-ef4c-42f9-b3c1-6d4a390dd6b7` | succeeded, exit 0 |

The post-acceptance public Run list contained exactly these five Runs. No failure diagnostic was emitted in the public terminals; the Axrun execution record has empty diagnostic code/message and `inference_termination_reason=completed`. Public pre-start `network_bridge` and `runsc_ephemeral_storage_hard_limit` conditions were healthy/available; the latter reported runtime-specific enforcement verified before workload start. These observations establish this accepted path's terminal state, not that all possible startup races or enforcement-loss modes are absent.

## Sealed result, replay and cleanup

Each available sealed manifest entry was downloaded through the public SDK, then its bytes, SHA-256 and returned metadata were independently checked. The six sealed outputs were:

| Role / declared output | Bytes | SHA-256 |
| --- | ---: | --- |
| Admission `/outputs/flask-image-audit.json` | 1,425 | `d762a453fc575e3293cbd9f8fa13e9409799e36caea3b46e85ef684b9da695ef` |
| Inference qualification `/outputs/qualification.json` | 298 | `210cc207a47dd076db473a6d80c125c33572188730c5cb974e78306935506ce9` |
| Verification qualification `/outputs/qualification.json` | 300 | `d4380c46c4d6b7c3706bb53b385ca11367e22dcabcdec569928e00b6983ab0f9` |
| Inference `/outputs/candidate.patch` | 390 | `087d51d66413bfa35111ac0eca31f1db1636572702cfd967c428049b453f451d` |
| Verification `/outputs/verification.json` | 8,752 | `5149d14c433352477c304e69ea78df86c589b27dc6dda61df132919b84769306` |
| Verification `/outputs/verifier.log` | 18,857 | `1443f3aa140ea21c44bfea1b43c5d2f9140e408801a0eb79ff77fb9322057c38` |

The immutable CandidateBundle digest is `65ffd5caaa9ca1b3597ca5a80d39d1e070fce98c9b7c09d619cbdb0adbb91ef8`; the VerificationResult digest is `768176507bddaebf6b2a72c73e2db41046fcf671985e83c172215d60d6aa0faf`. The result links back to that candidate and the sealed verification output. The spec digest is `b33167af2844dd7f8fe5cf3c7c4bd23df64e762d9d6f280bdb77c590caf9fd02`, qualification-result digest `9a2e0c9a07b790ff70edee1d1923d8982aa2a9dd6c7a6f91fdf97eceb036ded2`, and final JSON report SHA-256 `51aa1a5662279449df61052715e3a9e24a2d3ecb3e49a8f3e1e7c004cc52a72f`. The verifier's complete 60-entry status map, category arrays and resolution matched the locked official gold grade exactly: 60 expected, 60 observed, 60 passed, 0 failed, 0 missing. No static trajectory was fabricated.

Completed `resume` left the persisted execution record bytes and the five public identities unchanged; `verify-record` succeeded. This checks completed-record replay, not a live disconnect or active model-session recovery scenario. After result verification, all five Runs were reconfirmed terminal, and data-plane reads for their Allocations returned `FAILED_PRECONDITION` because they were inactive. Only the three newly owned Environments were deleted, each after exact identity/image checks and each confirmed `NOT_FOUND`; a subsequent public Environment list was empty. Run and sealed evidence remained retained by Axern. Private input, log and artifact evidence is retained outside the source checkout; its final summary SHA-256 is `b2446e3ae4a0e2f2f120f2d789a9bbc00dce3c268f20c017a33a3604e940ceb6`.

## Axern #190 implication

[Axern #190](https://github.com/cofy-x/axern/issues/190) records the original v0.12.0 preactivation `CAPABILITY_ENFORCEMENT_LOST` failure and explicitly requested a new independent-wheel consumer acceptance after a platform correction. The released v0.12.1 correction and this fresh, five-Run CLI acceptance satisfy that requested **single-case consumer retest**: admission was no longer blocked, and the verifier reached an integrity-checked gold verdict without loosening deny-all policy, adding caller sleeps or treating a failed Run as success. The v0.12.0 failure remains valid historical evidence; this result does not itself prove exhaustive absence of startup races, certify all capability modes, or close the issue administratively. Platform regression coverage and issue closure remain Axern-owner decisions.
