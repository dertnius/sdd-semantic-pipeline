"""Tests for corpus_taxonomy: corpus-derived, coverage-gated taxonomy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdd_pipeline.corpus_taxonomy import (
    build_corpus_taxonomy,
    taxonomy_to_json,
    vocabulary_to_json,
)

CORPUS = Path(__file__).resolve().parent.parent / "src" / "tools" / "eval" / "corpus"


# ── serialization (pure) ───────────────────────────────────────────────────────


def test_taxonomy_json_is_canonical():
    tax = {
        "b": {"fields": ["y", "x"], "orientation": "wide"},
        "a": {"fields": [], "orientation": "wide"},
    }
    out = taxonomy_to_json(tax)
    assert out.index('"a"') < out.index('"b"')  # sorted keys
    assert json.loads(out)["b"]["fields"] == ["x", "y"]  # sorted fields


def test_vocabulary_sorted_by_descending_frequency():
    vocab = {"rare": 1, "common": 5, "mid": 3}
    ordered = list(json.loads(vocabulary_to_json(vocab)).items())
    assert [k for k, _ in ordered] == ["common", "mid", "rare"]


# ── corpus scan over the real eval corpus (needs pandoc) ───────────────────────


@pytest.mark.slow
def test_min_docs_gate_empty_on_single_doc_corpus(tmp_path):
    # src/tools/eval/corpus has one SAD; with min_docs=2 every field is below the gate.
    import shutil

    shutil.copy(CORPUS / "sad-retailnexus-oms.md", tmp_path / "sad.md")
    taxonomy, vocab = build_corpus_taxonomy(tmp_path, min_docs=2)
    assert taxonomy == {}  # nothing survives the coverage gate
    assert vocab  # but the ungated vocabulary still lists what was seen
    assert max(vocab.values()) == 1


@pytest.mark.slow
def test_min_docs_one_surfaces_real_data_fields(tmp_path):
    import shutil

    shutil.copy(CORPUS / "sad-retailnexus-oms.md", tmp_path / "sad.md")
    taxonomy, vocab = build_corpus_taxonomy(tmp_path, min_docs=1)
    # Real fields the data carries (not in the template) appear.
    assert "expose" in vocab
    assert "direction" in vocab
    # A known section maps to its real columns.
    assert "microservice inventory" in taxonomy
    assert "service" in taxonomy["microservice inventory"]["fields"]


@pytest.mark.slow
def test_two_doc_corpus_gates_to_shared_fields(tmp_path):
    # Same doc twice (distinct names) → every field has doc_freq 2 → all kept.
    import shutil

    shutil.copy(CORPUS / "sad-retailnexus-oms.md", tmp_path / "a.md")
    shutil.copy(CORPUS / "sad-retailnexus-oms.md", tmp_path / "b.md")
    taxonomy, vocab = build_corpus_taxonomy(tmp_path, min_docs=2)
    assert taxonomy  # fields now survive the gate
    assert all(v == 2 for v in vocab.values())


@pytest.mark.slow
def test_output_is_deterministic(tmp_path):
    import shutil

    shutil.copy(CORPUS / "sad-retailnexus-oms.md", tmp_path / "sad.md")
    t1, v1 = build_corpus_taxonomy(tmp_path, min_docs=1)
    t2, v2 = build_corpus_taxonomy(tmp_path, min_docs=1)
    assert taxonomy_to_json(t1) == taxonomy_to_json(t2)
    assert vocabulary_to_json(v1) == vocabulary_to_json(v2)
