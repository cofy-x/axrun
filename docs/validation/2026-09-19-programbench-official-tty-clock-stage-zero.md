# ProgramBench 1.2.4 tty-clock official-instance stage zero

Date: 2026-09-19

This record covers selection, immutable asset locking, cleanroom qualification, and the public
Axern SDK capability audit for one real ProgramBench instance. It does **not** claim an official
ProgramBench score, evaluator parity, or leaderboard support.

## Fixed sources

| Component | Identity |
| --- | --- |
| Axrun contract implementation | `489b72d86cb4b9ada1b35ef2743ed205e3e44368` |
| Axern source-cluster checkout | `0294033e870647e0dde5777b298d437c1d4bb5bc` (read-only reference only) |
| Released SDK | `axern-sdk==0.9.1` from Axrun's locked environment |
| ProgramBench | package `1.2.4`, git `963063c9271cc40fa179977356782ea4582e0b0c` |
| Openbench | `a666534e83d8a4615d1b5841fb1475d9ab5b64a9` (read-only protocol reference) |

Axrun did not import an Axern source Python package or private Proto. Neither Axern nor Openbench
was modified.

## Instance selection

The selected instance is `xorg62__tty-clock.f2f847c`, one of the 200 formal instances and not the
`testorg__` fixture:

- repository: `xorg62/tty-clock`;
- commit: `f2f847cf2cc2949c8a8b7779a778f366d3743474`;
- language: C;
- difficulty: easy;
- active branches: 6; ignored branches: 0;
- active expected tests: 281; ignored tests: 38.

Selection was based on all 200 task metadata records rather than the repository name. The two
smallest test-count candidates were not better verticals: `YS-L/flamelens` has 223 active tests
but is medium-difficulty Rust across eight branches, while `tomnomnom/gron` has 224 active tests
but no fixed difficulty and only one branch. tty-clock is the smallest metadata-labeled easy
instance, uses a small C/ncurses build, and its six branches exercise the isolation requirement.

The exact upstream `task.yaml` and `tests.json` are stored under
`fixtures/programbench/tty-clock-1.2.4-official/` with SHA-256:

- task metadata: `7b84b5c8042b33afed1597a92bd527a4163bb354a89f29a2f2d5e8b24676d36d`;
- tests metadata: `ec1760221921b7614f2c85215b8739203093c1faee45dad70ec6f9d55f8017d6`.

The resolver recalculates the six branch and 281/38 test denominator from the locked metadata and
rejects unknown fields, identity drift, digest drift, branch drift, or denominator drift.

## Official image and branch blobs

The mutable source tag is
`docker.io/programbench/xorg62_1776_tty-clock.f2f847c:task_cleanroom_v6`. Runtime identity is the
single-platform `linux/amd64` manifest:

`docker.io/programbench/xorg62_1776_tty-clock.f2f847c@sha256:7c070e64a44e0b7dc2a032acf02159da43a0a4993a154b5fd98c4ab997726272`

The local pull resolved to image/config ID
`sha256:d433c4a48704aee0b45a0f97b43f8bfee5a76bd4299bdeb1133b649e3e151820` and reported
`amd64/linux`. This is a platform manifest digest, not a mutable tag or manifest-list digest.

ProgramBench's Hugging Face `main` was resolved to immutable dataset revision
`de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5`. Every branch blob was downloaded and independently
checked:

| Branch | Bytes | SHA-256 |
| --- | ---: | --- |
| `89bbe1810fa3` | 12,261 | `b70f0d0f54d01410de343b14a27a8831b95512e77662c7c7ff74d13dbd5095b5` |
| `9951be903ea4` | 10,502 | `62727f9092aea5ec4b5cf23b8717da3768059cfbd4322927243ead31634ab882` |
| `b2bd72001100` | 9,763 | `bbea41ad480413a43db1e4423d7d3540264e322e3cc37dce87087182499c8a07` |
| `b48a2e05f04f` | 10,290 | `0480561b30d79061894a00886ce358c4c69be0b3af22d4321d7f583532e53347` |
| `dc1d19eea619` | 14,420 | `708404eb4dec87af386bef968f301d74fbedcaebe017e7ab964c451234415442` |
| `ed5c2b1ffc48` | 92,070 | `b98a5f5468f1ee1f75342a004123041cebebea5b356b4016582d0174086ccf79` |

Hidden blob contents are not vendored, placed in prompts, or retained in any episode or candidate.
Only their immutable revision, paths, sizes, and digests are committed.

## Cleanroom checks

An ordinary Docker smoke used the digest-pinned image with `--platform linux/amd64 --network none`:

- `uname -m` returned `x86_64`;
- `/workspace/executable` was a root-owned regular file with mode `0111` and size 31,936 bytes;
- the prepared workspace contained the reference executable and public project documentation;
- upstream source at the fixed commit built offline with `make BIN=executable`;
- the resulting executable SHA-256 was
  `02a20572293650b3337efd8e20e6ea9a0bc1be69cec0ca3e94954dc54b27fe3c`;
