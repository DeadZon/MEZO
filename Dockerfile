FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Required build tools (matches setup.sh dependencies + entrypoint needs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    sudo \
    git \
    curl \
    wget \
    unzip \
    zip \
    tar \
    xz-utils \
    p7zip-full \
    aria2 \
    zstd \
    brotli \
    bc \
    xmlstarlet \
    file \
    python3 \
    python3-pip \
    python-is-python3 \
    openjdk-17-jdk-headless \
    software-properties-common \
    ca-certificates \
    e2fsprogs \
    lz4 \
    && rm -rf /var/lib/apt/lists/*

# Optional packages (android sparse tools; may not be on all mirrors)
RUN apt-get update \
    ; apt-get install -y --no-install-recommends android-sdk-libsparse-utils fuse3 2>/dev/null \
    ; rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the full repository — container uses the exact commit that triggered the workflow
COPY . /app

# Install Python dependencies if present
RUN if [ -f /app/requirements.txt ]; then \
        pip3 install --no-cache-dir -r /app/requirements.txt; \
    fi

RUN chmod +x /app/docker-entrypoint.sh \
    && chmod +x /app/setup.sh /app/build.sh /app/packROM.sh 2>/dev/null || true

ENTRYPOINT ["/app/docker-entrypoint.sh"]
