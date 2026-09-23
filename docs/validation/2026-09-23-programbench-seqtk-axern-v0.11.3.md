# ProgramBench seqtk acceptance on released Axern v0.11.3

Status: passed. This is the first bounded, repeated ProgramBench vertical accepted against a
released Axern stack. It is one locked instance, not general ProgramBench or leaderboard support.
It does not resolve the tty-clock partial-result discrepancy tracked by cofy-x/axrun#3.

## Released identities and fixed inputs

- Axern release: `v0.11.3`, release commit
  `a1783d2f6a4248de11ecaf6244979350e2f204de`. Release workflow `35814971693` and the
  independent Homebrew workflow `35816057330` were both freshly observed successful.
- Released SDK: `axern-sdk==0.11.3`. An isolated install resolved only its declared grpcio,
  protobuf and PyYAML dependencies. Axrun's lock uses wheel SHA-256
  `db236554c1cb02f197dd9fc4f7b9f5fe319a059d611730f960283bc919673238`.
- Axrun executed commit: `3e59a9490fb8162bfc50a668ff6c04d48c1b2206`.
- Host/runtime: `wayne-hk-kvm`, native `linux/amd64`; released CLI and stack both reported
  `0.11.3` and every service healthy.
- Released node image: `ghcr.io/cofy-x/axern/node-all-in-one@sha256:11d076234e59bceb0da1e46cbcf00c4d39b147e6be3c4147ad1a891df5a2b1c1`.
- ProgramBench: package `1.2.4`, git
  `963063c9271cc40fa179977356782ea4582e0b0c`; instance `lh3__seqtk.94e7070`;
  upstream source commit `94e707082d39b0a038f234df676e32d9802c0dc7`.
- Official task image: `linux/amd64`
  `sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0`;
  config `sha256:742ff17f7c2fb045550e0545750ba44c698a9801bfffe0cdb13c9ad9610801ac`.
- Axrun evaluator image, imported with the released public CLI:
  `index.docker.io/axrun/seqtk-evaluator@sha256:f777ae80f074fbe841afebb3d66e7d0753b8442455e4fb94a714bfc069e9f61b`.
- Test revision: `de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5`; branch blobs
  `e592c32aec70` = 107995 bytes / `3a9ba4e29bf1eed9cc80b8c8eab537af092fc0b559f8f05eac326b8f5a7943a0`,
  `5d974fdda794` = 73593 bytes / `b908e8eda5bdbb72b338c20a80ec7f18a086a92ee4f5e34a56b72303cb650d11`.
- Denominator: 2 active branches, 429 active tests, 11 ignored tests, no ignored branch.
- Evaluator contract: `programbench-1.2.4-axrun-seqtk-v1`; dependency lock
  `9b14aaddb4cd53fe338a8bf4391b0eed12ea264c49a4c47e7b774d54735f4777`.

The reference-build is the locked upstream source plus the disclosed build wrapper; it is not an
official ProgramBench gold. The partial archive is the unchanged published candidate (6630 bytes,
SHA-256 `e13533d16886d84814f3fe45975c8d255a7333f17028ca606da1e011e231cdaa`).
Compile-failure is separately labeled synthetic input. The prior native evidence remains at
`/data/forge-artifacts/seqtk-native.0398np4n`.

## Declared execution and parity

Before execution, the released-stack matrix was fixed at two repetitions each for reference-build,
public partial and compile-failure. All six episodes and complete per-test mappings were retained;
there was no best-of selection, outer retry, changed timeout, changed test, or changed denominator.

| Input | Native Linux repeats | Released Axern repeats | Executable SHA-256 |
| --- | --- | --- | --- |
| reference-build | twice: 429 passed, 0 failed/not-run, score 1 | twice: identical 429/0/0 and every test status identical | `348c6e08241681487a4031afd1c34c6970409209adaed9e8a04330be0c0b1e7b` |
| public partial | twice: 173 passed, 256 failed, 0 not-run, score 0.40326340326340326 | twice: identical counts, score and all 429 test statuses | `09fb0650707f0e9b10c91252a18c0f1b4a8d5f513eeb69dc7041c5b070a4eab0` |
| synthetic compile-failure | twice: build script exits 42; no tests | twice: compile Run FAILED with adapter code 23 (`compile_failed`), 429 not-run, score 0; no branch Run or derived Environment | none |

Successful compile Runs terminated before Axrun separately waited for a READY rootfs result. Each
result produced an immutable derived Environment, and each official branch used a distinct fresh
Run and Allocation. Candidate failures stayed structured benchmark results; no infrastructure error
was converted into a score.

## Public Run evidence

