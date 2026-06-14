"""Tests for the header normalisation spec (header_norm.normalise_header)."""

from __future__ import annotations

import pytest

from sdd_pipeline.header_norm import normalise_header


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Consumer", "consumer"),
        ("consumers", "consumer"),
        ("Consumer (system)", "consumer"),
        ("Client/Consumer", "client"),
        ("  Stakeholder   Role  ", "stakeholder role"),
        ("Related components", "related component"),
        ("Quality attribute", "quality attribute"),
        ("Measurable metric", "measurable metric"),
        ("Technology Stack", "technology stack"),
        ("Notes", "note"),
        ("Abbreviation or Acronym", "abbreviation or acronym"),
    ],
)
def test_normalise_examples(raw, expected):
    assert normalise_header(raw) == expected


def test_consumer_variants_collapse():
    variants = {"Consumer", "consumers", "Consumer (system)"}
    assert {normalise_header(v) for v in variants} == {"consumer"}


def test_empty_and_blank_become_empty_string():
    assert normalise_header("") == ""
    assert normalise_header("   ") == ""
    assert normalise_header("(optional)") == ""  # parenthetical-only header cell


def test_keep_s_endings_not_stripped():
    # 'status'/'analysis' must not be mangled to 'statu'/'analysi'.
    assert normalise_header("Status") == "status"
    assert normalise_header("Analysis") == "analysis"


def test_real_template_component_labels_are_stable():
    # The Solution Component key-value table's col-0 labels (from docs/notes/SPIKE_FINDINGS.md).
    labels = [
        "Description",
        "Technology Stack",
        "Related components",
        "Covered functional requirements",
        "Notes",
    ]
    out = [normalise_header(x) for x in labels]
    assert out == [
        "description",
        "technology stack",
        "related component",
        "covered functional requirement",
        "note",
    ]
    # Idempotent: normalising twice changes nothing.
    assert [normalise_header(x) for x in out] == out
