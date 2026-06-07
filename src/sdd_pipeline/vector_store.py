"""
Stage 7b: Vector store backed by ChromaDB.

Handles persistence, cosine-similarity search, and filtered retrieval.
All ChromaDB-specific logic is isolated here so the rest of the pipeline
can use a mock via duck-typing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from .models import ContentType, SectionType, SemanticChunk

logger = logging.getLogger(__name__)

# Provenance keys recorded on the collection so a search cannot be run with an
# embedder that differs from the one that built the index.
PROVENANCE_KEYS = ("embedding_provider", "embedding_model", "embedding_dimension")

# ── Result type ──────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    chunk_id: str
    content: str
    metadata: dict
    distance: float
    fused_score: float | None = None  # set by hybrid retrieval (RRF)

    @property
    def score(self) -> float:
        """Hybrid fused score when present, else cosine similarity (1 − distance)."""
        if self.fused_score is not None:
            return self.fused_score
        return 1.0 - self.distance

    def __repr__(self) -> str:
        return (
            f"SearchResult("
            f"id={self.chunk_id!r}, "
            f"score={self.score:.3f}, "
            f"section={self.metadata.get('section_type', '?')!r})"
        )


# ── VectorStore ───────────────────────────────────────────────────────────────


class VectorStore:
    """
    ChromaDB-backed store for :class:`SemanticChunk` embeddings.

    Uses ``hnsw:space=cosine`` so distances are in [0, 1] and
    ``score = 1 - distance``.
    """

    def __init__(
        self,
        persist_dir: str = "./data/chroma",
        collection_name: str = "sdd_docs",
    ) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError("chromadb is not installed.\nRun: pip install chromadb") from exc

        # Disable telemetry without requiring Settings import
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Write ────────────────────────────────────────────────────────────────

    def add_chunks(
        self,
        chunks: list[SemanticChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Upsert *chunks* and their *embeddings* into the collection."""
        if not chunks:
            return
        self._collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.content for c in chunks],
            # Chroma's stub wants ndarray/Sequence; list[list[float]] is valid at runtime.
            embeddings=embeddings,  # type: ignore[arg-type]
            metadatas=[c.to_metadata() for c in chunks],
        )

    def delete_document(self, doc_id: str) -> int:
        """Remove all chunks that belong to *doc_id*. Returns deleted count."""
        results = self._collection.get(where={"doc_id": {"$eq": doc_id}})  # type: ignore[dict-item]
        ids = results["ids"]
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def reset(self) -> None:
        """Delete all chunks from the collection (recreates it; provenance is lost)."""
        name = self._collection.name
        self._client.delete_collection(name)
        self._collection = self._client.create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Provenance ───────────────────────────────────────────────────────────

    def set_provenance(self, provider: str, model: str, dimension: int) -> None:
        """
        Record which embedder built this index, merged onto existing metadata.

        Best-effort: failures are logged, never raised, so indexing never breaks.
        ``get_or_create_collection`` only sets metadata on create, so updates go
        through ``Collection.modify``. Reserved ``hnsw:*`` keys are excluded — Chroma
        manages those internally and rejects a modify payload that contains them.
        """
        existing = getattr(self._collection, "metadata", None) or {}
        merged = {k: v for k, v in existing.items() if not str(k).startswith("hnsw:")}
        merged.update(
            {
                "embedding_provider": provider,
                "embedding_model": model,
                "embedding_dimension": int(dimension),
            }
        )
        try:
            self._collection.modify(metadata=merged)
        except Exception:
            logger.warning("Could not persist embedding provenance to collection metadata.")

    def get_provenance(self) -> dict:
        """Return stored provenance keys, or ``{}`` if none recorded (legacy index)."""
        meta = getattr(self._collection, "metadata", None) or {}
        if not isinstance(meta, dict):
            return {}
        return {k: meta[k] for k in PROVENANCE_KEYS if k in meta}

    # ── Read ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_where(
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        doc_id: str | None = None,
    ) -> dict | None:
        """Build a ChromaDB ``where`` filter; conditions are ANDed together."""
        conditions: list[dict] = []
        if section_type:
            conditions.append({"section_type": {"$eq": section_type.value}})
        if content_type:
            conditions.append({"content_type": {"$eq": content_type.value}})
        if space:
            conditions.append({"space": {"$eq": space}})
        if doc_id:
            conditions.append({"doc_id": {"$eq": doc_id}})

        if len(conditions) == 0:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def get_corpus(
        self,
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        doc_id: str | None = None,
    ) -> list[SearchResult]:
        """
        Return every stored chunk (optionally filtered) for lexical indexing.

        Distances are not meaningful here (set to 0.0); callers use the
        ``content``/``metadata`` to build a BM25 index.
        """
        where = self._build_where(section_type, content_type, space, doc_id)
        results = self._collection.get(where=where, include=["documents", "metadatas"])
        ids = results["ids"] or []
        docs = results["documents"] or []
        metas = results["metadatas"] or []
        out: list[SearchResult] = []
        for chunk_id, doc, meta in zip(ids, docs, metas, strict=True):
            out.append(SearchResult(chunk_id, doc, dict(meta), distance=0.0))
        return out

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        doc_id: str | None = None,
    ) -> list[SearchResult]:
        """
        Return the *n_results* most similar chunks to *query_embedding*.

        All filter arguments are ANDed together when multiple are given.
        """
        where = self._build_where(section_type, content_type, space, doc_id)

        results = self._collection.query(
            # Chroma's stub wants ndarray/Sequence; list[list[float]] is valid at runtime.
            query_embeddings=[query_embedding],  # type: ignore[arg-type]
            n_results=min(n_results, self.count or 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        # Chroma types these as Optional and nested-per-query; guard before indexing.
        ids = results["ids"] or [[]]
        docs = results["documents"] or [[]]
        metas = results["metadatas"] or [[]]
        dists = results["distances"] or [[]]
        out: list[SearchResult] = []
        for chunk_id, doc, meta, dist in zip(ids[0], docs[0], metas[0], dists[0], strict=True):
            out.append(SearchResult(chunk_id, doc, dict(meta), dist))
        return out

    @property
    def count(self) -> int:
        return self._collection.count()
