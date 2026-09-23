# Synthetic greenfield task v1

This fixture proves that Axrun is not a Git-patch-only runner. The inference image starts with an empty `/workspace` and does not require Git. A harness creates a complete project, `workspace-archive@1` is the only stage bridge, and a fresh Allocation rooted in the distinct verification Environment performs offline grading.

`Dockerfile.inference` and `Dockerfile.verification` both support `linux/amd64` and `linux/arm64`. Production and benchmark acceptance remain canonical on amd64; arm64 is for local Axern source-cluster development. Build and import each image separately, then resolve the episode with the exact canonical digest returned by Axern. Mutable local tags are build handles, not runtime identities.

The hidden verifier is delivered as an Axrun-owned verification input. It is absent from the inference image and candidate archive. The `gold`, `empty`, and `known-bad` directories are deterministic model-free candidate producers used to exercise passed and valid failed verdicts; they are not task inputs visible to a real model.
