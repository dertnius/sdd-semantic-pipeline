"""
Tests for sdd_pipeline.vector_store.

ChromaDB is mocked in all unit tests; no on-disk state is created.
The ``requires_chromadb`` marker guards the few tests that import the real
library to verify interface compatibility.
"""

from __future__ import annotations

import pytest

from sdd_pipeline.models import SectionType

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_query_response(
    ids: list[str],
    docs: list[str],
    metas: list[dict],
    dists: list[float],
) -> dict:
    """Build a ChromaDB-style query result envelope."""
    return {
        "ids": [ids],
        "documents": [docs],
        "metadatas": [metas],
        "distances": [dists],
    }


# ── SearchResult ──────────────────────────────────────────────────────────────


class TestSearchResult:
    def test_score_is_one_minus_distance(self):
        from sdd_pipeline.vector_store import SearchResult

        r = SearchResult(chunk_id="c1", content="text", metadata={}, distance=0.3)
        assert abs(r.score - 0.7) < 1e-9

    def test_repr_contains_score(self):
        from sdd_pipeline.vector_store import SearchResult

        r = SearchResult(
            chunk_id="c1", content="text", metadata={"section_type": "api"}, distance=0.2
        )
        assert "0.800" in repr(r)

    def test_zero_distance_is_perfect_score(self):
        from sdd_pipeline.vector_store import SearchResult

        r = SearchResult(chunk_id="c1", content="text", metadata={}, distance=0.0)
        assert r.score == 1.0

    def test_fused_score_overrides_cosine(self):
        from sdd_pipeline.vector_store import SearchResult

        r = SearchResult(chunk_id="c1", content="t", metadata={}, distance=0.9, fused_score=0.05)
        assert r.score == 0.05


# ── VectorStore (mocked) ──────────────────────────────────────────────────────


@pytest.fixture
def patched_store(mocker):
    """
    Return a (ChromaVectorStore, mock_collection) pair without importing chromadb.

    We bypass __init__ with __new__ so that the guard ``import chromadb`` inside
    __init__ is never reached — the store is wired directly to MagicMock objects.
    This makes the fixture work even when chromadb is not installed.
    """
    from sdd_pipeline.vector_store import ChromaVectorStore

    mock_collection = mocker.MagicMock()
    mock_collection.count.return_value = 0
    mock_collection.name = "sdd_docs"
    mock_collection.metadata = {}  # provenance helpers read this as a real dict

    mock_client = mocker.MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    # Allocate instance without running __init__
    store = ChromaVectorStore.__new__(ChromaVectorStore)
    store._client = mock_client
    store._collection = mock_collection

    return store, mock_collection


class TestAddChunks:
    def test_calls_upsert_with_correct_counts(self, patched_store, sample_chunks):
        store, collection = patched_store
        embeddings = [[0.1, 0.2]] * len(sample_chunks)

        store.add_chunks(sample_chunks, embeddings)

        collection.upsert.assert_called_once()
        kwargs = collection.upsert.call_args[1]
        assert len(kwargs["ids"]) == len(sample_chunks)
        assert len(kwargs["embeddings"]) == len(sample_chunks)
        assert len(kwargs["documents"]) == len(sample_chunks)
        assert len(kwargs["metadatas"]) == len(sample_chunks)

    def test_ids_match_chunk_ids(self, patched_store, sample_chunks):
        store, collection = patched_store
        embeddings = [[0.0] * 3] * len(sample_chunks)
        store.add_chunks(sample_chunks, embeddings)
        kwargs = collection.upsert.call_args[1]
        assert kwargs["ids"] == [c.chunk_id for c in sample_chunks]

    def test_empty_list_is_no_op(self, patched_store):
        store, collection = patched_store
        store.add_chunks([], [])
        collection.upsert.assert_not_called()

    def test_metadata_all_scalar(self, patched_store, sample_chunks):
        store, collection = patched_store
        embeddings = [[0.0]] * len(sample_chunks)
        store.add_chunks(sample_chunks, embeddings)
        kwargs = collection.upsert.call_args[1]
        for meta in kwargs["metadatas"]:
            for v in meta.values():
                assert isinstance(v, (str, int, float, bool))


