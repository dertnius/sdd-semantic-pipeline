"""Tests for sdd_pipeline.chunking."""

from __future__ import annotations

from sdd_pipeline.chunking import _split_text, chunk_document
from sdd_pipeline.models import ContentType, DocumentModel, SectionType


class TestSplitText:
    def test_short_text_unchanged(self):
        text = "Short paragraph."
        assert _split_text(text, 1000) == [text]

    def test_returns_list_of_one_for_exact_limit(self):
        text = "x" * 100
        result = _split_text(text, 100)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_long_text_split_at_paragraphs(self):
        text = ("A" * 300) + "\n\n" + ("B" * 300) + "\n\n" + ("C" * 300)
        result = _split_text(text, 400)
        assert len(result) > 1

    def test_each_chunk_respects_limit_approximately(self):
        # Some tolerance because sentence splitting may overshoot slightly
        text = " ".join([f"Sentence {i}." for i in range(200)])
        chunks = _split_text(text, 300)
        # All chunks should be reasonably bounded
        for chunk in chunks:
            assert len(chunk) <= 450, f"Chunk too large: {len(chunk)} chars"

    def test_no_empty_chunks(self):
        text = "Para1\n\n\n\nPara2\n\n"
        for chunk in _split_text(text, 20):
            assert chunk.strip()

    def test_single_very_long_word_hard_cut(self):
        text = "x" * 600  # no natural split point
        result = _split_text(text, 200)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 200


