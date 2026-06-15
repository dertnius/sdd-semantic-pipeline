"""
Stage 7b: Pluggable vector store backends.

Two backends implement :class:`VectorStoreProtocol`, selected by
``make_vector_store(config)``:

- ``memory`` (default) — langchain-core's ``InMemoryVectorStore``, persisted as
  ``<persist_dir>/<collection>.json`` so a separate search process can load it.
- ``chroma`` — ChromaDB (optional dependency: ``pip install "sdd-pipeline[chroma]"``).

All backend-specific logic is isolated here so the rest of the pipeline can use
a mock via duck-typing. Both backend libraries are imported lazily inside the
class constructors, so this module imports cleanly without either installed.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .models import EMBED_FORMAT_VERSION, ContentType, Genre, SectionType, SemanticChunk

if TYPE_CHECKING:
    from .config import PipelineConfig

logger = logging.getLogger(__name__)

# Provenance keys recorded with the index. The embedding_* triple lets search
# refuse a configured embedder that differs from the one that built the index
# (incompatible vector spaces); embed_format_version lets it *warn* when the
# embed-text composition has changed since the index was built (the embedder is
# identical, but the stored vectors encode an older to_embed_text layout).
PROVENANCE_KEYS = (
    "embedding_provider",
    "embedding_model",
    "embedding_dimension",
    "embed_format_version",
)

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


# ── Protocol (allows test mocks and keeps the pipeline backend-agnostic) ─────


@runtime_checkable
class VectorStoreProtocol(Protocol):
    def add_chunks(self, chunks: list[SemanticChunk], embeddings: list[list[float]]) -> None: ...

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        doc_id: str | None = None,
        genre: Genre | None = None,
    ) -> list[SearchResult]: ...

    def get_corpus(
        self,
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        doc_id: str | None = None,
        genre: Genre | None = None,
    ) -> list[SearchResult]: ...

    def delete_document(self, doc_id: str) -> int: ...

    def reset(self) -> None: ...

    def set_provenance(self, provider: str, model: str, dimension: int) -> None: ...

    def get_provenance(self) -> dict: ...

    @property
    def count(self) -> int: ...


# ── Chroma backend ────────────────────────────────────────────────────────────


class ChromaVectorStore:
    """
    ChromaDB-backed store for :class:`SemanticChunk` embeddings.

    Uses ``hnsw:space=cosine`` so ``score = 1 - distance``.
    """

    def __init__(
        self,
        persist_dir: str = "./build/index",
        collection_name: str = "sdd_docs",
    ) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(
                "chromadb is not installed.\n"
                'Run: pip install "sdd-pipeline[chroma]" (or pip install chromadb)'
            ) from exc

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
                "embed_format_version": int(EMBED_FORMAT_VERSION),
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
        genre: Genre | None = None,
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
        if genre:
            conditions.append({"genre": {"$eq": genre.value}})

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
        genre: Genre | None = None,
    ) -> list[SearchResult]:
        """
        Return every stored chunk (optionally filtered) for lexical indexing.

        Distances are not meaningful here (set to 0.0); callers use the
        ``content``/``metadata`` to build a BM25 index.
        """
        where = self._build_where(section_type, content_type, space, doc_id, genre)
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
        genre: Genre | None = None,
    ) -> list[SearchResult]:
        """
        Return the *n_results* most similar chunks to *query_embedding*.

        All filter arguments are ANDed together when multiple are given.
        """
        where = self._build_where(section_type, content_type, space, doc_id, genre)

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


# Back-compat alias for external import sites.
VectorStore = ChromaVectorStore


# ── Memory backend (langchain-core InMemoryVectorStore) ──────────────────────


def _precomputed_embeddings() -> Any:
    """Stub Embeddings for InMemoryVectorStore's constructor/``load()`` signature.

    The pipeline computes vectors itself; this object must never be called, so
    any accidental embedding path fails loudly instead of silently re-embedding.
    """
    from langchain_core.embeddings import Embeddings

    class _PrecomputedEmbeddings(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise NotImplementedError("MemoryVectorStore receives precomputed vectors.")

        def embed_query(self, text: str) -> list[float]:
            raise NotImplementedError("MemoryVectorStore receives precomputed vectors.")

    return _PrecomputedEmbeddings()


class MemoryVectorStore:
    """
    langchain-core ``InMemoryVectorStore`` backend, persisted as JSON.

    Index file:      ``<persist_dir>/<collection>.json`` (``dump``/``load``)
    Provenance file: ``<persist_dir>/<collection>.provenance.json``

    Cosine similarity, mapped to ``distance = 1 - similarity`` so it shares
    Chroma's cosine-distance space and ``SearchResult.score`` semantics.
    """

    def __init__(
        self,
        persist_dir: str = "./build/index",
        collection_name: str = "sdd_docs",
    ) -> None:
        try:
            from langchain_core.vectorstores import InMemoryVectorStore
        except ImportError as exc:
            raise ImportError(
                "langchain-core is not installed.\nRun: pip install langchain-core"
            ) from exc

        self._persist_dir = Path(persist_dir)
        self._data_path = self._persist_dir / f"{collection_name}.json"
        self._provenance_path = self._persist_dir / f"{collection_name}.provenance.json"

        embedding = _precomputed_embeddings()
        if self._data_path.exists():
            # A corrupt index file raises here — deliberately loud, so a broken
            # index is never silently replaced by an empty one.
            self._store = InMemoryVectorStore.load(str(self._data_path), embedding)
        else:
            self._store = InMemoryVectorStore(embedding)

    def _dump(self) -> None:
        """Persist atomically: dump to a temp file, then swap it into place."""
        tmp = self._data_path.with_suffix(".json.tmp")
        self._store.dump(str(tmp))  # creates parent dirs, writes UTF-8 JSON
        tmp.replace(self._data_path)

    # ── Write ────────────────────────────────────────────────────────────────

    def add_chunks(
        self,
        chunks: list[SemanticChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Upsert *chunks* and their *embeddings*, then persist.

        Writes the documented ``store`` dict layout directly —
        ``add_documents`` would re-embed via the Embeddings object, which must
        never happen (the pipeline embeds ``embed_text``, not raw content).
        """
        if not chunks:
            return
        for chunk, vector in zip(chunks, embeddings, strict=True):
            self._store.store[chunk.chunk_id] = {
                "id": chunk.chunk_id,
                "vector": list(vector),
                "text": chunk.content,
                "metadata": chunk.to_metadata(),
            }
        self._dump()

    def delete_document(self, doc_id: str) -> int:
        """Remove all chunks that belong to *doc_id*. Returns deleted count."""
        ids = [
            chunk_id
            for chunk_id, item in self._store.store.items()
            if (item.get("metadata") or {}).get("doc_id") == doc_id
        ]
        if ids:
            self._store.delete(ids)
            self._dump()
        return len(ids)

    def reset(self) -> None:
        """Delete all chunks and the recorded provenance."""
        self._store.store.clear()
        self._dump()
        self._provenance_path.unlink(missing_ok=True)

    # ── Provenance ───────────────────────────────────────────────────────────

    def set_provenance(self, provider: str, model: str, dimension: int) -> None:
        """Record which embedder built this index in a sidecar JSON file.

        Best-effort: failures are logged, never raised, so indexing never breaks.
        """
        payload = {
            "embedding_provider": provider,
            "embedding_model": model,
            "embedding_dimension": int(dimension),
            "embed_format_version": int(EMBED_FORMAT_VERSION),
        }
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._provenance_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("Could not persist embedding provenance sidecar.")

    def get_provenance(self) -> dict:
        """Return stored provenance keys, or ``{}`` if none recorded."""
        try:
            data = json.loads(self._provenance_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: data[k] for k in PROVENANCE_KEYS if k in data}

    # ── Read ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_conditions(
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        doc_id: str | None = None,
        genre: Genre | None = None,
    ) -> dict[str, str]:
        """Metadata equality conditions; ANDed together when multiple are given."""
        conditions: dict[str, str] = {}
        if section_type:
            conditions["section_type"] = section_type.value
        if content_type:
            conditions["content_type"] = content_type.value
        if space:
            conditions["space"] = space
        if doc_id:
            conditions["doc_id"] = doc_id
        if genre:
            conditions["genre"] = genre.value
        return conditions

    @staticmethod
    def _make_filter(conditions: dict[str, str]) -> Callable[[Any], bool] | None:
        """Turn equality conditions into a langchain Document filter callable."""
        if not conditions:
            return None
        return lambda doc: all(doc.metadata.get(k) == v for k, v in conditions.items())

    def get_corpus(
        self,
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        doc_id: str | None = None,
        genre: Genre | None = None,
    ) -> list[SearchResult]:
        """
        Return every stored chunk (optionally filtered) for lexical indexing.

        Distances are not meaningful here (set to 0.0); callers use the
        ``content``/``metadata`` to build a BM25 index.
        """
        conditions = self._build_conditions(section_type, content_type, space, doc_id, genre)
        out: list[SearchResult] = []
        for item in self._store.store.values():
            meta = item.get("metadata") or {}
            if all(meta.get(k) == v for k, v in conditions.items()):
                # dict() copy: results must not alias the stored metadata dict.
                out.append(SearchResult(item["id"], item["text"], dict(meta), distance=0.0))
        return out

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        doc_id: str | None = None,
        genre: Genre | None = None,
    ) -> list[SearchResult]:
        """
        Return the *n_results* most similar chunks to *query_embedding*.

        All filter arguments are ANDed together when multiple are given.
        """
        conditions = self._build_conditions(section_type, content_type, space, doc_id, genre)
        hits = self._store.similarity_search_with_score_by_vector(
            embedding=query_embedding,
            k=n_results,
            filter=self._make_filter(conditions),
        )
        return [
            # langchain returns the stored metadata dict by reference — copy it.
            SearchResult(doc.id or "", doc.page_content, dict(doc.metadata), 1.0 - similarity)
            for doc, similarity in hits
        ]

    @property
    def count(self) -> int:
        return len(self._store.store)


# ── Factory ───────────────────────────────────────────────────────────────────


def make_vector_store(config: PipelineConfig) -> VectorStoreProtocol:
    """Construct the vector store selected by ``config.vector_store_backend``."""
    backend = (config.vector_store_backend or "memory").lower()
    if backend == "memory":
        return MemoryVectorStore(config.chroma_persist_dir, config.collection_name)
    if backend == "chroma":
        return ChromaVectorStore(config.chroma_persist_dir, config.collection_name)
    raise ValueError(f"Unknown vector_store_backend {backend!r}; expected 'memory' or 'chroma'.")
