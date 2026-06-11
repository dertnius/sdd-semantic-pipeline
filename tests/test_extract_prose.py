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
