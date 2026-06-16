# syntax=docker/dockerfile:1
# ── Production image for the SDD Semantic Pipeline (rootless Podman) ───────────
# A deployable runtime image for the `sdd-pipeline` batch CLI — distinct from the
# VS Code dev image in .devcontainer/Dockerfile. Multi-stage so the final layer
# carries only the venv + the pandoc binary (no apt/dpkg/build toolchain).
#
# Build (rootless Podman):
#   podman build -t sdd-pipeline:latest .
#   podman build --build-arg INSTALL_EXTRAS=azure,chroma -t sdd-pipeline:latest .
# Run (see scripts/podman.ps1 / scripts/podman.sh for the wrapped invocation):
#   podman run --rm --userns=keep-id:uid=1000,gid=1000 \
#     -v ./inbox:/app/inbox:Z -v ./outbox:/app/outbox:Z \
#     -v sdd-hf-cache:/app/.cache/huggingface --env-file .env \
#     sdd-pipeline:latest check

# ── Stage 1: builder — resolve every wheel into a self-contained venv ──────────
FROM python:3.11-slim-bookworm AS builder

# azure (default — Azure OpenAI embeddings, no local model download) or
# "azure,chroma" to also bake the ChromaDB backend. [dev]/[tui]/[mcp] are
# deliberately excluded: a batch container has no TTY/stdio peer.
ARG INSTALL_EXTRAS=azure
# Debian bookworm's apt pandoc is 2.17 (< the project's >= 3.0 requirement), so
# pandoc is installed from the pinned official .deb instead. TARGETARCH is
# provided by BuildKit/buildah (amd64 | arm64) so the image builds on both.
ARG PANDOC_VERSION=3.5
ARG TARGETARCH=amd64

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Fetch the pinned pandoc .deb and extract just the binary — no dpkg-managed
# packages leak into the runtime stage (pandoc is a static Haskell binary).
RUN set -eux; \
    curl -fsSL -o /tmp/pandoc.deb \
      "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${TARGETARCH}.deb"; \
    dpkg-deb -x /tmp/pandoc.deb /tmp/pandoc-x; \
    cp /tmp/pandoc-x/usr/bin/pandoc /usr/local/bin/pandoc; \
    rm -rf /tmp/pandoc.deb /tmp/pandoc-x; \
    /usr/local/bin/pandoc --version | head -1

# Self-contained venv so the runtime stage copies one directory.
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip \
 && pip install ".[${INSTALL_EXTRAS}]"

# ── Stage 2: runtime — slim, non-root, no build toolchain ─────────────────────
FROM python:3.11-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="sdd-pipeline" \
      org.opencontainers.image.description="Semantic search pipeline for Confluence SDD documents (batch CLI)" \
      org.opencontainers.image.source="https://github.com/your-org/sdd-semantic-pipeline"

# Non-root user at UID/GID 1000 — matches the AKS securityContext (runAsUser
# 1000) and rootless Podman `--userns=keep-id:uid=1000,gid=1000`, so files
# written to bind-mounted inbox/outbox stay owned by the host user.
RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/app --shell /usr/sbin/nologin app

COPY --from=builder /usr/local/bin/pandoc /usr/local/bin/pandoc
COPY --from=builder /opt/venv /opt/venv

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ANONYMIZED_TELEMETRY=false \
    HF_HOME=/app/.cache/huggingface \
    PIPELINE_INBOX_DIR=/app/inbox \
    PIPELINE_OUTBOX_DIR=/app/outbox \
    PIPELINE_CHROMA_PERSIST_DIR=/app/outbox/index \
    PIPELINE_ENFORCE_WORKSPACE=true

WORKDIR /app
# Pre-create the workspace zones + HF cache, app-owned, so the contract holds
# and writes succeed even before a volume is mounted (and under AKS fsGroup).
# PIPELINE_CHROMA_PERSIST_DIR stays under the outbox, as the contract requires.
RUN mkdir -p /app/inbox /app/outbox/index /app/.cache/huggingface \
 && chown -R app:app /app

USER app
VOLUME ["/app/inbox", "/app/outbox", "/app/.cache/huggingface"]

ENTRYPOINT ["sdd-pipeline"]
# Default to the dependency self-check (verifies pandoc + deps, exits 0) — a safe
# no-op when the container is run with no command. Override with index/convert/etc.
CMD ["check"]
