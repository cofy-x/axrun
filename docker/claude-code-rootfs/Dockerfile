ARG UBUNTU_BASE_IMAGE=ubuntu:24.04@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea

FROM ${UBUNTU_BASE_IMAGE} AS builder

ARG CLAUDE_CODE_VERSION=2.1.205
ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142
ARG NODE_VERSION=22.23.2
ARG UBUNTU_BASE_IMAGE
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      binutils \
      ca-certificates \
      curl \
      file \
      jq \
      libgcc-s1 \
      libstdc++6 \
      patchelf \
      python3 \
      xz-utils \
 && rm -rf /var/lib/apt/lists/*

COPY artifacts.lock.json /opt/axrun-build/artifacts.lock.json
COPY scripts/resolve-architecture.py /opt/axrun-build/scripts/resolve-architecture.py

RUN python3 /opt/axrun-build/scripts/resolve-architecture.py \
      /opt/axrun-build/artifacts.lock.json "$TARGETARCH" /tmp/architecture.env \
      --ubuntu-base-image "$UBUNTU_BASE_IMAGE" \
      --claude-code-version "$CLAUDE_CODE_VERSION" \
      --claude-runtime-version "$CLAUDE_RUNTIME_VERSION" \
      --node-version "$NODE_VERSION"

ARG NODE_DIST_BASE_URL=https://nodejs.org/dist
ARG NPM_REGISTRY_URL=https://registry.npmjs.org

ENV PATH=/opt/claude-code/node/bin:${PATH}

COPY scripts/fetch-artifacts.sh /opt/axrun-build/scripts/fetch-artifacts.sh
RUN NODE_DIST_BASE_URL="$NODE_DIST_BASE_URL" NPM_REGISTRY_URL="$NPM_REGISTRY_URL" \
      /bin/bash /opt/axrun-build/scripts/fetch-artifacts.sh

COPY scripts/patch-bun-interp.py /opt/axrun-build/scripts/patch-bun-interp.py
COPY scripts/patch-loader.py /opt/axrun-build/scripts/patch-loader.py
COPY scripts/prepare-loader.sh /opt/axrun-build/scripts/prepare-loader.sh
COPY scripts/patch-elfs.sh /opt/axrun-build/scripts/patch-elfs.sh
RUN /bin/bash /opt/axrun-build/scripts/prepare-loader.sh
RUN /bin/bash /opt/axrun-build/scripts/patch-elfs.sh

COPY scripts/verify-builder.sh /opt/axrun-build/scripts/verify-builder.sh
COPY scripts/write-manifest.sh /opt/axrun-build/scripts/write-manifest.sh
RUN /bin/bash /opt/axrun-build/scripts/verify-builder.sh
RUN UBUNTU_BASE_IMAGE="$UBUNTU_BASE_IMAGE" \
      /bin/bash /opt/axrun-build/scripts/write-manifest.sh

FROM ${UBUNTU_BASE_IMAGE}

ARG CLAUDE_CODE_VERSION=2.1.205
ARG CLAUDE_RUNTIME_VERSION=2.1.205-20260812-234142
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libgcc-s1 libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/claude-code /opt/claude-code
COPY --from=builder /tmp/claude-loader /l
COPY --from=builder /tmp/architecture.env /tmp/architecture.env
COPY scripts/claude-launcher.sh /usr/local/bin/claude

RUN set -eu; \
    build_target_arch="$TARGETARCH"; \
    . /tmp/architecture.env; \
    test "$TARGETARCH" = "$build_target_arch"; \
    chmod 0755 /usr/local/bin/claude /l; \
    ln -s "lib/$DEB_LIB_ARCH" "/$LIB_ALIAS"; \
    ln -s "usr/lib/$DEB_LIB_ARCH" "/$USR_ALIAS"; \
    rm /tmp/architecture.env

LABEL io.axrun.claude-code.version="$CLAUDE_CODE_VERSION" \
      io.axrun.claude-runtime.version="$CLAUDE_RUNTIME_VERSION" \
      io.axrun.claude-code.mount-target="/__claude_code" \
      io.axrun.claude-code.entry="/__claude_code/usr/local/bin/claude" \
      io.axrun.claude-code.rootfs="ubuntu-24.04"
