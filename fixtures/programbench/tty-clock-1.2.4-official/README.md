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

ProgramBench's official evaluator installs `pytest-rerunfailures` from an unpinned network source
after compilation. This fixture closes that reproducibility gap by locking the 16.7 wheel and its
SHA-256, installing it offline, and materializing the official default of 10 CPUs/xdist workers.
Those values are evaluator assets and contract inputs, not caller-selectable tuning knobs.
