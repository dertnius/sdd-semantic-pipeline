"""Tests for mixed-section reconciliation (table authoritative)."""

from __future__ import annotations

from sdd_pipeline.models import EntityRecord
from sdd_pipeline.reconcile import reconcile


def _r(text, field, source, conf, section="s", canonical=""):
    return EntityRecord(text, field, source, conf, section, canonical or text)


def test_table_beats_prose_for_same_canonical():
    table = _r("payment-service", "related component", "table_cell", 1.0)
    prose = _r("payment-service", "", "backtick_regex", 0.8)
    out = reconcile([prose, table])
    assert len(out) == 1
    kept = out[0]
    assert kept.source == "table_cell" and kept.field == "related component"


def test_distinct_canonicals_all_kept():
    out = reconcile(
        [
            _r("a", "f", "table_cell", 1.0),
            _r("b", "f", "table_cell", 1.0),
        ]
    )
    assert {r.text for r in out} == {"a", "b"}


def test_dedupe_is_per_section():
    out = reconcile(
        [
            _r("x", "f", "table_cell", 1.0, section="s1"),
            _r("x", "f", "prose", 0.6, section="s2"),
        ]
    )
    assert len(out) == 2  # same canonical, different sections → not merged


def test_canonical_match_is_case_insensitive():
    out = reconcile(
        [
            _r("OrderSvc", "f", "prose", 0.6, canonical="ordersvc"),
            _r("ordersvc", "f", "table_cell", 1.0, canonical="ordersvc"),
        ]
    )
    assert len(out) == 1 and out[0].confidence == 1.0


def test_output_is_deterministic_regardless_of_input_order():
    a = _r("a", "f", "table_cell", 1.0)
    b = _r("b", "g", "prose", 0.6)
    assert reconcile([a, b]) == reconcile([b, a])
