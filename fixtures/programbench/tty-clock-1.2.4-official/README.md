# ProgramBench 1.2.4 official-instance lock

This directory pins the official `xorg62__tty-clock.f2f847c` contract used by Axrun's stage-zero
ProgramBench capability audit. It is one of the 200 benchmark instances, not the bundled
`testorg__` fixture.

The test metadata is included so the expected denominator and ignore decisions are immutable.
Hidden branch blobs are deliberately not vendored; `asset-lock.json` records their immutable
Hugging Face revision, sizes, and independently verified SHA-256 digests. The official cleanroom
image is identified by its `linux/amd64` platform manifest digest, never by the mutable v6 tag at
runtime.

This lock is not yet a runnable official verifier. ProgramBench 1.2.4 commits the
candidate-specific post-compile container and starts every branch from that committed state.
`axern-sdk==0.10.0` now exposes a successful Run's immutable rootfs result as a derived
Environment, and the live SDK validation proves fresh Runs do not share later mutations. Axrun
still fails closed until its benchmark-owned verifier orchestration and official evaluator parity
are implemented.
