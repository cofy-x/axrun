ARG TARGETARCH
ARG UBUNTU_ARM64_IMAGE="ubuntu:22.04@sha256:1cc7bb38a74c0e126716646e47c0b3c5c139547d386d5ff7a64cf3ea316ca523"
FROM ${UBUNTU_ARM64_IMAGE}

ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    PATH=/opt/miniconda3/envs/testbed/bin:/opt/miniconda3/bin:${PATH} \
    TZ=Etc/UTC

RUN test "${TARGETARCH}" = arm64 || { echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 64; }

ARG APT_MIRROR="http://ports.ubuntu.com/ubuntu-ports"
RUN sed -i "s|http://ports.ubuntu.com/ubuntu-ports|${APT_MIRROR}|g" /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        jq \
        libffi-dev \
        libjpeg-dev \
        libmemcached-dev \
        libtiff-dev \
        locales \
        python3 \
        tzdata \
        wget \
        zlib1g-dev \
    && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*

ARG MINICONDA_BASE_URL="https://repo.anaconda.com/miniconda"
ARG MINICONDA_ARTIFACT="Miniconda3-py311_23.11.0-2-Linux-aarch64.sh"
ARG MINICONDA_SHA256="decd447fb99dbd0fc5004481ec9bf8c04f9ba28b35a9292afe49ecefe400237f"
RUN curl --fail --location --retry 3 \
        "${MINICONDA_BASE_URL}/${MINICONDA_ARTIFACT}" \
        --output /tmp/miniconda.sh \
    && echo "${MINICONDA_SHA256}  /tmp/miniconda.sh" | sha256sum --check --strict \
    && bash /tmp/miniconda.sh -b -p /opt/miniconda3 \
    && rm /tmp/miniconda.sh \
    && conda config --system --prepend channels conda-forge \
    && conda config --system --set channel_priority strict

COPY environment-arm64.yml /opt/axrun/environment-arm64.yml
COPY environment-arm64.lock /opt/axrun/environment-arm64.lock
COPY requirements-case.txt /opt/axrun/requirements-case.txt
ARG CONDAFORGE_CHANNEL_URL="https://conda.anaconda.org/conda-forge"
RUN sed -i "s|__CONDAFORGE_CHANNEL_URL__|${CONDAFORGE_CHANNEL_URL}|" \
        /opt/axrun/environment-arm64.lock \
    && conda create --name testbed --file /opt/axrun/environment-arm64.lock \
    && /opt/miniconda3/envs/testbed/bin/python -m pip install \
        --require-hashes \
        --only-binary=:all: \
        --requirement /opt/axrun/requirements-case.txt \
    && conda clean --all --yes

COPY testbed-source/ /testbed/
COPY setup-repository.sh /opt/axrun/setup-repository.sh
ARG DJANGO_BASE_COMMIT="7fa1a93c6c8109010a6ff3f604fda83b604e0e97"
RUN DJANGO_BASE_COMMIT="${DJANGO_BASE_COMMIT}" \
    /opt/axrun/setup-repository.sh

WORKDIR /testbed

LABEL org.opencontainers.image.title="Axrun SWE-bench Verified django__django-12419 arm64 seed" \
      org.opencontainers.image.description="Local-development arm64 variant; official benchmark acceptance remains amd64" \
      io.axrun.dataset="SWE-bench/SWE-bench_Verified" \
      io.axrun.instance-id="django__django-12419" \
      io.axrun.platform-role="local-development" \
      io.axrun.repo="django/django" \
      io.axrun.base-commit="7fa1a93c6c8109010a6ff3f604fda83b604e0e97"

CMD ["/bin/bash"]