- dynamic dependencies resolved entirely inside the cleanroom image (`libncurses.so.6`,
  `libtinfo.so.6`, `libc.so.6`, and the amd64 loader).

This proves the selected task's build dependencies are present offline. The original source was
used only for selection qualification and is not included in Axrun's prompt, fixture, candidate,
or runtime assets.

## Official evaluator semantic audit

ProgramBench 1.2.4 performs the following candidate-specific sequence: wipe `/workspace`, extract
the submission, remove hash-matched artifacts and stale `./executable`, seed deterministic Git,
apply a DNS blackhole, run `compile.sh`, stash and hash the new executable, then `docker commit` the
complete compile container. Each branch starts a fresh container from that committed image, adds
one test blob, restores and verifies the executable, and produces JUnit results. Expected tests
missing from JUnit become `not_run`; ignored branches/tests are filtered from the official score.
The build-side DNS blackhole is not a complete deny-all network boundary, and official branch tests
may use network. A future adapter must model those policies separately rather than describe either
one as inference-style deny-all.

Axrun can faithfully model the pre-compile cleanup, stale executable deletion, offline compile
command, executable hashing, locked expected-test denominator, ignore rules, and structured
business/infrastructure result classes. It cannot preserve the decisive transition from the
complete post-compile state to fresh branch Allocations.

`axern-sdk==0.9.1` publicly exposes:

- Environment creation from an image/template;
- Run creation from an Environment;
- Allocation-scoped exec, file, and archive operations;
- declared sealed files/archives after a Run.

It exposes no Allocation snapshot/commit, no Environment creation from Allocation state, and no
Run creation from a snapshot. A `/workspace` archive is not equivalent: `compile.sh` runs as root
and may modify package state, toolchain caches, system paths, ownership, or other files outside
`/workspace`; the official evaluator itself installs build-time support before committing the
container. Sequential branches in one Allocation would also violate fresh-branch isolation.

Therefore:

| Required semantic | Stage-zero result |
| --- | --- |
| clean workspace, stale executable removal, offline compile | expressible |
| executable stash and SHA-256 verification | expressible within one Allocation |
| every branch from identical complete post-compile state | **blocked: no public snapshot boundary** |
| ignored branches/tests and missing expected tests as `not_run` | contract/data locked; verifier deferred |
| compile, branch, test, and infrastructure failure separation | contract can express; parity deferred |
| exact official score/resolved parity | blocked by branch-state gap |

No observed-tests ratio is emitted or described as an official score.

## Resolver and fail-closed behavior

`ProgramBenchOfficialSingleResolver` accepts only the fixed converted row schema and validates all
content-addressed local metadata. Its seed digest is
`6f5f2524daab1bf4686335bc0e686172cfe5fdf2fccc89868223d21c3c43f622`.
It emits the exact amd64 OCI digest for both stage bindings, requires different Environment IDs,
selects `workspace-archive@1` with only the seed-owned top-level `executable` excluded, and records
the missing public capability.

The resolver's task and verifier identities are intentionally absent from the executable catalog.
`axrun validate` accepts the canonical episode contract, while `axrun run` fails before creating an
Axern Run with:

`unsupported task adapter: programbench-official-single@1`

This prevents a caller from mistaking the asset lock for runnable official support.

## Minimal public-SDK reproducer

Run from the Axrun repository:

```bash
uv run python tools/reproducers/programbench_post_compile_snapshot.py
test $? -eq 2
```

The JSON report records SDK version `0.9.1`, public client/allocation method names, the relevant
`create_environment` and `create_run` state-source audit, `supported=false`, and stable missing
capability `post-compile-allocation-snapshot-v1`. It imports only `AllocationClient` and
`AxernClient` from the released public package. It does not inspect or call private Proto.

## Reproduction

```bash
uv run axrun resolve-programbench-official \
  fixtures/programbench/tty-clock-1.2.4-official/row.json \
  --episode-id programbench-tty-clock-stage-zero \
  --runtime-image docker.io/programbench/xorg62_1776_tty-clock.f2f847c@sha256:7c070e64a44e0b7dc2a032acf02159da43a0a4993a154b5fd98c4ab997726272 \
  --inference-environment INFERENCE_ENVIRONMENT_ID \
  --verification-environment DIFFERENT_VERIFICATION_ENVIRONMENT_ID \
  --output /tmp/programbench-tty-clock-stage-zero.json

uv run axrun validate /tmp/programbench-tty-clock-stage-zero.json
uv run axrun run /tmp/programbench-tty-clock-stage-zero.json
# expected fail-closed before any Run is created
```

There are no qualification, inference, verification Run/Allocation IDs, sealed candidate outputs,
CandidateBundle, TrajectoryBundle, VerificationResult, credential scan, or lifecycle cleanup result
for this stage: official execution was deliberately not started after the capability audit failed.
Gold/empty/partial parity and real Claude acceptance remain downstream of the single missing public
snapshot capability.
