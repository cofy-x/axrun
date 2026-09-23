# ProgramBench 1.2.4 official-instance lock

This directory pins the official `xorg62__tty-clock.f2f847c` contract used by Axrun's closed
ProgramBench single-instance vertical. It is one of the 200 benchmark instances, not the bundled
`testorg__` fixture.

The test metadata is included so the expected denominator and ignore decisions are immutable.
Hidden branch blobs are deliberately not vendored; `asset-lock.json` records their immutable
Hugging Face revision, sizes, and independently verified SHA-256 digests. The official cleanroom
image is identified by its `linux/amd64` platform manifest digest, never by the mutable v6 tag at
runtime.

The runnable verifier clears and safely extracts the candidate, removes the locked upstream
clean-hash set and stale executable, compiles offline, then asks Axern for a successful Run's
immutable rootfs result. Every active branch receives its locked blob in a fresh Run from that
same derived Environment. Result aggregation preserves ProgramBench 1.2.4's ignored-test,
missing-test, duplicate-test and scoring semantics. This remains a single-instance contract rather
than general ProgramBench or leaderboard support.

Build `Dockerfile.verification` with this directory as context before resolving episodes. It starts from the locked official base and installs `verifier/requirements.lock` with hashes. Supply the resulting published manifest reference through `--verification-image`; `--runtime-image` still identifies the official inference base. Record the build source, dependency lock and resulting digest. No static package installation is performed during compile or branch Runs, which retain deny-all networking.

The evaluator pins pytest 9.0.3, pytest-timeout 2.4.0, xdist 3.8.0, dependency 0.6.1, rerunfailures 16.7 and libtmux 0.58.0 plus their dependency closure. The default 10 CPUs/xdist workers and official test/scoring inputs are unchanged. This is contract v4; prior records cannot be resumed under a changed contract. New gold/partial parity is required before treating this evaluator image as accepted.
