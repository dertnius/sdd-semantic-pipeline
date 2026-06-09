"""Tests for template_taxonomy: pipe-table parsing, orientation, extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdd_pipeline.template_taxonomy import (
    extract_taxonomy,
    fields_and_orientation,
    parse_pipe_table,
    to_canonical_json,
)

TEMPLATE = Path(__file__).resolve().parent.parent / "docs" / "template" / "template.md"


# ── pipe-table parser (pure, no pandoc) ────────────────────────────────────────


def test_parse_wide_table_header_and_body():
    text = "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    header, body = parse_pipe_table(text)
    assert header == ["A", "B"]
    assert body == [["1", "2"], ["3", "4"]]


def test_parse_unescapes_pipe():
    text = "| A | B |\n| --- | --- |\n| x \\| y | z |"
    _header, body = parse_pipe_table(text)
    assert body == [["x | y", "z"]]


def test_parse_key_value_table_empty_header():
    text = "|  |  |\n| --- | --- |\n| Description | [Describe it] |\n| Notes | [Put notes] |"
    header, body = parse_pipe_table(text)
    assert header == ["", ""]
    assert body[0] == ["Description", "[Describe it]"]


# ── orientation + field extraction ─────────────────────────────────────────────


def test_wide_orientation_uses_header_skips_body():
    header, body = ["Priority", "Quality attribute", "Measurable metric"], [["", "x", "y"]]
    fields, orient = fields_and_orientation(header, body)
    assert orient == "wide"
    assert fields == ["priority", "quality attribute", "measurable metric"]


def test_key_value_orientation_uses_col0_skips_placeholders():
    header = ["", ""]
    body = [
        ["Description", "[Describe the component]"],
        ["Technology Stack", "[List frameworks]"],
        ["Related components", "[List related components]"],
    ]
    fields, orient = fields_and_orientation(header, body)
    assert orient == "key_value"
    assert fields == ["description", "technology stack", "related component"]


def test_key_value_skips_empty_first_column():
    fields, orient = fields_and_orientation(["", ""], [["", "value"], ["Notes", "[x]"]])
    assert orient == "key_value"
    assert fields == ["note"]


# ── full extraction against the real template (needs pandoc) ───────────────────


@pytest.mark.slow
def test_extract_taxonomy_real_template():
    taxonomy = extract_taxonomy(TEMPLATE)

    # Key-value Solution Component table → fields from body col 0.
    assert "solution component 1" in taxonomy
    sc = taxonomy["solution component 1"]
    assert sc["orientation"] == "key_value"
    assert set(sc["fields"]) == {
        "description",
        "technology stack",
        "related component",
        "covered functional requirement",
        "note",
    }

    # Wide Quality Attributes table → fields from header.
    assert taxonomy["quality attribute"]["orientation"] == "wide"
    assert "measurable metric" in taxonomy["quality attribute"]["fields"]


@pytest.mark.slow
def test_extract_taxonomy_never_leaks_body_sample_values():
    # Body-row sample values from wide tables must never appear as fields.
    blob = to_canonical_json(extract_taxonomy(TEMPLATE)).lower()
    for leaked in ["fhir", "transaction hub", "john smith", "conceptual integrity"]:
        assert leaked not in blob


@pytest.mark.slow
def test_extract_taxonomy_is_deterministic():
    a = to_canonical_json(extract_taxonomy(TEMPLATE))
    b = to_canonical_json(extract_taxonomy(TEMPLATE))
    assert a == b
