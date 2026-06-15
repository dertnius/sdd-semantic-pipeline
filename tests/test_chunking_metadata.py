"""Chunk-level metadata scoping (raw_entities is per-chunk; named fields are not)."""

from __future__ import annotations

from sdd_pipeline.chunking import chunk_document
from sdd_pipeline.models import ContentBlock, ContentType, DocumentMetadata, DocumentModel, Section


def test_raw_entities_scoped_per_chunk():
    sec = Section(
        level=1,
        title="S",
        section_id="s",
        breadcrumb=["S"],
        blocks=[
            ContentBlock("b1", ContentType.PARAGRAPH, "Alpha mentions FOO_SVC here."),
            ContentBlock("b2", ContentType.PARAGRAPH, "Beta mentions BAR_SVC here."),
        ],
        metadata={"raw_entities": ["FOO_SVC", "BAR_SVC"], "technology stack": ["Go 1.22"]},
    )
    doc = DocumentModel(doc_id="d", metadata=DocumentMetadata(title="t"), root_sections=[sec])

    chunks = chunk_document(doc)  # merge off → one chunk per paragraph
    assert len(chunks) == 2

    foo = next(c for c in chunks if "FOO_SVC" in c.content)
    bar = next(c for c in chunks if "BAR_SVC" in c.content)

    # raw_entities holds only the term that appears in this chunk's own text.
    assert foo.metadata["raw_entities"] == ["FOO_SVC"]
    assert bar.metadata["raw_entities"] == ["BAR_SVC"]

    # Named inventory fields stay section-level (a table applies to the whole section).
    assert foo.metadata["technology stack"] == ["Go 1.22"]
    assert bar.metadata["technology stack"] == ["Go 1.22"]
