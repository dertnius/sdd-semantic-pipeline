"""Tests for extract_prose (pure regex; spaCy path inert without a model)."""

from __future__ import annotations

from sdd_pipeline.extract_prose import build_prose_inventory, extract_prose
from sdd_pipeline.models import ContentBlock, ContentType, DocumentMetadata, DocumentModel, Section


def _by_text(records):
    return {r.text: r for r in records}


def test_allcaps_and_snake_case():
    recs = _by_text(extract_prose("s", "The AUTH_SERVICE talks to KPO."))
    assert "AUTH_SERVICE" in recs and recs["AUTH_SERVICE"].source == "allcaps_regex"
    assert "KPO" in recs


def test_backtick_tokens():
    recs = _by_text(extract_prose("s", "Run `order-service` then `kubectl apply`."))
    assert "order-service" in recs
    assert recs["order-service"].source in {"backtick_regex", "prose"}


def test_pascal_and_kebab_multiword_only():
    recs = _by_text(extract_prose("s", "KubernetesPodOperator uses the inventory-service."))
    assert "KubernetesPodOperator" in recs
    assert "inventory-service" in recs
    # A single lowercase word is not a kebab/pascal entity.
    assert "uses" not in recs


def test_allcaps_stoplist_and_min_length():
    recs = _by_text(extract_prose("s", "TODO: NOTE this OK fix the DB."))
    assert "TODO" not in recs and "NOTE" not in recs and "OK" not in recs


def test_confidence_below_one():
    recs = extract_prose("s", "AUTH_SERVICE and `code` and Some-Thing")
    assert recs and all(r.confidence < 1.0 for r in recs)
    assert all(r.field == "" for r in recs)  # unbucketed prose


def test_runs_without_spacy_model():
    # Must not raise even though no spaCy model is installed.
    assert isinstance(extract_prose("s", "plain text with ACME_CORP"), list)


def test_named_entities_inert_without_spacy():
    from sdd_pipeline.extract_prose import _named_entities

    # No spaCy model installed → empty, never raises (mirrors _noun_chunks).
    assert _named_entities("Ada Lovelace works at Acme in London on 2024-01-01.") == []


def test_enable_ner_false_emits_no_ner_records():
    recs = extract_prose("s", "Ada Lovelace works at Acme.", enable_ner=False)
    assert all(not r.field.startswith("ner:") for r in recs)


def test_build_prose_inventory_keys_by_section():
    sec = Section(
        level=1,
        title="Overview",
        section_id="ov",
        breadcrumb=["Overview"],
        blocks=[ContentBlock("b", ContentType.PARAGRAPH, "The PAYMENT_SVC is core.")],
    )
    doc = DocumentModel(doc_id="d", metadata=DocumentMetadata(title="t"), root_sections=[sec])
    inv = build_prose_inventory(doc)
    assert "ov" in inv
    assert any(r.text == "PAYMENT_SVC" for r in inv["ov"])


def test_backtick_does_not_span_newline():
    # A stray / unbalanced backtick must not let one match swallow a newline
    # (and with it a whole code block) — that was the raw_entities pollution.
    recs = extract_prose("s", "Open `start\nmiddle\nend` close")
    assert all("\n" not in r.text for r in recs)


def test_top_level_code_block_not_mined():
    # A top-level CODE block is excluded from prose mining; the paragraph beside
    # it is still mined.
    sec = Section(
        level=1,
        title="X",
        section_id="x",
        breadcrumb=["X"],
        blocks=[
            ContentBlock("p", ContentType.PARAGRAPH, "The PAYMENT_SVC is core."),
            ContentBlock("c", ContentType.CODE, "```python\nDocumentModel.run(SECRET_KEY)\n```"),
        ],
    )
    doc = DocumentModel(doc_id="d", metadata=DocumentMetadata(title="t"), root_sections=[sec])
    texts = {r.text for r in build_prose_inventory(doc).get("x", [])}
    assert "PAYMENT_SVC" in texts
    assert "DocumentModel" not in texts and "SECRET_KEY" not in texts


def test_nested_code_in_list_not_mined():
    # structural.py folds code nested in a list item into the LIST block text,
    # fences and all. That code must not be prose-mined, but a prose `inline`
    # token in the same block must be.
    list_text = (
        "1. Call `InlineThing` like so:\n   ```python\n   NestedClass.run(DEEP_CONST)\n   ```"
    )
    sec = Section(
        level=1,
        title="Usage",
        section_id="u",
        breadcrumb=["Usage"],
        blocks=[ContentBlock("b", ContentType.LIST, list_text)],
    )
    doc = DocumentModel(doc_id="d", metadata=DocumentMetadata(title="t"), root_sections=[sec])
    texts = {r.text for r in build_prose_inventory(doc).get("u", [])}
    assert "InlineThing" in texts
    assert "NestedClass" not in texts and "DEEP_CONST" not in texts
