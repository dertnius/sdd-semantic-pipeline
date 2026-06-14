"""
Fast, model-free, pandoc-free guard for the search path.

Drives the REAL pipeline orchestration — enrich -> chunk -> embed -> langchain
``MemoryVectorStore`` -> ``search`` / hybrid (RRF + BM25) — using the deterministic
``hashing_embedder`` fixture and the pre-built ``sample_document_model`` (no pandoc).
So a regression in filtering, ranking, provenance, or hybrid fusion is caught in the
fast lane without loading an embedding model or shelling out to pandoc.

The mock embedder is lexical (word-overlap), so these assertions check the *contract*
of the search path (results return, filters narrow, output is stable, hybrid runs),
NOT semantic relevance — that needs a real model and lives in the ``slow`` e2e tests.
"""

from __future__ import annotations

from pathlib import Path

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.models import DocumentModel, SectionType
from sdd_pipeline.pipeline import SemanticPipeline


def _indexed_pipeline(
    tmp_path: Path,
    doc: DocumentModel,
    embedder,
) -> SemanticPipeline:
    """Build a memory-backed pipeline and index one pre-parsed doc (no model/pandoc)."""
    config = PipelineConfig(chroma_persist_dir=str(tmp_path))
    pipe = SemanticPipeline(config=config, embedding_model=embedder)
    indexed = pipe.index_doc(doc, [])
    assert indexed > 0, "fixture doc should produce chunks"
    return pipe


def test_offline_search_returns_shaped_results(sample_document_model, hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder)
    results = pipe.search("kubernetes deployment", n_results=5)

    assert results, "expected at least one result"
    top = results[0]
    assert 0.0 <= top.score <= 1.0
    assert top.metadata.get("breadcrumb")
    assert top.metadata.get("section_type")


def test_section_type_filter_narrows(sample_document_model, hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder)

    filtered = pipe.search("service", n_results=10, section_type=SectionType.DEPLOYMENT)
    assert filtered, "the deployment section should match"
    assert all(r.metadata.get("section_type") == SectionType.DEPLOYMENT.value for r in filtered)

    # Sanity: the unfiltered query surfaces more than just deployment sections.
    unfiltered = pipe.search("service", n_results=10)
    assert {r.metadata.get("section_type") for r in unfiltered} - {SectionType.DEPLOYMENT.value}


def test_search_is_deterministic(sample_document_model, hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder)

    def fingerprint(results):
        return [(r.chunk_id, round(r.score, 6)) for r in results]

    first = pipe.search("authentication jwt token", n_results=5)
    second = pipe.search("authentication jwt token", n_results=5)
    assert fingerprint(first) == fingerprint(second)


def test_hybrid_path_runs_without_model(sample_document_model, hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder)
    # Exercises _hybrid_search: dense (hashing) + BM25, fused via RRF — all model-free.
    results = pipe.search("kubernetes", n_results=5, hybrid=True)
    assert results
    assert results[0].score is not None
