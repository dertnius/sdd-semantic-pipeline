"""
Tests for the memory vector-store backend and the backend factory.

Unlike the Chroma tests (mocked collection), these use the REAL
langchain-core ``InMemoryVectorStore`` — it is pure-Python and fast, so the
roundtrip tests double as a tripwire for layout changes in the library.
"""

from __future__ import annotations

import json
import types

import pytest

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.models import ContentType, SectionType, SemanticChunk
from sdd_pipeline.vector_store import (
    ChromaVectorStore,
    MemoryVectorStore,
    SearchResult,
    VectorStoreProtocol,
    make_vector_store,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _chunk(
    chunk_id: str,
    doc_id: str = "doc-a",
    content: str = "Some content.",
    section_type: SectionType = SectionType.OVERVIEW,
    content_type: ContentType = ContentType.PARAGRAPH,
    space: str = "PLATFORM",
) -> SemanticChunk:
    return SemanticChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        breadcrumb=["Doc", "Section"],
        content=content,
        content_type=content_type,
        language=None,
        section_type=section_type,
        entities=[],
        tags=[],
        depends_on=[],
        exposes=[],
        space=space,
        labels=[],
    )


@pytest.fixture
def store(tmp_path) -> MemoryVectorStore:
    return MemoryVectorStore(persist_dir=str(tmp_path), collection_name="sdd_docs")


# Orthogonal vectors: c1 matches [1,0,0] exactly, c2 matches [0,1,0].
_CHUNKS = [
    _chunk("c1", doc_id="doc-a", content="Alpha content", section_type=SectionType.OVERVIEW),
    _chunk(
        "c2",
        doc_id="doc-b",
        content="Beta content",
        section_type=SectionType.ARCHITECTURE,
        space="OTHER",
    ),
]
_VECTORS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


# ── Empty store ───────────────────────────────────────────────────────────────


class TestEmptyStore:
    def test_fresh_store_is_empty(self, store, tmp_path):
        assert store.count == 0
        assert store.search([1.0, 0.0, 0.0]) == []
        assert store.get_corpus() == []
        assert store.get_provenance() == {}

    def test_add_empty_is_noop(self, store, tmp_path):
        store.add_chunks([], [])
        assert store.count == 0
        assert not (tmp_path / "sdd_docs.json").exists()


# ── Add + search roundtrip ────────────────────────────────────────────────────


