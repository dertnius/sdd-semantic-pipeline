"""Tests for sdd_pipeline.models."""

from __future__ import annotations

import json

from sdd_pipeline.models import (
    ContentBlock,
    ContentType,
    DocumentMetadata,
    DocumentModel,
    SectionType,
    SemanticChunk,
)


class TestContentBlock:
    def test_paragraph_defaults(self):
        block = ContentBlock(block_id="b1", content_type=ContentType.PARAGRAPH, text="Hello.")
        assert block.language is None
        assert block.raw is None

    def test_code_block_with_language(self):
        block = ContentBlock(
            block_id="b2",
            content_type=ContentType.CODE,
            text="SELECT 1",
            language="sql",
        )
        assert block.language == "sql"
        assert block.content_type == ContentType.CODE


class TestContentTypeEnum:
    def test_all_values_are_strings(self):
        for ct in ContentType:
            assert isinstance(ct.value, str)

    def test_round_trip(self):
        assert ContentType("code") == ContentType.CODE
        assert ContentType("paragraph") == ContentType.PARAGRAPH


class TestSectionType:
    def test_all_values_are_strings(self):
        for st in SectionType:
            assert isinstance(st.value, str)


class TestDocumentModel:
    def test_iter_sections_flat(self, sample_document_model: DocumentModel):
        all_sections = sample_document_model.iter_sections()
        # 1 root + 5 subsections
        assert len(all_sections) >= 5

    def test_iter_sections_includes_root(self, sample_document_model: DocumentModel):
        sections = sample_document_model.iter_sections()
        root = sample_document_model.root_sections[0]
        assert root in sections

    def test_iter_sections_empty_doc(self):
        doc = DocumentModel(
            doc_id="empty",
            metadata=DocumentMetadata(title="empty"),
        )
        assert doc.iter_sections() == []


