# Claude Code 2.1.205 rootfs mount

This directory is Axrun's self-contained build source for the read-only Claude Code rootfs mounted at `/__claude_code`. It does not depend on another checkout and it is not a task image: the task image still owns Git, shells, language toolchains, tests, and the writable workspace.

The runtime is fixed to Claude Code `2.1.205`, runtime identity `2.1.205-20260812-234142`, and Node.js `22.23.2`. One Dockerfile builds `linux/amd64` and `linux/arm64` with a closed `TARGETARCH` mapping; any other architecture fails. The Ubuntu base image, common Claude package, platform-native Claude package, and Node archive are checksum-pinned. The amd64 build remains the benchmark and production canonical platform. The arm64 build exists for local development and E2E against an arm64 Axern source Compose node.

The build definition is split by responsibility:

- `artifacts.lock.json` is the machine-readable supply-chain lock. It owns the exact versions, per-platform artifacts, SHA-256 values, loader paths, and architecture aliases.
- `Dockerfile` exposes the stable ABI and version defaults and orchestrates the build stages. Its version arguments must match the lock; a mismatch fails the build.
- `scripts/` contains checked-in, independently reviewable fetch, ELF patching, validation, manifest, and runtime-launcher logic. Docker uses explicit `COPY`; it does not fetch build logic with `ADD` or generated heredocs.

Update the lock and the corresponding visible Dockerfile defaults together when intentionally changing a runtime version or base image. Keep platform selection in the closed lock mapping rather than adding architecture conditionals throughout the Dockerfile.

The rootfs carries its own Node, glibc loader, libraries, CA bundle, and native helpers. Claude's Bun executable has its `PT_INTERP` value replaced in place without changing the file length. Other dynamic executables receive a mount-rooted interpreter and RPATH. The launcher removes `LD_LIBRARY_PATH`; consumers must not set global loader paths, use `chroot`, or depend on task-image libc.

Build and load a local platform-specific image through the maintained wrapper:

```bash
./docker/claude-code-rootfs/build-local.sh amd64
./docker/claude-code-rootfs/build-local.sh arm64
```

Official public origins are the default. When they are slow, `--mirror` explicitly selects npmmirror as transport; the downloaded Node and Claude artifacts must still match their platform-specific pinned SHA-256 values:

```bash
./docker/claude-code-rootfs/build-local.sh amd64 --mirror
./docker/claude-code-rootfs/build-local.sh arm64 --mirror
```

The emitted tags are `axrun-claude-code-rootfs:2.1.205-amd64` and `axrun-claude-code-rootfs:2.1.205-arm64`. The script can be invoked from any working directory and rejects unknown architectures or options.

Run the static source verification before a build:

```bash
./docker/claude-code-rootfs/verify-source.sh
```

After a local build, run the image-level truth-path. It exports the selected image, mounts that rootfs read-only at `/__claude_code` in an independent container, and checks the manifest, Claude and Node versions, ELF machine, `PT_INTERP`, read-only behavior, and absence of a configured `LD_LIBRARY_PATH`:

```bash
./docker/claude-code-rootfs/verify-image.sh amd64
./docker/claude-code-rootfs/verify-image.sh arm64
```

After publishing, resolve and record the registry's returned manifest digest. Runtime configuration must use an `image@sha256:...` reference. This repository intentionally contains no registry, region, credential, or claimed output digest; rebuilding does not inherit the digest of a previous image built elsewhere.

Linux acceptance must select a rootfs digest matching the task Environment platform, mount it read-only at `/__claude_code`, execute `/__claude_code/usr/local/bin/claude --version`, validate `/__claude_code/opt/claude-code/manifest.json`, and run a real tool call in the task image. Both variants expose exactly the same mount ABI and use a mount-rooted `PT_INTERP`; neither depends on task-image libc. A source test does not replace this ABI truth path.
