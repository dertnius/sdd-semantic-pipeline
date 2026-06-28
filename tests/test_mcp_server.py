"""
Model-free contract tests for the MCP server's tool logic.

Mirrors ``test_search_offline.py``: drives the real pipeline (enrich -> chunk ->
embed -> memory store -> search) with the deterministic ``hashing_embedder`` and
the pre-built ``sample_document_model`` — no ML model, no pandoc. We test the
plain worker functions directly (no MCP runtime) plus one smoke test that
``build_server`` wires up the four tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp")  # the server module imports `mcp`; skip if the extra is absent

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.mcp_server import (
    _expected_sad_sections,
    build_server,
    find_decision_context_impl,
    find_sad_coverage_impl,
    list_section_type_values,
    list_spaces_impl,
    resolve_section_type,
    result_to_dict,
    run_search,
)
from sdd_pipeline.models import SectionType
from sdd_pipeline.pipeline import SemanticPipeline
from sdd_pipeline.vector_store import SearchResult

_RESULT_KEYS = {
    "chunk_id",
    "score",
    "title",
    "source_url",
    "breadcrumb",
    "section_type",
    "doc_type",
    "space",
    "entities",
    "tags",
    "content",
}


def _indexed_pipeline(tmp_path: Path, doc, embedder, **config_kwargs) -> SemanticPipeline:
    config = PipelineConfig(chroma_persist_dir=str(tmp_path), **config_kwargs)
    pipe = SemanticPipeline(config=config, embedding_model=embedder)
    assert pipe.index_doc(doc, []) > 0
    return pipe


def _empty_pipeline(tmp_path: Path, embedder) -> SemanticPipeline:
    config = PipelineConfig(chroma_persist_dir=str(tmp_path))
    return SemanticPipeline(config=config, embedding_model=embedder)


# ── result_to_dict (shape, truncation, JSON-list decode) ───────────────────────


def test_result_to_dict_shape_truncation_and_list_decode():
    r = SearchResult(
        chunk_id="c1",
        content="x" * 1000,
        metadata={
            "title": "T",
            "source_url": "u",
            "breadcrumb": "A > B",
            "section_type": "decision",
            "space": "PLATFORM",
            "entities": '["JWT", "Kubernetes"]',  # JSON-encoded string in the store
            "tags": "[]",
        },
        distance=0.25,
    )

    full = result_to_dict(r)
    assert set(full) == _RESULT_KEYS
    assert full["chunk_id"] == "c1"
    assert full["content"] == "x" * 1000  # untruncated by default
    assert isinstance(full["score"], float)
    assert full["entities"] == ["JWT", "Kubernetes"]  # decoded to a list
    assert full["tags"] == []

    snippet = result_to_dict(r, truncate=600)
    assert len(snippet["content"]) == 603  # 600 chars + "..."
    assert snippet["content"].endswith("...")


def test_loads_list_handles_real_lists_and_garbage():
    # Memory backend may hand back a real list; malformed JSON degrades to [].
    r = SearchResult("c", "body", {"entities": ["A"], "tags": "not-json"}, 0.1)
    d = result_to_dict(r)
    assert d["entities"] == ["A"]
    assert d["tags"] == []


# ── resolve_section_type ───────────────────────────────────────────────────────


def test_resolve_section_type_paths():
    assert resolve_section_type("decision") is SectionType.DECISION
    assert resolve_section_type("  decision ") is SectionType.DECISION  # trimmed
    assert resolve_section_type("") is None
    assert resolve_section_type(None) is None
    with pytest.raises(ValueError, match="Unknown section_type"):
        resolve_section_type("bogus")


# ── run_search ─────────────────────────────────────────────────────────────────


def test_run_search_returns_shaped_results(sample_document_model, hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder)
    out = run_search(pipe, "kubernetes deployment", 5, None, None)
    assert out
    for rec in out:
        assert set(rec) == _RESULT_KEYS
        assert isinstance(rec["score"], float)
        assert isinstance(rec["entities"], list)
        assert isinstance(rec["tags"], list)


def test_run_search_section_type_narrows(sample_document_model, hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder)
    out = run_search(pipe, "service", 10, "deployment", None)
    assert out
    assert all(rec["section_type"] == "deployment" for rec in out)


def test_run_search_empty_index_raises(hashing_embedder, tmp_path):
    pipe = _empty_pipeline(tmp_path, hashing_embedder)
    with pytest.raises(ValueError, match="Index is empty"):
        run_search(pipe, "anything", 5, None, None)


def test_hybrid_none_defers_to_config(sample_document_model, hashing_embedder, tmp_path):
    # The dropped-bug regression: hybrid=None must take the configured hybrid path,
    # not silently force it off (which `hybrid=False` as a default would have done).
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder, hybrid_search=True)
    via_none = run_search(pipe, "kubernetes", 5, None, None, hybrid=None)
    via_true = [result_to_dict(r) for r in pipe.search("kubernetes", n_results=5, hybrid=True)]
    via_false = [result_to_dict(r) for r in pipe.search("kubernetes", n_results=5, hybrid=False)]
    assert via_none == via_true  # None deferred to config (True)
    assert via_none != via_false  # and hybrid genuinely changes the result here


# ── find_decision_context_impl (buckets, dedup, general recall) ────────────────


def test_find_decision_context_buckets_dedup_and_general(
    sample_document_model, hashing_embedder, tmp_path
):
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder)
    ctx = find_decision_context_impl(pipe, "service jwt kubernetes deployment")

    assert set(ctx) == {
        "general",
        "context",
        "decision",
        "alternatives",
        "tradeoffs",
        "consequences",
        "done_criteria",
    }
    assert all(isinstance(v, list) for v in ctx.values())

    # No chunk appears in more than one bucket.
    all_ids = [rec["chunk_id"] for bucket in ctx.values() for rec in bucket]
    assert len(all_ids) == len(set(all_ids))

    # general guarantees recall even though the fixture has no ADR-style sections.
    assert ctx["general"]
    # Section types absent from the fixture come back empty (no error).
    assert ctx["alternatives"] == []
    assert ctx["tradeoffs"] == []

    # Every general chunk is absent from the precision buckets (precision-first).
    precision_ids = {rec["chunk_id"] for k, v in ctx.items() if k != "general" for rec in v}
    assert all(rec["chunk_id"] not in precision_ids for rec in ctx["general"])


def test_find_decision_context_snippets_are_truncated(hashing_embedder, tmp_path, monkeypatch):
    # Build a doc with one long section so the 600-char snippet cap actually bites.
    from sdd_pipeline.models import (
        ContentBlock,
        ContentType,
        DocumentMetadata,
        DocumentModel,
        Section,
    )

    long_text = "kubernetes deployment scaling " * 60  # ~1800 chars
    doc = DocumentModel(
        doc_id="long-doc",
        metadata=DocumentMetadata(title="Long", space="PLATFORM", url="http://x"),
        root_sections=[
            Section(
                level=1,
                title="Root",
                section_id="root",
                breadcrumb=["Root"],
                blocks=[],
                subsections=[
                    Section(
                        level=2,
                        title="Overview",
                        section_id="ov",
                        breadcrumb=["Root", "Overview"],
                        blocks=[
                            ContentBlock(
                                block_id="b1",
                                content_type=ContentType.PARAGRAPH,
                                text=long_text,
                            )
                        ],
                        section_type=SectionType.OVERVIEW,
                    )
                ],
            )
        ],
        source_path="/tmp/long.md",
    )
    # The chunk gate would split a huge block; keep it whole for the test.
    pipe = _indexed_pipeline(
        tmp_path, doc, hashing_embedder, max_chunk_chars=10000, embed_char_budget=10000
    )
    ctx = find_decision_context_impl(pipe, "kubernetes deployment")
    snippets = [rec for bucket in ctx.values() for rec in bucket]
    assert snippets
    assert any(rec["content"].endswith("...") for rec in snippets)
    assert all(len(rec["content"]) <= 603 for rec in snippets)


def test_find_decision_context_empty_index_raises(hashing_embedder, tmp_path):
    pipe = _empty_pipeline(tmp_path, hashing_embedder)
    with pytest.raises(ValueError, match="Index is empty"):
        find_decision_context_impl(pipe, "anything")


# ── discovery helpers ──────────────────────────────────────────────────────────


def test_list_spaces_and_section_types(sample_document_model, hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, sample_document_model, hashing_embedder)
    assert list_spaces_impl(pipe) == ["PLATFORM"]

    values = list_section_type_values()
    assert {"decision", "alternative", "tradeoff", "consequence"} <= set(values)


def test_list_spaces_empty_index_returns_empty(hashing_embedder, tmp_path):
    pipe = _empty_pipeline(tmp_path, hashing_embedder)
    assert list_spaces_impl(pipe) == []


# ── build_server smoke (exposes the 4 tools) ───────────────────────────────────


def test_build_server_exposes_five_tools(sample_document_model, hashing_embedder, tmp_path):
    import asyncio

    from mcp.server.fastmcp import FastMCP

    config = PipelineConfig(chroma_persist_dir=str(tmp_path))
    pipe = SemanticPipeline(config=config, embedding_model=hashing_embedder)
    pipe.index_doc(sample_document_model, [])

    server = build_server(config, pipeline=pipe)
    assert isinstance(server, FastMCP)

    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == {
        "semantic_search",
        "find_decision_context",
        "find_sad_coverage",
        "list_section_types",
        "list_spaces",
    }


# ── model-free (lexical) MCP path ──────────────────────────────────────────────


class _ExplodingEmbedder:
    """Fails if used — proves the MCP lexical path never loads an embedding model."""

    def embed_chunks(self, chunks):  # pragma: no cover - must never run
        raise AssertionError("embed_chunks called for a lexical MCP server")

    def embed_query(self, query):  # pragma: no cover - must never run
        raise AssertionError("embed_query called for a lexical MCP server")


def test_run_search_model_free_over_lexical_index(sample_document_model, tmp_path):
    # A lexical index is built with no model, and the MCP search worker answers via BM25
    # without ever touching the embedder — Copilot gets multilingual search, no model.
    pipe = _indexed_pipeline(
        tmp_path, sample_document_model, _ExplodingEmbedder(), lexical_only=True
    )
    assert pipe.store.get_provenance().get("embedding_provider") == "lexical"

    results = run_search(pipe, "kubernetes deployment", top_k=5, section_type=None, space=None)
    assert results
    assert all(_RESULT_KEYS <= set(r) for r in results)


# ── find_sad_coverage + doc_type stamping ──────────────────────────────────────


def _sad_doc(arch_text: str = "We adopt FooBar for messaging."):
    """A minimal SAD-shaped doc: 3 fingerprint headings -> detect_doc_type == 'sad'."""
    from sdd_pipeline.models import (
        ContentBlock,
        ContentType,
        DocumentMetadata,
        DocumentModel,
        Section,
    )

    def section(title: str, sid: str, body: str) -> Section:
        return Section(
            level=1,
            title=title,
            section_id=sid,
            breadcrumb=[title],
            blocks=[
                ContentBlock(block_id=f"{sid}-b", content_type=ContentType.PARAGRAPH, text=body)
            ],
        )

    return DocumentModel(
        doc_id="sad-doc",
        metadata=DocumentMetadata(title="RetailNexus SAD", space="ARCH", url="http://sad"),
        root_sections=[
            section("Introduction", "intro", "This document is the SAD for the system."),
            section("Architecture", "arch", arch_text),
            section("Data Model", "data", "Orders are stored in PostgreSQL per service."),
        ],
        source_path="/tmp/sad.md",
    )


def _one_section_doc():
    from sdd_pipeline.models import (
        ContentBlock,
        ContentType,
        DocumentMetadata,
        DocumentModel,
        Section,
    )

    return DocumentModel(
        doc_id="notes-doc",
        metadata=DocumentMetadata(title="Notes", space="MISC", url="http://n"),
        root_sections=[
            Section(
                level=1,
                title="Notes",
                section_id="notes",
                breadcrumb=["Notes"],
                blocks=[
                    ContentBlock(
                        block_id="n-b",
                        content_type=ContentType.PARAGRAPH,
                        text="Some loose notes about caching and queues.",
                    )
                ],
            )
        ],
        source_path="/tmp/notes.md",
    )


def test_doc_type_stamped_onto_sad_chunks(hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, _sad_doc(), hashing_embedder)
    sad_chunks = [r for r in pipe.store.get_corpus() if r.metadata.get("doc_type") == "sad"]
    assert sad_chunks  # detect_doc_type ran at index time and stamped every chunk


def test_find_sad_coverage_hard_match(hashing_embedder, tmp_path):
    pipe = _indexed_pipeline(tmp_path, _sad_doc(), hashing_embedder)
    # The decision carries no section hint, so expected == () and a hard match only
    # needs the entity to appear in any SAD chunk (objective, model-free path).
    out = find_sad_coverage_impl(pipe, "adopt the FooBar approach", ["FooBar"])
    assert out["covered"] is True
    assert out["confidence"] == "hard"
    assert out["matched_entities"] == ["FooBar"]
    assert out["missing_entities"] == []


def test_find_sad_coverage_no_sad_in_index(hashing_embedder, tmp_path):
    # A non-SAD doc -> no chunk has doc_type='sad' -> confidence 'none', not covered.
    pipe = _indexed_pipeline(tmp_path, _one_section_doc(), hashing_embedder)
    out = find_sad_coverage_impl(pipe, "anything at all", ["JWT"])
    assert out["covered"] is False
    assert out["confidence"] == "none"
    assert out["missing_entities"] == ["JWT"]


def test_find_sad_coverage_empty_index_raises(hashing_embedder, tmp_path):
    pipe = _empty_pipeline(tmp_path, hashing_embedder)
    with pytest.raises(ValueError, match="Index is empty"):
        find_sad_coverage_impl(pipe, "anything", ["X"])


def test_expected_sad_sections_mapping():
    assert _expected_sad_sections("choose a database engine") == ("data_model",)
    assert _expected_sad_sections("integration via a kafka topic") == ("architecture",)
    assert _expected_sad_sections("a brand new microservice") == ("architecture", "api")
    assert _expected_sad_sections("nothing topical here") == ()
