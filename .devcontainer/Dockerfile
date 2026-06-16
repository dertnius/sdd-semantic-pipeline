# syntax=docker/dockerfile:1
# ── Prebuild image for the SDD Semantic Pipeline dev container ────────────────
# Used by .devcontainer/devcontainer.json (build.dockerfile) and `devpod build`.
# Bakes pandoc + the heavy Python deps (and a small dev embedding model) so cold
# starts on Docker / Kubernetes / cloud providers are fast.
#
# Base: Microsoft devcontainers Python image — provides a non-root `vscode`
# user, git, curl, and common dev tooling.
FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# ── pandoc (>= 3.0) ───────────────────────────────────────────────────────────
# Installed from the pinned official .deb. Debian bookworm's apt ships pandoc
# 2.17, below the project's >= 3.0 requirement, so apt is deliberately avoided.
# TARGETARCH is provided by BuildKit (amd64 / arm64) so the image builds on both
# Intel and ARM hosts (Apple Silicon, arm64 cloud nodes).
ARG PANDOC_VERSION=3.5
ARG TARGETARCH=amd64
RUN set -eux; \
    curl -fsSL -o /tmp/pandoc.deb \
      "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${TARGETARCH}.deb"; \
    dpkg -i /tmp/pandoc.deb; \
    rm -f /tmp/pandoc.deb; \
    pandoc --version | head -1

# ── Provider-independent caches ───────────────────────────────────────────────
# Fixed, world-writable cache dirs so the pip + HuggingFace caches work
# regardless of the runtime user (sidesteps the /root vs /home/vscode mismatch).
# The devcontainer mounts named volumes here so downloads survive rebuilds.
ENV PIP_CACHE_DIR=/opt/cache/pip \
    HF_HOME=/opt/cache/huggingface
RUN mkdir -p "$PIP_CACHE_DIR" "$HF_HOME" && chmod -R 777 /opt/cache

# ── Bake the heavy Python dependencies ────────────────────────────────────────
# Copy just the metadata + source needed to resolve and install the project, so
# the torch / sentence-transformers / chromadb / textual wheels live in the
# image. The runtime postCreateCommand re-runs the *editable* install, which is
# then near-instant because every dependency is already satisfied.
WORKDIR /tmp/build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip \
    && pip install '.[dev]'

# Let the non-root `vscode` user perform the editable install at runtime — it
# writes an .egg-link/.pth and the console script into these dirs.
RUN chown -R vscode /usr/local/lib/python3.11/site-packages /usr/local/bin

# The real source is bind-mounted over the workspace at runtime; drop the
# build-time copy so it can't shadow it or bloat the layer.
WORKDIR /
RUN rm -rf /tmp/build

# ── Optional: prefetch a small dev embedding model into the baked HF cache ─────
# Makes the first `sdd-pipeline index` offline-instant on k8s/cloud where the
# named-volume cache may not exist. The production BAAI/bge-large-en-v1.5 model
# still downloads on first use. Build with --build-arg PREFETCH_MODEL="" to skip.
ARG PREFETCH_MODEL=all-MiniLM-L6-v2
RUN if [ -n "$PREFETCH_MODEL" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${PREFETCH_MODEL}')"; \
      chmod -R 777 /opt/cache; \
    fi
