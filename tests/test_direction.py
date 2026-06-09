"""Tests for direction resolution (field name -> depends_on/exposes)."""

from __future__ import annotations

from sdd_pipeline.direction import load_field_directions, resolve_direction


def test_resolve_normalises_both_sides():
    directions = {"consumer": "depends_on", "expose": "exposes"}
    assert resolve_direction("Consumers", directions) == "depends_on"  # plural/case
    assert resolve_direction("Exposes", directions) == "exposes"
    assert resolve_direction("Owner", directions) is None  # unmapped → metadata


def test_load_real_committed_config():
    directions = load_field_directions()  # config/field_directions.yaml
    # Entries are normalised at load; seeded directional fields resolve.
    assert resolve_direction("Exposes", directions) == "exposes"
    assert resolve_direction("Direction", directions) == "depends_on"
    assert resolve_direction("Related components", directions) == "depends_on"


def test_missing_file_yields_empty(tmp_path):
    directions = load_field_directions(tmp_path / "nope.yaml")
    assert directions == {}
    assert resolve_direction("Exposes", directions) is None


def test_load_normalises_config_entries(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text("exposes: [Provides, Publishes]\ndepends_on: [Consumers]\n", encoding="utf-8")
    directions = load_field_directions(p)
    assert resolve_direction("provides", directions) == "exposes"
    assert resolve_direction("consumer", directions) == "depends_on"
