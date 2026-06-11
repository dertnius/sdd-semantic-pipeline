"""End-to-end: inventory-driven fields reach the chunk and its embed text."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.models import ContentBlock, ContentType, DocumentMetadata, DocumentModel, Section
from sdd_pipeline.pipeline import SemanticPipeline

CORPUS = Path(__file__).resolve().parent.parent / "eval" / "corpus"


def _doc_with_table(table_md: str) -> DocumentModel:
    section = Section(
        level=1,
        title="Integration",
        section_id="integration",
        breadcrumb=["Integration"],
        blocks=[ContentBlock("b0", ContentType.TABLE, table_md)],
    )
    return DocumentModel(doc_id="d", metadata=DocumentMetadata(title="t"), root_sections=[section])


def test_directional_table_column_reaches_chunk_and_embed_text():
    # "Consumer" is a depends_on field in config/field_directions.yaml.
    doc = _doc_with_table("| Consumer | Protocol |\n| --- | --- |\n| order-service | REST |")
    pipeline = SemanticPipeline(config=PipelineConfig())  # no embedder/store touched

    chunks = pipeline.enrich_and_chunk(doc, [])

    assert chunks, "table section should produce a chunk"
    chunk = chunks[0]
    assert "order-service" in chunk.depends_on  # routed by field name → depends_on
    assert "REST" in chunk.metadata.get("protocol", [])  # non-directional → metadata
    embed = chunk.to_embed_text()
    assert "depends on: order-service" in embed  # folded into the vector text


@pytest.mark.slow
def test_real_sad_populates_directional_fields_end_to_end():
    sad = CORPUS / "sad-retailnexus-oms.md"
    pipeline = SemanticPipeline(config=PipelineConfig())
    chunks = pipeline.process_file(sad)

    # The SAD's tables carry an "Exposes" column and a "Direction" column, both
    # mapped in field_directions.yaml — so some chunk must carry a directional field.
    assert any(c.exposes or c.depends_on for c in chunks), (
        "expected inventory-driven depends_on/exposes on at least one real chunk"
    )
    # And those signals must surface in the embed text.
    enriched = [c for c in chunks if c.depends_on or c.exposes]
    assert any(
        ("depends on:" in c.to_embed_text()) or ("exposes:" in c.to_embed_text()) for c in enriched
    )
