"""Tests for the inventory-driven path of enrich_section/enrich_document."""

from __future__ import annotations

import random

from sdd_pipeline.enrichment import enrich_section
from sdd_pipeline.models import EntityRecord, Section


def _section(section_id: str = "s1") -> Section:
    return Section(level=1, title="Component", section_id=section_id, breadcrumb=["Component"])


DIRECTIONS = {"consumer": "depends_on", "expose": "exposes"}


def test_directional_fields_route_to_depends_on_and_exposes():
    sec = _section()
    inv = {
        "s1": [
            EntityRecord("order-service", "consumer", "table_cell", 1.0, "s1"),
            EntityRecord("REST API", "expose", "table_cell", 1.0, "s1"),
        ]
    }
    enrich_section(sec, inventory=inv, directions=DIRECTIONS)
    assert sec.depends_on == ["order-service"]
    assert sec.exposes == ["REST API"]


def test_non_directional_field_goes_to_metadata_bucket():
    sec = _section()
    inv = {"s1": [EntityRecord("Go 1.22", "technology stack", "table_cell", 1.0, "s1")]}
    enrich_section(sec, inventory=inv, directions=DIRECTIONS)
    assert sec.metadata["technology stack"] == ["Go 1.22"]
    assert sec.depends_on == [] and sec.exposes == []


def test_below_threshold_goes_to_raw_entities():
    sec = _section()
    inv = {"s1": [EntityRecord("some phrase", "", "noun_chunk", 0.5, "s1")]}
    enrich_section(sec, inventory=inv, directions=DIRECTIONS, confidence_threshold=0.6)
    assert sec.metadata["raw_entities"] == ["some phrase"]


def test_table_beats_prose_then_routes_by_table_field():
    sec = _section()
    inv = {
        "s1": [
            EntityRecord("payment-service", "", "backtick_regex", 0.8, "s1", "payment-service"),
            EntityRecord("payment-service", "consumer", "table_cell", 1.0, "s1", "payment-service"),
        ]
    }
    enrich_section(sec, inventory=inv, directions=DIRECTIONS)
    # Reconciliation keeps the table record → routed by its field to depends_on.
    assert sec.depends_on == ["payment-service"]
    assert "payment-service" not in sec.metadata.get("raw_entities", [])


def test_no_inventory_is_pure_legacy_enrichment():
    sec = _section()
    enrich_section(sec)  # no inventory
    assert sec.depends_on == [] and sec.exposes == [] and sec.metadata == {}
    assert sec.section_type is not None  # legacy enrichment still ran


def test_conservation_every_above_threshold_canonical_written_once():
    rng = random.Random(42)
    sources = ["table_cell", "allcaps_regex", "backtick_regex", "prose", "noun_chunk"]
    confs = {
        "table_cell": 1.0,
        "allcaps_regex": 0.9,
        "backtick_regex": 0.8,
        "prose": 0.6,
        "noun_chunk": 0.5,
    }
    fields = ["consumer", "expose", "technology stack", "protocol", ""]
    records = []
    for i in range(60):
        src = rng.choice(sources)
        records.append(
            EntityRecord(f"ent{i}", rng.choice(fields), src, confs[src], "s1", f"ent{i}")
        )
    sec = _section()
    enrich_section(sec, inventory={"s1": records}, directions=DIRECTIONS, confidence_threshold=0.6)

    written: list[str] = [
        *sec.depends_on,
        *sec.exposes,
        *(v for vals in sec.metadata.values() for v in vals),
    ]
    # All canonicals are unique here, so the written multiset is a set.
    above = {r.canonical for r in records if r.confidence >= 0.6}
    below = {r.canonical for r in records if r.confidence < 0.6}
    raw = set(sec.metadata.get("raw_entities", []))
    # Every above-threshold canonical appears exactly once across all fields.
    assert sorted(written) == sorted(set(written))  # no duplicates
    assert above <= set(written)  # nothing above-threshold dropped
    assert below <= raw  # below-threshold preserved in the audit bucket
