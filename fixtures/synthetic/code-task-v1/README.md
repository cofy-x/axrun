# Synthetic code-task image

This directory is one complete `axrun.synthetic.code-task@1` fixture. Its task seed is the OCI image built by the adjacent `Dockerfile`; Axrun does not reconstruct `/workspace` by uploading dataset files at Run time.

The image owns:

- Python 3 and Git;
- the repository at `/workspace`;
- the clean base commit declared by `row.json`.

Build the task image for the target Axern node. The mirror arguments are optional build-time transport choices and are not embedded as private infrastructure defaults:

```bash
docker buildx build --platform linux/amd64 --load \
  -t axrun-synthetic-code-task:1 \
  fixtures/synthetic/code-task-v1
```

For a CLI-managed local Axern node, import it with `axern local image load axrun-synthetic-code-task:1`. During joint development against Axern's source-managed Compose stack, use that checkout's source import path instead:

```bash
IMAGE=axrun-synthetic-code-task:1 make -C /path/to/axern local-compose-image-import
```

Create the Axern Environment from the canonical digest returned by the import, not from an unpinned mutable tag.

The Dockerfile supports `linux/amd64` and `linux/arm64`; publish a multi-platform index or import the matching single-platform build. Both inference and verification Environments must be created from the imported or registry-resolved digest of this same image. Each stage still gets a fresh Run and Allocation. Claude Code is not installed in this task image; its independently built rootfs is attached read-only at `/__claude_code` only for the Claude inference Run.

The deterministic gold and known-bad paths run on either supported task-image platform. Claude Code `2.1.205` remains a separate mount with matching `linux/amd64` and `linux/arm64` rootfs variants. Production and benchmark acceptance use amd64; arm64 is available for local source-cluster development. The task image, Claude rootfs, and Axern node must use the same platform.
