"""
Unit tests for the retrieval-eval scoring core (``src/tools/scripts/eval_retrieval.py``).

These exercise the recall@k / MRR math and the section-matcher join against
hand-built rankings — no embedding model, no pandoc, no index. The point is that
the *measurement itself* is trustworthy before we trust any number it produces.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load src/tools/scripts/eval_retrieval.py by path (src/tools/scripts/ is not on the import path).
_SCRIPT = Path(__file__).resolve().parent.parent / "src" / "tools" / "scripts" / "eval_retrieval.py"
_spec = importlib.util.spec_from_file_location("eval_retrieval", _SCRIPT)
assert _spec and _spec.loader
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_retrieval"] = ev
_spec.loader.exec_module(ev)


# ── matches() — the section-granularity join ──────────────────────────────────


def test_matches_requires_same_doc():
    assert not ev.matches(("a.md", "Overview"), ("b.md", "Overview"))


def test_matches_needle_is_case_insensitive_substring():
    assert ev.matches(("a.md", "Architecture > OMS Service"), ("a.md", "oms service"))
    assert not ev.matches(("a.md", "Architecture > OMS Service"), ("a.md", "inventory"))


def test_empty_needle_matches_any_section_in_doc():
    assert ev.matches(("a.md", "anything at all"), ("a.md", ""))
    assert not ev.matches(("other.md", "anything"), ("a.md", ""))


# ── recall@k ───────────────────────────────────────────────────────────────────


def test_recall_full_hit():
    retrieved = [("a.md", "Sec A"), ("a.md", "Sec B")]
    expected = [("a.md", "Sec A"), ("a.md", "Sec B")]
    assert ev.recall_at_k(retrieved, expected, 5) == 1.0


def test_recall_partial():
    retrieved = [("a.md", "Sec A"), ("a.md", "Sec C")]
    expected = [("a.md", "Sec A"), ("a.md", "Sec B")]  # B never retrieved
    assert ev.recall_at_k(retrieved, expected, 5) == pytest.approx(0.5)


def test_recall_respects_k_cutoff():
    retrieved = [("a.md", "noise")] * 4 + [("a.md", "Sec A")]  # relevant at rank 5
    expected = [("a.md", "Sec A")]
    assert ev.recall_at_k(retrieved, expected, 4) == 0.0
    assert ev.recall_at_k(retrieved, expected, 5) == 1.0


def test_recall_no_expected_is_zero_not_crash():
    assert ev.recall_at_k([("a.md", "x")], [], 5) == 0.0


def test_recall_dedups_section_split_across_chunks():
    # One section split into three chunks must still count once toward its matcher.
    retrieved = [("a.md", "Sec A")] * 3
    expected = [("a.md", "Sec A")]
    assert ev.recall_at_k(retrieved, expected, 10) == 1.0


# ── reciprocal rank ─────────────────────────────────────────────────────────────


def test_rr_rank_one():
    assert ev.reciprocal_rank([("a.md", "Sec A")], [("a.md", "Sec A")]) == 1.0


def test_rr_rank_three():
    retrieved = [("a.md", "x"), ("a.md", "y"), ("a.md", "Sec A")]
    assert ev.reciprocal_rank(retrieved, [("a.md", "Sec A")]) == pytest.approx(1 / 3)


def test_rr_miss_is_zero():
    assert ev.reciprocal_rank([("a.md", "x")], [("a.md", "Sec A")]) == 0.0


# ── score_query + aggregate ─────────────────────────────────────────────────────


def test_score_query_keys_and_values():
    retrieved = [("a.md", "x"), ("a.md", "Sec A")]  # relevant at rank 2
    m = ev.score_query(retrieved, [("a.md", "Sec A")], ks=(5, 10))
    assert m == {"recall@5": 1.0, "recall@10": 1.0, "rr": pytest.approx(0.5)}


def test_aggregate_macro_averages_and_renames_rr_to_mrr():
    q1 = {"recall@5": 1.0, "recall@10": 1.0, "rr": 1.0}
    q2 = {"recall@5": 0.0, "recall@10": 1.0, "rr": 0.5}
    agg = ev.aggregate([q1, q2])
    assert agg["recall@5"] == pytest.approx(0.5)
    assert agg["recall@10"] == pytest.approx(1.0)
    assert agg["MRR"] == pytest.approx(0.75)
    assert "rr" not in agg


def test_aggregate_empty():
    assert ev.aggregate([]) == {}


# ── load_queries (JSON shape; same as the frozen YAML) ──────────────────────────


def test_load_queries_parses_matchers(tmp_path):
    data = {
        "queries": [
            {
                "id": "q1",
                "text": "what depends on the OMS service?",
                "category": "cross-reference",
                "expected": [
                    {"doc": "sad.md", "section": "Dependencies"},
                    {"doc": "sad.md"},  # no section ⇒ doc-level matcher
                ],
            }
        ]
    }
    p = tmp_path / "queries.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    queries = ev.load_queries(p)
    assert len(queries) == 1
    q = queries[0]
    assert q.id == "q1"
    assert q.category == "cross-reference"
    assert q.expected == [("sad.md", "Dependencies"), ("sad.md", "")]


# ── HashingEmbedder (mock) — deterministic, lexical-ish, never a model ─────────


def test_hashing_embedder_is_deterministic_and_normalized():
    emb = ev.HashingEmbedder()
    v1 = emb.embed_query("auth service depends on database")
    v2 = emb.embed_query("auth service depends on database")
    assert v1 == v2
    assert len(v1) == ev.HashingEmbedder.DIM
    norm = sum(x * x for x in v1) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-9)


def test_hashing_embedder_overlap_ranks_higher():
    emb = ev.HashingEmbedder()
    q = emb.embed_query("inventory service api")

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    near = cos(q, emb.embed_query("the inventory service exposes an api"))
    far = cos(q, emb.embed_query("completely unrelated payroll text"))
    assert near > far