class TestSearch:
    def test_returns_search_results(self, patched_store):
        from sdd_pipeline.vector_store import SearchResult

        store, collection = patched_store
        collection.count.return_value = 5
        collection.query.return_value = _make_query_response(
            ids=["c1"],
            docs=["Overview text"],
            metas=[{"section_type": "overview", "doc_id": "d1"}],
            dists=[0.15],
        )

        results = store.search([0.1, 0.2, 0.3], n_results=1)

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].chunk_id == "c1"
        assert abs(results[0].score - 0.85) < 1e-9

    def test_no_filters_passes_none_where(self, patched_store):
        store, collection = patched_store
        collection.count.return_value = 1
        collection.query.return_value = _make_query_response([], [], [], [])
        store.search([0.0])
        kwargs = collection.query.call_args[1]
        assert kwargs["where"] is None

    def test_single_filter_no_and_wrapper(self, patched_store):
        store, collection = patched_store
        collection.count.return_value = 1
        collection.query.return_value = _make_query_response([], [], [], [])
        store.search([0.0], section_type=SectionType.API)
        kwargs = collection.query.call_args[1]
        assert "$and" not in kwargs["where"]
        assert "section_type" in kwargs["where"]

    def test_multiple_filters_uses_and(self, patched_store):
        store, collection = patched_store
        collection.count.return_value = 1
        collection.query.return_value = _make_query_response([], [], [], [])
        store.search([0.0], section_type=SectionType.API, space="PLATFORM")
        kwargs = collection.query.call_args[1]
        assert "$and" in kwargs["where"]

    def test_empty_results(self, patched_store):
        store, collection = patched_store
        collection.count.return_value = 0
        collection.query.return_value = _make_query_response([], [], [], [])
        results = store.search([0.0])
        assert results == []


class TestGetCorpus:
    def test_returns_all_chunks_flat(self, patched_store):
        from sdd_pipeline.vector_store import SearchResult

        store, collection = patched_store
        collection.get.return_value = {
            "ids": ["c1", "c2"],
            "documents": ["alpha", "beta"],
            "metadatas": [{"breadcrumb": "A"}, {"breadcrumb": "B"}],
        }
        corpus = store.get_corpus()
        assert [r.chunk_id for r in corpus] == ["c1", "c2"]
        assert all(isinstance(r, SearchResult) for r in corpus)
        assert corpus[0].content == "alpha"

    def test_passes_filter_where(self, patched_store):
        store, collection = patched_store
        collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        store.get_corpus(section_type=SectionType.API)
        kwargs = collection.get.call_args[1]
        assert "section_type" in kwargs["where"]


class TestProvenance:
    def test_set_provenance_excludes_hnsw_and_adds_keys(self, patched_store):
        store, collection = patched_store
        collection.metadata = {"hnsw:space": "cosine", "custom": "keep"}
        store.set_provenance("local", "all-MiniLM-L6-v2", 384)
        meta = collection.modify.call_args[1]["metadata"]
        # hnsw:* keys are reserved by Chroma — excluded from the modify payload.
        assert "hnsw:space" not in meta
        assert meta["custom"] == "keep"  # other existing metadata preserved
        assert meta["embedding_provider"] == "local"
        assert meta["embedding_model"] == "all-MiniLM-L6-v2"
        assert meta["embedding_dimension"] == 384

    def test_set_provenance_swallows_modify_errors(self, patched_store):
        store, collection = patched_store
        collection.modify.side_effect = RuntimeError("chroma boom")
        # Must not raise — provenance is best-effort.
        store.set_provenance("azure", "dep", 1536)

    def test_get_provenance_returns_recorded_keys(self, patched_store):
        store, collection = patched_store
        collection.metadata = {
            "hnsw:space": "cosine",
            "embedding_provider": "azure",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimension": 1536,
        }
        assert store.get_provenance() == {
            "embedding_provider": "azure",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimension": 1536,
        }

    def test_get_provenance_empty_when_absent(self, patched_store):
        store, collection = patched_store
        collection.metadata = {"hnsw:space": "cosine"}
        assert store.get_provenance() == {}


class TestDeleteDocument:
    def test_deletes_returned_ids(self, patched_store):
        store, collection = patched_store
        collection.get.return_value = {"ids": ["c1", "c2"]}
        count = store.delete_document("doc1")
        assert count == 2
        collection.delete.assert_called_once_with(ids=["c1", "c2"])

    def test_no_op_when_nothing_to_delete(self, patched_store):
        store, collection = patched_store
        collection.get.return_value = {"ids": []}
        count = store.delete_document("missing-doc")
        assert count == 0
        collection.delete.assert_not_called()


class TestReset:
    def test_deletes_and_recreates_collection(self, patched_store):
        store, _collection = patched_store
        store.reset()
        store._client.delete_collection.assert_called_once_with("sdd_docs")
        store._client.create_collection.assert_called_once()
