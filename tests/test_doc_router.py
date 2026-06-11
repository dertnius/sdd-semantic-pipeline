"""Tests for doc_router (pure — DocumentModel built directly, no pandoc)."""

from __future__ import annotations

from sdd_pipeline.doc_router import detect_doc_type, load_taxonomy, taxonomy_for
from sdd_pipeline.models import DocumentMetadata, DocumentModel, Section


def _section(title: str) -> Section:
    return Section(level=1, title=title, section_id=title, breadcrumb=[title])


def _doc(titles: list[str]) -> DocumentModel:
    return DocumentModel(
        doc_id="d",
        metadata=DocumentMetadata(title="t"),
        root_sections=[_section(t) for t in titles],
    )


def test_detects_sad_by_fingerprint():
    doc = _doc(
        [
            "1. Executive summary",
            "2. Introduction",
            "3 Requirements",
            "4 Quality Attributes",
            "6 Target Solution Architecture",
        ]
    )
    assert detect_doc_type(doc) == "sad"


def test_unknown_when_below_threshold():
    doc = _doc(["Overview", "Installation", "FAQ"])
    assert detect_doc_type(doc) == "unknown"


def test_threshold_is_inclusive():
    doc = _doc(["2 Introduction", "3 Requirements", "4 Quality Attributes"])
    assert detect_doc_type(doc, threshold=3) == "sad"
    assert detect_doc_type(doc, threshold=4) == "unknown"


def test_taxonomy_for_routes_sad_to_taxonomy_else_empty():
    sad_tax = {"solution component 1": {"fields": ["description"], "orientation": "key_value"}}
    sad_doc = _doc(["2 Introduction", "3 Requirements", "4 Quality Attributes"])
    other_doc = _doc(["Overview", "Setup"])
    assert taxonomy_for(sad_doc, sad_tax) == sad_tax
    assert taxonomy_for(other_doc, sad_tax) == {}


def test_load_taxonomy_missing_file_returns_empty(tmp_path):
    assert load_taxonomy(tmp_path / "nope.json") == {}


def test_load_taxonomy_reads_real_committed_file():
    # data/taxonomy.json is generated + committed; sanity-check it loads.
    tax = load_taxonomy()
    assert "solution component 1" in tax