class TestRoundtrip:
    def test_nearest_result_first(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        results = store.search([1.0, 0.0, 0.0], n_results=2)
        assert [r.chunk_id for r in results] == ["c1", "c2"]
        assert all(isinstance(r, SearchResult) for r in results)

    def test_identical_vector_is_perfect_score(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        top = store.search([1.0, 0.0, 0.0], n_results=1)[0]
        assert top.distance == pytest.approx(0.0, abs=1e-9)
        assert top.score == pytest.approx(1.0, abs=1e-9)
        assert top.content == "Alpha content"

    def test_k_larger_than_count(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        assert len(store.search([1.0, 0.0, 0.0], n_results=50)) == 2

    def test_upsert_replaces_same_chunk_id(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        updated = _chunk("c1", doc_id="doc-a", content="Alpha v2")
        store.add_chunks([updated], [[1.0, 0.0, 0.0]])
        assert store.count == 2
        top = store.search([1.0, 0.0, 0.0], n_results=1)[0]
        assert top.content == "Alpha v2"

    def test_mismatched_lengths_raise(self, store):
        with pytest.raises(ValueError):
            store.add_chunks(_CHUNKS, [[1.0, 0.0, 0.0]])


# ── Filters ───────────────────────────────────────────────────────────────────


class TestFilters:
    @pytest.fixture(autouse=True)
    def _populate(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        self.store = store

    def test_section_type_filter(self):
        results = self.store.search([1.0, 0.0, 0.0], section_type=SectionType.ARCHITECTURE)
        assert [r.chunk_id for r in results] == ["c2"]

    def test_content_type_filter(self):
        results = self.store.search([1.0, 0.0, 0.0], content_type=ContentType.PARAGRAPH)
        assert len(results) == 2

    def test_space_filter(self):
        results = self.store.search([0.0, 1.0, 0.0], space="PLATFORM")
        assert [r.chunk_id for r in results] == ["c1"]

    def test_doc_id_filter(self):
        results = self.store.search([1.0, 0.0, 0.0], doc_id="doc-b")
        assert [r.chunk_id for r in results] == ["c2"]

    def test_filters_are_anded(self):
        results = self.store.search(
            [1.0, 0.0, 0.0], section_type=SectionType.OVERVIEW, space="OTHER"
        )
        assert results == []

    def test_non_matching_filter_returns_empty(self):
        assert self.store.search([1.0, 0.0, 0.0], space="NOPE") == []


# ── get_corpus ────────────────────────────────────────────────────────────────


class TestGetCorpus:
    def test_returns_all_with_zero_distance(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        corpus = store.get_corpus()
        assert {r.chunk_id for r in corpus} == {"c1", "c2"}
        assert all(r.distance == 0.0 for r in corpus)

    def test_filtered_subset(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        corpus = store.get_corpus(doc_id="doc-a")
        assert [r.chunk_id for r in corpus] == ["c1"]

    def test_metadata_is_a_copy(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        first = store.get_corpus(doc_id="doc-a")[0]
        first.metadata["doc_id"] = "mutated"
        again = store.get_corpus(doc_id="doc-a")
        assert [r.chunk_id for r in again] == ["c1"]

    def test_search_metadata_is_a_copy(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        top = store.search([1.0, 0.0, 0.0], n_results=1)[0]
        top.metadata["space"] = "mutated"
        assert store.search([1.0, 0.0, 0.0], n_results=1, space="PLATFORM") != []


# ── delete / reset ────────────────────────────────────────────────────────────


class TestDeleteReset:
    def test_delete_document_removes_only_that_doc(self, store, tmp_path):
        store.add_chunks(_CHUNKS, _VECTORS)
        deleted = store.delete_document("doc-a")
        assert deleted == 1
        assert store.count == 1
        # Persisted: a fresh instance over the same dir no longer sees it.
        reloaded = MemoryVectorStore(persist_dir=str(tmp_path), collection_name="sdd_docs")
        assert {r.chunk_id for r in reloaded.get_corpus()} == {"c2"}

    def test_delete_unknown_doc_returns_zero(self, store):
        store.add_chunks(_CHUNKS, _VECTORS)
        assert store.delete_document("nope") == 0
        assert store.count == 2

    def test_reset_clears_chunks_and_provenance(self, store, tmp_path):
        store.add_chunks(_CHUNKS, _VECTORS)
        store.set_provenance("local", "test-model", 3)
        store.reset()
        assert store.count == 0
        assert store.get_provenance() == {}
        assert not (tmp_path / "sdd_docs.provenance.json").exists()


# ── Persistence ───────────────────────────────────────────────────────────────


class TestPersistence:
    def test_index_and_provenance_survive_reload(self, store, tmp_path):
        store.add_chunks(_CHUNKS, _VECTORS)
        store.set_provenance("local", "test-model", 3)

        reloaded = MemoryVectorStore(persist_dir=str(tmp_path), collection_name="sdd_docs")
        assert reloaded.count == 2
        top = reloaded.search([1.0, 0.0, 0.0], n_results=1)[0]
        assert top.chunk_id == "c1"

        prov = reloaded.get_provenance()
        assert prov["embedding_provider"] == "local"
        assert prov["embedding_model"] == "test-model"
        assert prov["embedding_dimension"] == 3
        assert isinstance(prov["embedding_dimension"], int)

    def test_expected_files_on_disk(self, store, tmp_path):
        store.add_chunks(_CHUNKS, _VECTORS)
        store.set_provenance("local", "test-model", 3)
        assert (tmp_path / "sdd_docs.json").exists()
        assert (tmp_path / "sdd_docs.provenance.json").exists()
        assert not (tmp_path / "sdd_docs.json.tmp").exists()  # atomic swap cleaned up

    def test_corrupt_provenance_sidecar_returns_empty(self, store, tmp_path):
        (tmp_path / "sdd_docs.provenance.json").write_text("not json{", encoding="utf-8")
        assert store.get_provenance() == {}

    def test_non_dict_provenance_returns_empty(self, store, tmp_path):
        (tmp_path / "sdd_docs.provenance.json").write_text(json.dumps([1, 2]), encoding="utf-8")
        assert store.get_provenance() == {}

    def test_collections_are_independent(self, tmp_path):
        a = MemoryVectorStore(persist_dir=str(tmp_path), collection_name="col_a")
        a.add_chunks(_CHUNKS, _VECTORS)
        b = MemoryVectorStore(persist_dir=str(tmp_path), collection_name="col_b")
        assert b.count == 0


# ── Protocol conformance ──────────────────────────────────────────────────────


class TestProtocol:
    def test_memory_store_satisfies_protocol(self, store):
        assert isinstance(store, VectorStoreProtocol)

    def test_chroma_store_satisfies_protocol(self):
        # __new__ keeps this chromadb-free (same trick as the patched_store fixture).
        # `count` is a property protocol member, so a runtime_checkable isinstance
        # check evaluates it on the instance — stub _collection so it returns instead
        # of raising AttributeError on the uninitialised object.
        chroma = ChromaVectorStore.__new__(ChromaVectorStore)
        chroma._collection = types.SimpleNamespace(count=lambda: 0)
        assert isinstance(chroma, VectorStoreProtocol)


# ── Factory ───────────────────────────────────────────────────────────────────


class TestFactory:
    def test_default_backend_is_memory(self):
        assert PipelineConfig().vector_store_backend == "memory"

    def test_memory_backend(self, tmp_path):
        config = PipelineConfig(vector_store_backend="memory", chroma_persist_dir=str(tmp_path))
        assert isinstance(make_vector_store(config), MemoryVectorStore)

    def test_chroma_backend_dispatch(self, tmp_path, monkeypatch):
        calls: list[tuple] = []

        class _Recorder:
            def __init__(self, persist_dir, collection_name):
                calls.append((persist_dir, collection_name))

        import sdd_pipeline.vector_store as vs

        monkeypatch.setattr(vs, "ChromaVectorStore", _Recorder)
        config = PipelineConfig(
            vector_store_backend="chroma",
            chroma_persist_dir=str(tmp_path),
            collection_name="col_x",
        )
        result = vs.make_vector_store(config)
        assert isinstance(result, _Recorder)
        assert calls == [(str(tmp_path), "col_x")]

    def test_backend_is_case_insensitive(self, tmp_path):
        config = PipelineConfig(vector_store_backend="MEMORY", chroma_persist_dir=str(tmp_path))
        assert isinstance(make_vector_store(config), MemoryVectorStore)

    def test_unknown_backend_raises(self, tmp_path):
        config = PipelineConfig(vector_store_backend="bogus", chroma_persist_dir=str(tmp_path))
        with pytest.raises(ValueError, match="bogus"):
            make_vector_store(config)
