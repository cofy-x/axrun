# Claude Code 2.1.205 rootfs mount

This directory is Axrun's self-contained build source for the read-only Claude Code rootfs mounted at `/__claude_code`. It does not depend on another checkout and it is not a task image: the task image still owns Git, shells, language toolchains, tests, and the writable workspace.

The initial runtime is fixed to Claude Code `2.1.205`, runtime identity `2.1.205-20260812-234142`, Node.js `22.23.2`, and `linux/amd64`. The Ubuntu base image and Node archive are digest-verified in the Dockerfile. `latest`, another architecture, and another binary/runtime version fail during the build.

The rootfs carries its own Node, glibc loader, libraries, CA bundle, and native helpers. Claude's Bun executable has its `PT_INTERP` value replaced in place without changing the file length. Other dynamic executables receive a mount-rooted interpreter and RPATH. The launcher removes `LD_LIBRARY_PATH`; consumers must not set global loader paths, use `chroot`, or depend on task-image libc.

Build locally with a disposable tag:

```bash
docker buildx build --platform linux/amd64 --load -t axrun-claude-code:2.1.205 docker/claude-code-rootfs
```

When the official origins are slow, an HTTPS mirror may transport the same fixed artifacts. The Node archive still must match its pinned SHA-256, and the installed Claude package version is verified:

```bash
docker buildx build --platform linux/amd64 --load \
  --build-arg NODE_DIST_BASE_URL=https://npmmirror.com/mirrors/node \
  --build-arg NPM_REGISTRY_URL=https://registry.npmmirror.com \
  -t axrun-claude-code:2.1.205 docker/claude-code-rootfs
```

Run the static source verification before a build:

```bash
./docker/claude-code-rootfs/verify-source.sh
```

After publishing, resolve and record the registry's returned manifest digest. Runtime configuration must use an `image@sha256:...` reference. This repository intentionally contains no registry, region, credential, or claimed output digest; rebuilding does not inherit the digest of a previous image built elsewhere.

Linux acceptance must mount the image read-only at `/__claude_code`, execute `/__claude_code/usr/local/bin/claude --version`, validate `/__claude_code/opt/claude-code/manifest.json`, and run a real Bash tool call in an Ubuntu 24.04 task image. A macOS Dockerfile parse or source test does not replace that ABI truth path.
