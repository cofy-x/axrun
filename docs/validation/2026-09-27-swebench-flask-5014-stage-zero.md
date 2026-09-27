# SWE-bench Verified Flask 5014 native stage-zero

Status: the pinned upstream TestSpec, eval script, and grader agree with the deterministic
gold and known-bad controls on native `linux/amd64`. This is **not** Axrun fresh-verifier
parity, a real Claude candidate, or general SWE-bench Verified support. Registration is
withheld until those separate checks pass.

## Locked inputs and execution

- Instance: `pallets__flask-5014` from `SWE-bench/SWE-bench_Verified`, dataset commit
  `78f471bf655a3137b2e8a75af1501690ec009ec3`.
- Parquet: 6,304,616 bytes, SHA-256
  `030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25`.
  The complete enriched row's canonical JSON SHA-256 is
  `36d5506b22ede57cf679dd50b44232dc640663dc9fa94f3dad5f9a06760a9c2e`.
- Official SWE-bench harness commit: `f7bbbb2ccdf479001d6467c9e34af59e44a840f9`;
  eval script SHA-256: `a752d2d3520db71513c263dd476e8da457395a447a346f6b5c18782dc0faf034`.
  The locally frozen scorer package list has SHA-256
  `de9c9901cf9f9c1b8227f33e509b5a25adad36322c3958d485ca00531b5d48e4`.
- Official cleanroom `linux/amd64` platform manifest:
  `docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:eaf597005c159361cb8ee26018fb3741b320f331065f0c95726d83ccf2f1fba4`.
  The image has a clean `/testbed` Git HEAD
  `966bb873e3a1e42d857362a17f5af2533dfd8f46`; the row's base commit
  `7ee9ceb71e868944a46e1ff00b506772a53a4f1d` exists but is **not** the image HEAD.
  A resolver must not silently equate those identities or reset the official image to the
  row base.
- Native host: `wayne-hk-dev`, `x86_64`; Axrun oracle commit
  `5d55f893eb9fa929ba8fcbeda73a4230625df7fd`. The released Axern CLI/local stack
  and public PyPI `axern-sdk` are all `0.11.4`.

The oracle runs the official patch-apply sequence, TestSpec eval script, and pinned
official grader, but does **not** invoke upstream `run_instance`. Docker uses the exact
platform digest, `--network none`, and bounded CPU/memory/PIDs. The official editable
install command succeeds offline only after a readonly two-file wheelhouse is supplied:
`setuptools==70.0.0` (863,432 bytes, SHA-256
`54faa7f2e8d2d11bcd2c07bed282eef1046b5c080d1c32add737d7b5817b1ad4`)
and `wheel==0.45.1` (72,494 bytes, SHA-256
`708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248`).
`PIP_NO_INDEX=1` and the fixed `PIP_FIND_LINKS` prohibit container-side downloads.
This environmental deviation from upstream `run_instance` is explicit, not silently
described as official harness identity.

## Deterministic upstream-oracle results

| Submission | Official classification | Fail-to-pass | Pass-to-pass | Expected/observed | Resolved |
| --- | --- | ---: | ---: | ---: | --- |
| Official gold patch, SHA-256 `087d51d66413bfa35111ac0eca31f1db1636572702cfd967c428049b453f451d` | test completed | 1/1 | 59/59 | 60/60 | yes |
| Unrelated nonempty known-bad patch, SHA-256 `174037c0c2018173a2fe413b5b8ec30bd4900365b488588fcec3243f433b8114` | test completed | 0/1 | 59/59 | 60/60 | no |
| Empty patch | `empty_patch_instances` | — | — | no test statuses | unscored |

The empty control is not a 0/60 test result. Both test containers were removed.
The final private receipt has SHA-256
`e16e32a970bf18028ca37f186440d1c064203525f909ad034d8a16c59c18856c`;
complete logs, official per-test JSON, and the enriched row remain in the private managed
HK evidence directory. No model credential was needed or used.

## Published Axern image identities prepared for the next step

The release CLI imported the official task image from the exact platform manifest and
returned runtime `immutable_ref`
`index.docker.io/swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:98b8b97b38b834eb5a9dad6a42a0380278a911afc74c7025b893ea79294a7da3`.
The source platform digest and Axern's imported runtime digest are distinct and both must
remain visible in the acceptance record.

The existing self-contained Claude rootfs was built on the same native host. Its local image
ID is `sha256:aec400caa69c56f3fa57ccaaac097ecb363ddf8d9abf496f1fa7ef8d0df074ca`;
the release CLI returned `immutable_ref`
`index.docker.io/library/axrun-claude-code-rootfs@sha256:df44581291434e694b4f9f054be19df394653d0e1fc5c1e893ed754cbe3fb13b`.
The independent readonly bind-mount check verified Claude Code 2.1.205, Node 22.23.2,
and mount-rooted PT_INTERP `/__claude_code/l`. Neither imported image is yet an Axrun
candidate or verifier result.

Next acceptance boundary: use the public SDK and the imported immutable task image to
obtain separate inference and verification Environments, preserve the official clean image
HEAD, compare complete sealed Axrun per-test output against the pinned upstream oracle,
then run real Claude only after deterministic parity. Until then, no official-instance
support claim is made.
