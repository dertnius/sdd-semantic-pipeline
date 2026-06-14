"""
Shared pytest fixtures and sample data.

Fixtures here are available to every test file without explicit imports.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from sdd_pipeline.models import (
    ContentBlock,
    ContentType,
    DocumentMetadata,
    DocumentModel,
    Section,
    SectionType,
    SemanticChunk,
)

# ── Workspace contract (inbox/outbox) ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def _workspace_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Neutralise the inbox/outbox contract for the bulk of the suite.

    Most tests pass explicit ``tmp_path`` input/output paths that live *outside*
    the real ``inbox/``/``outbox/`` roots, so the enforcement guard would reject
    them. This autouse fixture turns enforcement off and redirects the inbox/
    outbox roots to per-test temp dirs, so default artifacts never land in the
    repo. Tests that exercise the guard re-enable it explicitly by setting
    ``PIPELINE_ENFORCE_WORKSPACE=true`` (and their own inbox/outbox roots).
    """
    monkeypatch.setenv("PIPELINE_ENFORCE_WORKSPACE", "false")
    monkeypatch.setenv("PIPELINE_INBOX_DIR", str(tmp_path / "_ws_inbox"))
    monkeypatch.setenv("PIPELINE_OUTBOX_DIR", str(tmp_path / "_ws_outbox"))


# ── Sample markdown ───────────────────────────────────────────────────────────

SAMPLE_MARKDOWN = """\
---
title: Auth Service Design
space: PLATFORM
url: https://confluence.example.com/display/PLATFORM/auth-service
labels: authentication,security,service-design
---

# Auth Service

## Overview

The Auth Service handles all authentication flows using JWT tokens.
It is a stateless microservice deployed on Kubernetes.

## Architecture

The service uses a stateless JWT-based approach.
The AuthService depends on UserService for credential validation.
Tokens are cached in Redis for fast revocation checks.

### Token Flow

1. Client sends credentials to `POST /auth/token`
2. AuthService validates via UserService
3. JWT is signed and returned with 1-hour expiry

## API Contract

### POST /auth/token

Validates credentials and returns a signed JWT.

```json
{"username": "alice", "password": "s3cr3t"}
```

Response:

```json
{"token": "eyJ...", "expires_in": 3600}
```

## Design Decision

We chose JWT over session cookies for horizontal scalability.
Session state would require sticky routing or a shared Redis session store.
The trade-off is that token revocation requires an explicit denylist.

## Deployment

The service is deployed via Helm on Kubernetes (namespace: `platform`).
Configuration is managed through ConfigMaps and Secrets.
CPU limit: 500m, Memory limit: 512Mi.
"""

# ── Minimal pandoc JSON AST ───────────────────────────────────────────────────
# Hand-crafted to match the format pandoc 3.x outputs.