class TestChunkDocument:
    def test_produces_chunks(self, sample_document_model: DocumentModel):
        chunks = chunk_document(sample_document_model)
        assert len(chunks) > 0

    def test_all_chunks_have_non_empty_content(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            assert chunk.content.strip(), f"Empty content in chunk {chunk.chunk_id}"

    def test_all_chunk_ids_unique(self, sample_document_model: DocumentModel):
        chunks = chunk_document(sample_document_model)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_breadcrumbs_non_empty(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            assert len(chunk.breadcrumb) >= 1

    def test_breadcrumb_includes_section_title(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            last_title = chunk.breadcrumb[-1]
            assert last_title, "Last breadcrumb element should be a section title"

    def test_doc_id_inherited(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            assert chunk.doc_id == sample_document_model.doc_id

    def test_space_inherited(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            assert chunk.space == sample_document_model.metadata.space

    def test_labels_inherited(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            assert chunk.labels == sample_document_model.metadata.labels

    def test_section_type_inherited_from_enriched_section(
        self, sample_document_model: DocumentModel
    ):
        chunks = chunk_document(sample_document_model)

        api_chunks = [c for c in chunks if c.section_type == SectionType.API]
        assert len(api_chunks) >= 1

    def test_code_chunks_have_content_type_code(self, sample_document_model: DocumentModel):
        chunks = chunk_document(sample_document_model)
        code_chunks = [c for c in chunks if c.content_type == ContentType.CODE]
        assert len(code_chunks) >= 1

    def test_json_code_chunk_has_language(self, sample_document_model: DocumentModel):
        chunks = chunk_document(sample_document_model)
        json_code_chunks = [
            c for c in chunks if c.content_type == ContentType.CODE and c.language == "json"
        ]
        assert len(json_code_chunks) >= 1

    def test_embed_text_contains_breadcrumb(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            embed = chunk.to_embed_text()
            assert chunk.breadcrumb[-1] in embed

    def test_embed_text_contains_section_type(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            embed = chunk.to_embed_text()
            assert chunk.section_type.value in embed

    def test_max_chunk_chars_respected(self, sample_document_model: DocumentModel):
        small_limit = 50
        for chunk in chunk_document(sample_document_model, max_chunk_chars=small_limit):
            # Allow slight overshoot from the sentence splitter
            assert len(chunk.content) <= small_limit + 200

    def test_empty_document_returns_empty_list(self):
        from sdd_pipeline.models import DocumentMetadata

        empty_doc = DocumentModel(
            doc_id="empty",
            metadata=DocumentMetadata(title="Empty"),
        )
        assert chunk_document(empty_doc) == []

    def test_title_and_source_url_propagated(self, sample_document_model: DocumentModel):
        for chunk in chunk_document(sample_document_model):
            assert chunk.title == sample_document_model.metadata.title
            assert chunk.source_url == sample_document_model.metadata.url


# ── entity_fn (per-chunk entity scoping) ──────────────────────────────────────


class TestEntityFnScoping:
    def _two_para_doc(self) -> DocumentModel:
        from sdd_pipeline.models import ContentBlock, DocumentMetadata, Section

        section = Section(
            level=1,
            title="Root",
            section_id="s1",
            breadcrumb=["Root"],
            blocks=[
                ContentBlock(block_id="b1", content_type=ContentType.PARAGRAPH, text="alpha here"),
                ContentBlock(block_id="b2", content_type=ContentType.PARAGRAPH, text="beta here"),
            ],
            # Section-level union (what a chunk would inherit without entity_fn).
            entities=["alpha", "beta"],
        )
        return DocumentModel(
            doc_id="d1",
            metadata=DocumentMetadata(title="t"),
            root_sections=[section],
        )

    def test_entity_fn_scopes_to_chunk_content(self):
        # Extractor returns only the words actually present in the chunk text.
        def fn(text: str) -> list[str]:
            return [w for w in ("alpha", "beta") if w in text]

        chunks = chunk_document(self._two_para_doc(), entity_fn=fn)
        by_content = {c.content: c.entities for c in chunks}
        assert by_content["alpha here"] == ["alpha"]  # no "beta" bleed
        assert by_content["beta here"] == ["beta"]

    def test_without_entity_fn_inherits_section_union(self):
        chunks = chunk_document(self._two_para_doc())
        for c in chunks:
            assert c.entities == ["alpha", "beta"]  # section-level union, unchanged


# ── merge_definitions (prose + code co-located) ───────────────────────────────


class TestMergeDefinitions:
    def _instr_doc(self) -> DocumentModel:
        return _doc_with_blocks(
            [
                _block("b1", ContentType.PARAGRAPH, "REPLACE swaps a column from another file."),
                _block("b2", ContentType.CODE, "```\nFILE|REPLACE|x|y\n```"),
                _block("b3", ContentType.TABLE, "| Id |\n| --- |\n| a |"),
            ]
        )

    def test_prose_and_code_share_one_chunk(self):
        chunks = chunk_document(self._instr_doc(), merge_definitions=True)
        assert any(
            "REPLACE swaps a column" in c.content and "FILE|REPLACE|x|y" in c.content
            for c in chunks
        )

    def test_table_stays_separate(self):
        chunks = chunk_document(self._instr_doc(), merge_definitions=True)
        tables = [c for c in chunks if c.content_type == ContentType.TABLE]
        assert len(tables) == 1
        assert "FILE|REPLACE" not in tables[0].content

    def test_merge_prose_keeps_code_separate(self):
        # Contrast: plain merge_prose does NOT fold code in.
        chunks = chunk_document(self._instr_doc(), merge_prose=True)
        assert any(c.content_type == ContentType.CODE for c in chunks)
        assert not any(
            "REPLACE swaps a column" in c.content and "FILE|REPLACE|x|y" in c.content
            for c in chunks
        )


# ── embed budget + junk filtering ─────────────────────────────────────────────


class TestEmbedBudget:
    def test_embed_text_stays_within_budget(self):
        long_para = " ".join(f"Item {i} here." for i in range(120))  # ~1.6k chars, one paragraph
        doc = _doc_with_blocks([_block("b1", ContentType.PARAGRAPH, long_para)])
        budget = 800
        chunks = chunk_document(doc, embed_char_budget=budget)
        assert len(chunks) > 1  # forced to split to fit the budget
        for c in chunks:
            assert len(c.to_embed_text()) <= budget


class TestJunkFilter:
    def test_punctuation_only_block_dropped(self):
        doc = _doc_with_blocks(
            [
                _block("b1", ContentType.PARAGRAPH, "\\"),  # converter <br/> artifact
                _block("b2", ContentType.PARAGRAPH, "real content here"),
            ]
        )
        chunks = chunk_document(doc)
        assert len(chunks) == 1
        assert chunks[0].content == "real content here"

    def test_junk_dropped_in_merge_mode(self):
        doc = _doc_with_blocks(
            [
                _block("b1", ContentType.PARAGRAPH, "alpha"),
                _block("b2", ContentType.PARAGRAPH, "***"),  # no alnum
                _block("b3", ContentType.PARAGRAPH, "beta"),
            ]
        )
        chunks = chunk_document(doc, merge_prose=True)
        joined = " ".join(c.content for c in chunks)
        assert "alpha" in joined and "beta" in joined
        assert "***" not in joined


# ── merge_prose (section-level packing) ───────────────────────────────────────


def _block(block_id: str, content_type: ContentType, text: str, language=None):
    from sdd_pipeline.models import ContentBlock

    return ContentBlock(block_id=block_id, content_type=content_type, text=text, language=language)


def _doc_with_blocks(blocks) -> DocumentModel:
    from sdd_pipeline.models import DocumentMetadata, Section

    section = Section(level=1, title="Setup", section_id="s1", breadcrumb=["Setup"], blocks=blocks)
    return DocumentModel(
        doc_id="d1",
        metadata=DocumentMetadata(title="Doc", space="SP"),
        root_sections=[section],
    )


class TestMergeProse:
    def _mixed_doc(self) -> DocumentModel:
        return _doc_with_blocks(
            [
                _block("b1", ContentType.PARAGRAPH, "To use VSCode for Impala development:"),
                _block("b2", ContentType.LIST, "1. Install VSCode.\n2. Connect over SSH."),
                _block("b3", ContentType.CODE, '```json\n{"port": 8000}\n```', language="json"),
                _block("b4", ContentType.PARAGRAPH, "Then set breakpoints."),
            ]
        )

    def test_prose_blocks_merge_into_one_chunk(self):
        doc = self._mixed_doc()
        chunks = chunk_document(doc, merge_prose=True)
        prose = [c for c in chunks if c.content_type == ContentType.PARAGRAPH]
        # b1 + b2 pack together (both prose, before the code block).
        first = prose[0]
        assert "To use VSCode" in first.content
        assert "Install VSCode" in first.content

    def test_default_does_not_merge(self):
        doc = self._mixed_doc()
        chunks = chunk_document(doc)  # merge_prose defaults False
        # One chunk per block: 2 prose + 1 code + 1 prose = 4.
        assert len(chunks) == 4

    def test_code_block_stays_separate_and_keeps_language(self):
        chunks = chunk_document(self._mixed_doc(), merge_prose=True)
        code = [c for c in chunks if c.content_type == ContentType.CODE]
        assert len(code) == 1
        assert code[0].language == "json"

    def test_code_breaks_the_prose_run(self):
        # b4 is prose but comes after the code block → its own chunk, not merged
        # with b1/b2.
        chunks = chunk_document(self._mixed_doc(), merge_prose=True)
        assert any(
            "Then set breakpoints." in c.content and "Install VSCode" not in c.content
            for c in chunks
        )

    def test_ids_unique_when_merging(self):
        chunks = chunk_document(self._mixed_doc(), merge_prose=True)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_merge_respects_max_chunk_chars(self):
        doc = _doc_with_blocks(
            [_block(f"b{i}", ContentType.PARAGRAPH, "word " * 40) for i in range(6)]
        )
        for chunk in chunk_document(doc, max_chunk_chars=120, merge_prose=True):
            assert len(chunk.content) <= 120 + 200  # tolerance for splitter

    def test_merged_chunk_inherits_section_metadata(self):
        from sdd_pipeline.models import DocumentMetadata, Section

        section = Section(
            level=1,
            title="API",
            section_id="s1",
            breadcrumb=["API"],
            blocks=[
                _block("b1", ContentType.PARAGRAPH, "alpha"),
                _block("b2", ContentType.PARAGRAPH, "beta"),
            ],
            section_type=SectionType.API,
            entities=["AuthService"],
            tags=["api"],
        )
        doc = DocumentModel(
            doc_id="d1", metadata=DocumentMetadata(title="t", space="SP"), root_sections=[section]
        )
        chunk = chunk_document(doc, merge_prose=True)[0]
        assert chunk.section_type == SectionType.API
        assert chunk.entities == ["AuthService"]
        assert chunk.space == "SP"