Shared inference Environment: `env-82613a6c-c171-4dd8-8566-0376443d72fc`. Shared verification
Environment: `env-96a59ea3-5f7c-4315-9192-d0bb6d038d5f`.

| Episode | Inference Run / Allocation | Compile Run / Allocation | Rootfs result / derived Environment | Branch Runs / Allocations |
| --- | --- | --- | --- | --- |
| reference-build-1 | `run-bd7ff0e6-205e-4160-bbb6-7fbb24a649e7` / `alloc-0eba7241-ac20-446a-a678-69cf6794ce1a` | `run-08277dd0-9c9f-4f77-a12d-e36dc0c43810` / `alloc-d5f3c1a3-c868-4c49-9350-84965f6ff334` | READY `sha256:9beeef2a5ce37647ab2e9a7c081705d97406cf4143bacff3b6819b2fe98dfc6c` / `env-28be9e65-c136-548b-9077-5119204b7970` | `run-6b0ffc1b-e7fa-487b-b758-1e16ad2c5bc1` / `alloc-c3a9bffd-c8ca-480e-9f2d-3f3225ff5d26`; `run-3b4ce562-89b0-4b2a-a63f-24e7d735b846` / `alloc-993b0a78-2123-4063-b739-3cd48a7c4a2c` |
| partial-1 | `run-2379ed91-2581-4cb6-8f5f-9aa0a00abd6b` / `alloc-1de6aeab-f0bc-470d-8515-c3ce21e78b34` | `run-1c7b0087-181d-4f81-ba64-4afc1f5609fe` / `alloc-f8e52fb6-1ac5-4c94-b9fb-49cbaca4c156` | READY `sha256:ea35d537e937a09e63f1b4764f55cb3fbdb0e68648346da4171b4ac9d490cdfc` / `env-7571f456-993b-5a0e-9ff8-9ab39007feca` | `run-7c778835-c22a-4642-95ed-c520099853f3` / `alloc-488babe0-4c94-4595-a5f4-9d309e29e60f`; `run-68d41eeb-62b5-4604-b1c2-e437960b5afe` / `alloc-4bf36e6a-e5d3-4439-8929-dbe3c94a440c` |
| compile-failure-1 | `run-524e2242-6b6d-4e30-b75f-225af5478d30` / `alloc-00926834-244f-4ed4-b17e-cf0617fba81c` | `run-c0acd024-712e-4159-8a4d-561763a7d23f` / `alloc-c16b810f-fd78-42ad-b856-d488b0e3a015` | FAILED `workload did not succeed`; no derived Environment | none |
| reference-build-2 | `run-f77e8e0e-4002-403f-b6c5-012ac91e9778` / `alloc-b1c7a561-adf7-4dd6-8bc8-db8b816f7abb` | `run-bb5e2bbf-0655-4ab7-abca-9c756b9eeb1a` / `alloc-cd005c6b-b13c-48aa-adbc-eb4169a045d9` | READY `sha256:df14cb77ac62d9fd4eb1a3ed3a26b6cd52cea39a2fa5c8ad52167fbfec4079db` / `env-acddd6bd-d554-58d0-a120-ce32cbcce878` | `run-28259d36-2eb3-4372-891d-f03a0673dca1` / `alloc-733f0212-feba-436d-95aa-318ddfa3fab1`; `run-e5101884-1747-4740-9ef1-c8e077f3d360` / `alloc-80bc9ce3-12f7-4447-9c4a-90c38786ab93` |
| partial-2 | `run-179c9d6c-7847-42db-b70d-1c8269d30e10` / `alloc-57971571-6cd7-4e33-98c9-dae0272516ba` | `run-98734615-d016-4eae-8b8e-ce376326bafc` / `alloc-dcf6eb1e-1df5-475d-b81b-d685de62b084` | READY `sha256:8768c58cb63d0d10ab73c761ba827834673be170352838255af83a716a266e3e` / `env-2219a9d0-44cd-54f1-9820-08f1b8fa26ec` | `run-19b689ab-32b5-4f57-8d66-f87a5b9dd36e` / `alloc-19a08f7e-1306-4dac-833a-407337655848`; `run-064f8fb8-a626-485f-9b36-f1a067fb56c4` / `alloc-691d2cb2-ec72-4054-862e-9c9c98334493` |
| compile-failure-2 | `run-fa59d94b-e54f-4be3-be44-dba41c05c2b9` / `alloc-b9e4f1fb-394e-49e8-a8ec-40ef096567d7` | `run-53b23a6c-69bd-4e2a-820a-f85edcc1718a` / `alloc-105ce9a8-c1f3-4448-945e-bc0e23295bee` | FAILED `workload did not succeed`; no derived Environment | none |