class TestSemanticChunk:
    """Tests for SemanticChunk serialisation and embed-text generation."""

    def _make_chunk(self, **overrides) -> SemanticChunk:
        defaults = {
            "chunk_id": "c1",
            "doc_id": "d1",
            "breadcrumb": ["Service", "Overview"],
            "content": "This is the overview.",
            "content_type": ContentType.PARAGRAPH,
            "language": None,
            "section_type": SectionType.OVERVIEW,
            "entities": [],
            "tags": [],
            "depends_on": [],
            "exposes": [],
            "space": "PLATFORM",
            "labels": [],
        }
        defaults.update(overrides)
        return SemanticChunk(**defaults)

    def test_to_embed_text_contains_section_type(self):
        chunk = self._make_chunk()
        text = chunk.to_embed_text()
        assert "[overview]" in text

    def test_ner_metadata_excluded_from_vector_but_kept_in_dict(self):
        # spaCy NER facets are metadata/display only — never the embed vector.
        chunk = self._make_chunk(metadata={"ner:person": ["Ada Lovelace"], "ner:org": ["Acme"]})
        assert "Ada Lovelace" not in chunk.to_embed_text()
        assert "Acme" not in chunk.to_embed_text()
        assert chunk.to_dict()["metadata"]["ner:person"] == ["Ada Lovelace"]

    def test_to_embed_text_contains_breadcrumb(self):
        chunk = self._make_chunk(breadcrumb=["Root", "Child"])
        text = chunk.to_embed_text()
        assert "Root > Child" in text

    def test_to_embed_text_contains_content(self):
        chunk = self._make_chunk(content="Special content.")
        text = chunk.to_embed_text()
        assert "Special content." in text

    def test_to_metadata_all_scalar_values(self):
        chunk = self._make_chunk(
            entities=["ServiceA"],
            tags=["api"],
            depends_on=["ServiceB"],
            exposes=["POST /token"],
            labels=["auth"],
            language="python",
        )
        meta = chunk.to_metadata()
        for key, val in meta.items():
            assert isinstance(val, (str, int, float, bool)), (
                f"Key '{key}' has non-scalar type {type(val).__name__}"
            )

    def test_to_metadata_required_keys_present(self):
        chunk = self._make_chunk()
        meta = chunk.to_metadata()
        for required in ("doc_id", "breadcrumb", "content_type", "section_type", "space"):
            assert required in meta, f"Missing key: {required}"

    def test_to_metadata_lists_json_encoded(self):
        chunk = self._make_chunk(entities=["A", "B"], tags=["x"])
        meta = chunk.to_metadata()
        # Lists must be JSON strings (vector-store metadata is scalar-only)
        entities = json.loads(meta["entities"])
        assert entities == ["A", "B"]
        tags = json.loads(meta["tags"])
        assert tags == ["x"]

    def test_to_metadata_none_language_becomes_empty_string(self):
        chunk = self._make_chunk(language=None)
        assert chunk.to_metadata()["language"] == ""

    def test_to_metadata_with_language(self):
        chunk = self._make_chunk(language="typescript")
        assert chunk.to_metadata()["language"] == "typescript"

    def test_embed_text_deep_breadcrumb(self):
        chunk = self._make_chunk(breadcrumb=["A", "B", "C", "D"])
        text = chunk.to_embed_text()
        assert "A > B > C > D" in text

    def test_embed_text_includes_entities(self):
        chunk = self._make_chunk(entities=["AuthService", "JWT"])
        text = chunk.to_embed_text()
        assert "keywords: AuthService, JWT" in text

    def test_embed_text_includes_tags(self):
        chunk = self._make_chunk(tags=["api", "lang:json"])
        text = chunk.to_embed_text()
        assert "tags: api, lang:json" in text

    def test_embed_text_omits_empty_segments(self):
        text = self._make_chunk().to_embed_text()
        assert "keywords:" not in text
        assert "tags:" not in text
        assert text.startswith("[overview]")

    def test_embed_text_code_lang_segment(self):
        chunk = self._make_chunk(content_type=ContentType.CODE, language="python")
        text = chunk.to_embed_text()
        assert "lang:python" in text

    def test_embed_text_code_lang_not_duplicated(self):
        chunk = self._make_chunk(
            content_type=ContentType.CODE, language="json", tags=["api", "lang:json"]
        )
        text = chunk.to_embed_text()
        # Already present via tags → no extra " | lang:json" segment.
        assert text.count("lang:json") == 1

    # ── to_dict (export) ──────────────────────────────────────────────────────

    def test_to_dict_has_expected_keys(self):
        d = self._make_chunk().to_dict()
        assert set(d) == {
            "chunk_id",
            "doc_id",
            "breadcrumb",
            "content",
            "content_type",
            "language",
            "section_type",
            "genre",
            "entities",
            "tags",
            "depends_on",
            "exposes",
            "space",
            "labels",
            "title",
            "source_url",
            "metadata",
            "embed_text",
        }

    def test_to_dict_enums_serialized_as_values(self):
        d = self._make_chunk(content_type=ContentType.CODE, section_type=SectionType.API).to_dict()
        assert d["content_type"] == "code"
        assert d["section_type"] == "api"
        assert type(d["content_type"]) is str

    def test_to_dict_none_language_is_null(self):
        # Contrast with to_metadata(), which maps None -> "".
        assert self._make_chunk(language=None).to_dict()["language"] is None

    def test_to_dict_with_language(self):
        assert self._make_chunk(language="python").to_dict()["language"] == "python"

    def test_to_dict_lists_preserved_as_arrays(self):
        d = self._make_chunk(
            breadcrumb=["A", "B"], entities=["X"], tags=["t"], labels=["l"]
        ).to_dict()
        assert d["breadcrumb"] == ["A", "B"]
        assert d["entities"] == ["X"]
        assert d["tags"] == ["t"]
        assert d["labels"] == ["l"]
        assert isinstance(d["entities"], list)  # not a JSON-encoded string

    def test_to_dict_embed_text_matches(self):
        chunk = self._make_chunk(entities=["JWT"], tags=["overview"])
        assert chunk.to_dict()["embed_text"] == chunk.to_embed_text()

    def test_to_dict_json_round_trips(self):
        d = self._make_chunk(entities=["A"], language="json").to_dict()
        assert json.loads(json.dumps(d)) == d

    # ── provenance (title / source_url) ───────────────────────────────────────

    def test_provenance_defaults_empty(self):
        chunk = self._make_chunk()
        assert chunk.title == ""
        assert chunk.source_url == ""

    def test_to_dict_carries_provenance(self):
        d = self._make_chunk(title="AIP-107", source_url="https://example/aip-107").to_dict()
        assert d["title"] == "AIP-107"
        assert d["source_url"] == "https://example/aip-107"

    def test_to_metadata_carries_provenance_as_scalars(self):
        meta = self._make_chunk(title="AIP-107", source_url="https://example/x").to_metadata()
        assert meta["title"] == "AIP-107"
        assert meta["source_url"] == "https://example/x"
        assert isinstance(meta["title"], str)
        assert isinstance(meta["source_url"], str)

    # ── embed_text hygiene (vector quality) ───────────────────────────────────

    def test_embed_text_drops_prefix_for_content_type(self):
        text = self._make_chunk(
            section_type=SectionType.CONTENT, breadcrumb=["REPLACE:"]
        ).to_embed_text()
        assert "[content]" not in text
        assert text.startswith("REPLACE:")

    def test_embed_text_keeps_prefix_for_real_type(self):
        text = self._make_chunk(section_type=SectionType.DECISION).to_embed_text()
        assert text.startswith("[decision]")

    def test_embed_text_drops_section_type_tag_echo(self):
        # extract_tags always puts section_type.value first; it must not be
        # re-embedded since the prefix already carries it.
        text = self._make_chunk(
            section_type=SectionType.API, tags=["api", "lang:python"]
        ).to_embed_text()
        assert "tags: lang:python" in text
        assert "tags: api" not in text

    def test_embed_text_dedups_keyword_matching_breadcrumb(self):
        text = self._make_chunk(
            section_type=SectionType.CONTENT, breadcrumb=["REPLACE:"], entities=["REPLACE"]
        ).to_embed_text()
        assert "keywords:" not in text  # only entity equalled the breadcrumb token

    def test_embed_text_drops_untrusted_lang(self):
        # A real language passes; an unknown brush is dropped from the vector.
        ok = self._make_chunk(content_type=ContentType.CODE, language="python").to_embed_text()
        assert "lang:python" in ok
        bad = self._make_chunk(content_type=ContentType.CODE, language="cobolish").to_embed_text()
        assert "lang:cobolish" not in bad

    def test_embed_text_drops_untrusted_lang_tag(self):
        text = self._make_chunk(tags=["lang:confluence"]).to_embed_text()
        assert "lang:confluence" not in text

    def test_embed_text_summarizes_table(self):
        table = "| Id | Name |\n| --- | --- |\n| a1 | x |\n| b2 | y |\n| c3 | z |"
        chunk = self._make_chunk(content_type=ContentType.TABLE, content=table)
        text = chunk.to_embed_text()
        assert "| Id | Name |" in text  # header kept
        assert "(table, 3 data rows)" in text
        assert "a1" not in text and "c3" not in text  # data cells not embedded
        # Full table is still preserved for display/export.
        assert chunk.to_dict()["content"] == table