SAMPLE_AST: dict = {
    "pandoc-api-version": [1, 23, 1],
    "meta": {
        "title": {
            "t": "MetaInlines",
            "c": [{"t": "Str", "c": "Auth Service Design"}],
        },
        "space": {
            "t": "MetaInlines",
            "c": [{"t": "Str", "c": "PLATFORM"}],
        },
        "labels": {
            "t": "MetaInlines",
            "c": [
                {"t": "Str", "c": "authentication"},
                {"t": "Str", "c": ",security"},
            ],
        },
    },
    "blocks": [
        {
            "t": "Header",
            "c": [
                1,
                ["auth-service", [], []],
                [{"t": "Str", "c": "Auth"}, {"t": "Space"}, {"t": "Str", "c": "Service"}],
            ],
        },
        {
            "t": "Header",
            "c": [
                2,
                ["overview", [], []],
                [{"t": "Str", "c": "Overview"}],
            ],
        },
        {
            "t": "Para",
            "c": [{"t": "Str", "c": "The Auth Service handles authentication using JWT."}],
        },
        {
            "t": "Header",
            "c": [
                2,
                ["architecture", [], []],
                [{"t": "Str", "c": "Architecture"}],
            ],
        },
        {
            "t": "Para",
            "c": [{"t": "Str", "c": "Stateless JWT-based approach with Redis token store."}],
        },
        {
            "t": "Header",
            "c": [
                2,
                ["api-contract", [], []],
                [
                    {"t": "Str", "c": "API"},
                    {"t": "Space"},
                    {"t": "Str", "c": "Contract"},
                ],
            ],
        },
        {
            "t": "CodeBlock",
            "c": [["", ["json"], []], '{"username": "alice", "password": "s3cr3t"}'],
        },
        {
            "t": "Header",
            "c": [
                2,
                ["decision", [], []],
                [
                    {"t": "Str", "c": "Design"},
                    {"t": "Space"},
                    {"t": "Str", "c": "Decision"},
                ],
            ],
        },
        {
            "t": "Para",
            "c": [
                {
                    "t": "Str",
                    "c": "JWT chosen over sessions for horizontal scalability.",
                }
            ],
        },
    ],
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_md_file(tmp_path: Path) -> Path:
    """Write SAMPLE_MARKDOWN to a temp file and return its path."""
    p = tmp_path / "auth-service.md"
    p.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    return p


@pytest.fixture
def sample_ast() -> dict:
    return SAMPLE_AST


@pytest.fixture
def sample_document_model() -> DocumentModel:
    """Pre-built DocumentModel (no pandoc required)."""
    return DocumentModel(
        doc_id="test-doc-001",
        metadata=DocumentMetadata(
            title="Auth Service Design",
            space="PLATFORM",
            url="https://confluence.example.com/display/PLATFORM/auth-service",
            labels=["authentication", "security"],
        ),
        root_sections=[
            Section(
                level=1,
                title="Auth Service",
                section_id="auth-service",
                breadcrumb=["Auth Service"],
                blocks=[],
                subsections=[
                    Section(
                        level=2,
                        title="Overview",
                        section_id="overview",
                        breadcrumb=["Auth Service", "Overview"],
                        blocks=[
                            ContentBlock(
                                block_id="blk001",
                                content_type=ContentType.PARAGRAPH,
                                text="The Auth Service handles authentication using JWT tokens.",
                            )
                        ],
                        section_type=SectionType.OVERVIEW,
                    ),
                    Section(
                        level=2,
                        title="Architecture",
                        section_id="architecture",
                        breadcrumb=["Auth Service", "Architecture"],
                        blocks=[
                            ContentBlock(
                                block_id="blk002",
                                content_type=ContentType.PARAGRAPH,
                                text=(
                                    "Stateless JWT-based microservice deployed on Kubernetes. "
                                    "The AuthService calls UserService for validation."
                                ),
                            )
                        ],
                        section_type=SectionType.ARCHITECTURE,
                    ),
                    Section(
                        level=2,
                        title="API Contract",
                        section_id="api-contract",
                        breadcrumb=["Auth Service", "API Contract"],
                        blocks=[
                            ContentBlock(
                                block_id="blk003",
                                content_type=ContentType.CODE,
                                text='{"username": "alice"}',
                                language="json",
                            )
                        ],
                        section_type=SectionType.API,
                    ),
                    Section(
                        level=2,
                        title="Design Decision",
                        section_id="decision",
                        breadcrumb=["Auth Service", "Design Decision"],
                        blocks=[
                            ContentBlock(
                                block_id="blk004",
                                content_type=ContentType.PARAGRAPH,
                                text="JWT chosen over sessions for horizontal scalability.",
                            )
                        ],
                        section_type=SectionType.DECISION,
                    ),
                    Section(
                        level=2,
                        title="Deployment",
                        section_id="deployment",
                        breadcrumb=["Auth Service", "Deployment"],
                        blocks=[
                            ContentBlock(
                                block_id="blk005",
                                content_type=ContentType.PARAGRAPH,
                                text="Deployed via Helm on Kubernetes namespace platform.",
                            )
                        ],
                        section_type=SectionType.DEPLOYMENT,
                    ),
                ],
            )
        ],
        source_path="/tmp/auth-service.md",
    )


@pytest.fixture
def sample_chunks() -> list[SemanticChunk]:
    """Two minimal SemanticChunks for store/embedding tests."""
    return [
        SemanticChunk(
            chunk_id="doc001_overview_blk001_0",
            doc_id="test-doc-001",
            breadcrumb=["Auth Service", "Overview"],
            content="The Auth Service handles authentication using JWT tokens.",
            content_type=ContentType.PARAGRAPH,
            language=None,
            section_type=SectionType.OVERVIEW,
            entities=["JWT"],
            tags=["overview"],
            depends_on=[],
            exposes=[],
            space="PLATFORM",
            labels=["authentication", "security"],
        ),
        SemanticChunk(
            chunk_id="doc001_arch_blk002_0",
            doc_id="test-doc-001",
            breadcrumb=["Auth Service", "Architecture"],
            content="Stateless JWT-based microservice deployed on Kubernetes.",
            content_type=ContentType.PARAGRAPH,
            language=None,
            section_type=SectionType.ARCHITECTURE,
            entities=["JWT", "Kubernetes"],
            tags=["architecture"],
            depends_on=[],
            exposes=[],
            space="PLATFORM",
            labels=["authentication", "security"],
        ),
    ]


# ── Model-free embedder (fast tests; no model download, no pandoc) ─────────────


class HashingEmbedder:
    """Deterministic, model-free embedder (hashing bag-of-words).

    Mirrors the eval harness's embedder (``src/tools/scripts/eval_retrieval.py``):
    lexically-overlapping texts get higher cosine similarity, so the full
    index -> search path can be exercised with no model download. It is a
    *wiring* stand-in, NOT a relevance/quality baseline.
    """

    DIM = 512

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.DIM
        for tok in text.lower().split():
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_chunks(self, chunks: list[SemanticChunk]) -> list[list[float]]:
        return [self._vec(c.to_embed_text()) for c in chunks]

    def embed_query(self, query: str) -> list[float]:
        return self._vec(query)


@pytest.fixture
def hashing_embedder() -> HashingEmbedder:
    """Inject into ``SemanticPipeline(embedding_model=...)`` for model-free tests."""
    return HashingEmbedder()
