FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84

ARG TARGETARCH
ARG DEBIAN_MIRROR=https://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=https://deb.debian.org/debian-security

RUN set -eux; \
    case "$TARGETARCH" in amd64|arm64) ;; *) exit 2 ;; esac; \
    case "$DEBIAN_MIRROR" in https://*|http://*) ;; *) exit 2 ;; esac; \
    case "$DEBIAN_SECURITY_MIRROR" in https://*|http://*) ;; *) exit 2 ;; esac; \
    sed -i \
      -e "s|https\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR%/}|g" \
      -e "s|https\?://deb.debian.org/debian|${DEBIAN_MIRROR%/}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends git ca-certificates; \
    rm -rf /var/lib/apt/lists/*

COPY repository/ /workspace/

RUN set -eux; \
    cd /workspace; \
    git init -q; \
    git add -A -- .; \
    GIT_AUTHOR_NAME='Axrun Synthetic' \
    GIT_AUTHOR_EMAIL='synthetic@axrun.invalid' \
    GIT_COMMITTER_NAME='Axrun Synthetic' \
    GIT_COMMITTER_EMAIL='synthetic@axrun.invalid' \
    GIT_AUTHOR_DATE='2000-01-01T00:00:00+00:00' \
    GIT_COMMITTER_DATE='2000-01-01T00:00:00+00:00' \
      git commit -q -m 'synthetic base'; \
    test "$(git rev-parse HEAD)" = 60dd887fd78561f03d8ca215e97de77048e93627

WORKDIR /workspace
