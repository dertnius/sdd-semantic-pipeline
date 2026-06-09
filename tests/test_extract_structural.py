"""Tests for extract_structural (pure — Sections built directly, no pandoc)."""

from __future__ import annotations

from sdd_pipeline.extract_structural import build_structural_inventory, extract_structural
from sdd_pipeline.models import ContentBlock, ContentType, DocumentMetadata, DocumentModel, Section


def _table_section(section_id: str, table_text: str) -> Section:
    return Section(
        level=1,
        title=section_id,
        section_id=section_id,
        breadcrumb=[section_id],
        blocks=[ContentBlock(block_id="b0", content_type=ContentType.TABLE, text=table_text)],
    )


def test_wide_table_emits_record_per_cell_with_column_field():
    text = "| Service | Owns DB |\n| --- | --- |\n| order-service | orders |"
    recs = extract_structural(_table_section("s1", text))
    by = {(r.field, r.text) for r in recs}
    assert ("service", "order-service") in by
    # "Owns DB" → "own db": the naive singulariser strips the trailing 's' on
    # "owns". Harmless — it is applied identically to template and document.
    assert ("own db", "orders") in by
    assert all(r.source == "table_cell" and r.confidence == 1.0 for r in recs)


def test_field_follows_header_name_not_position():
    # Same data, columns reordered → field labels track the header, not the index.
    a = extract_structural(_table_section("s", "| Service | Owns DB |\n|---|---|\n| os | db1 |"))
    b = extract_structural(_table_section("s", "| Owns DB | Service |\n|---|---|\n| db1 | os |"))
    assert {(r.field, r.text) for r in a} == {(r.field, r.text) for r in b}


def test_key_value_table_field_is_col0_value_is_col1():
    text = (
        "|  |  |\n| --- | --- |\n"
        "| Description | An order service |\n"
        "| Related components | payment-service, inventory-service |"
    )
    recs = extract_structural(_table_section("s2", text))
    fields = {r.field: r.text for r in recs}
    assert fields["description"] == "An order service"
    assert fields["related component"] == "payment-service, inventory-service"


def test_placeholder_and_empty_cells_skipped():
    text = (
        "|  |  |\n| --- | --- |\n"
        "| Description | [Describe the component] |\n"  # placeholder → skip
        "| Notes |  |"  # empty value → skip
    )
    assert extract_structural(_table_section("s3", text)) == []


def test_escaped_pipe_in_cell_preserved():
    text = "| Field | Value |\n|---|---|\n| range | a \\| b |"
    recs = extract_structural(_table_section("s", text))
    assert any(r.text == "a | b" for r in recs)


def test_build_inventory_keys_by_section_and_skips_empty():
    s_with = _table_section("has", "| A |\n|---|\n| v |")
    s_without = Section(level=1, title="x", section_id="empty", breadcrumb=["x"])
    doc = DocumentModel(
        doc_id="d", metadata=DocumentMetadata(title="t"), root_sections=[s_with, s_without]
    )
    inv = build_structural_inventory(doc)
    assert "has" in inv and "empty" not in inv
    assert inv["has"][0].text == "v"