CandidateBundle / VerificationResult digests, in table order:

1. `c6dad0d37dcd6ae9ad8787f68d4ea634589a7ec1ec6dc179e9f420823ace5bf4` /
   `756b38c711f5f0dbe68118601a9c9ceac2cdfdfd42d84605b57fa6d2b9eb41ad`
2. `e2af68950e45ac4c8c6961f16728f4d013b1fbce4351a5ef56ee3c08a1849f13` /
   `150c452fe1c93deea99c78f4e8e927eee9a7553b57300440b4c8713dfbdef6ec`
3. `9e5401100c98d6d571de9713b038bb11f86a20ef6beebbd1fae53d93eff00469` /
   `94d745870ad9b0376848f12edeba14d5d42855fd77f875d6a2263148414e17d8`
4. `ce1f7994dff9a190d78b4996873975a274e2b84e2da6a3171b7fe489a8e891d9` /
   `1e4c66f6e96a850cb634cb995b3b2c8b5b033629b07768a8b033e811afc8785d`
5. `e06093e97139082c32701b27c39ee7cc8440476e554b57430afa52e71ab9584d` /
   `85d5b4baca73b9d15ee7a6d60324abeab7a385e9983629a300afc8495fe4eeee`
6. `d93926ec248184971091f7cc17b8f2c574642c324346ddffb221a14a11662442` /
   `fe12067e2fa9265208d4563912ea6407402332f9ceca9ad6e20e1668fd5d9645`

The reference rootfs was rebound once for explicit isolation proof. `run-265134e5-fe07-4cc3-8e48-4fc5e271a0ce`
/ `alloc-7db7600d-49d5-4257-8334-cbd6d059cb05` wrote a marker; fresh
`run-260efb09-be4b-486e-96d1-9264cdaa7a2c` /
`alloc-246c8a6f-524a-4c79-9f04-0babeb14d2ed` could not observe it. Both succeeded.

Evidence directory: `/data/forge-artifacts/seqtk-v0113.U1NLUppz`. It contains every test map,
comparison, execution record, public Run message and cleanup receipt. Final public inventory:
34 terminal Runs, zero active Runs, zero Environments. All four successful derived Environments,
the isolation binding, and the two shared base Environments were deleted. Cleanup errors: zero.

## Failure-boundary review and corrections

Axrun now waits for workload terminal state, then independently waits for the rootfs result, and only
then downloads the rootfs workload outputs. A missing/corrupt sealed evaluator result is an
infrastructure failure and the already-created derived Environment is deleted. Malformed compile or
branch JSON is also an infrastructure failure with completed cleanup. Candidate compile/test failure
remains a legal benchmark result. Unit coverage includes execute and recovery paths.

The first validation-tool attempt, `/data/forge-artifacts/seqtk-v0113.upRqQ9Tb`, stopped before any
Run because the public SDK normalized `docker.io` to `index.docker.io` in the resolved Environment
identity. Both created Environments were cleaned. The tool was corrected to use the SDK-returned
canonical identity while retaining the exact platform digest; no assertion, timeout or benchmark
input changed.

No credential was required. A sensitive-pattern scan of the committed diff and acceptance records
found no credential or token. Axrun used no Axern source checkout, private Proto, Node target or
runtime identity. The older v0.11.2 local state was stopped and moved intact to
`/data/forge-artifacts/.preserved/axern-local-v0.11.2-20260923T123500Z`; it was not reset or deleted.

## Reproduction

After installing and starting released Axern v0.11.3 and importing the evaluator image, run:

```bash
uv run python tools/validation/programbench_seqtk_axern.py \
  --repo /data/forge-workspace/axrun \
  --native-evidence /data/forge-artifacts/seqtk-native.0398np4n \
  --context-file /data/forge-workspace/.forge/local/hosts/wayne-hk-kvm/axern/config.json \
  --context local \
  --runtime-image docker.io/programbench/lh3_1776_seqtk.94e7070@sha256:9d5dc381fd8b30ed1c8c94af8066646aca736ba53ab90da90af29825c6c6c4d0 \
  --verification-image index.docker.io/axrun/seqtk-evaluator@sha256:f777ae80f074fbe841afebb3d66e7d0753b8442455e4fb94a714bfc069e9f61b \
  --output /data/forge-artifacts/seqtk-v0113.NEW \
  --repetitions 2
```

This acceptance found no reproducible general Axern v0.11.3 platform defect. The repeated
`capability_reconcile` fail-stop warnings observed while the first cold image was still preparing did
not terminate or alter the persisted Run; it subsequently succeeded and all formal results matched.
That log alone is insufficient evidence for an Axern issue.
