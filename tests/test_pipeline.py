"""
Tests for sdd_pipeline.pipeline.

Unit tests inject mocked embedder and store so they run without pandoc or
any ML model.  Integration tests are gated by ``@pytest.mark.slow`` and are
skipped unless pandoc is available.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.models import (
    ContentType,
    DocumentMetadata,
    DocumentModel,
    SectionType,
    SemanticChunk,
)
from sdd_pipeline.pipeline import SemanticPipeline, _stable_doc_id
from sdd_pipeline.vocabulary import load_vocabulary, save_vocabulary

# ── Helper factories ──────────────────────────────────────────────────────────


def _mock_embedder(n_dims: int = 3) -> MagicMock:
    embedder = MagicMock()
    embedder.embed_chunks.side_effect = lambda chunks: [[0.0] * n_dims] * len(chunks)
    embedder.embed_query.return_value = [0.0] * n_dims
    return embedder


def _mock_store() -> MagicMock:
    store = MagicMock()
    store.count = 0
    return store


def _make_pipeline(tmp_path: Path, **config_overrides) -> SemanticPipeline:
    config = PipelineConfig(
        chroma_persist_dir=str(tmp_path / "chroma"),
        embedding_model="all-MiniLM-L6-v2",
        **config_overrides,
    )
    return SemanticPipeline(
        config=config,
        embedding_model=_mock_embedder(),
        vector_store=_mock_store(),
    )


# ── _stable_doc_id ────────────────────────────────────────────────────────────


class TestStableDocId:
    def test_returns_12_chars(self, tmp_path: Path):
        assert len(_stable_doc_id(tmp_path / "doc.md")) == 12

    def test_same_path_same_id(self, tmp_path: Path):
        path = tmp_path / "doc.md"
        assert _stable_doc_id(path) == _stable_doc_id(path)

    def test_different_paths_different_ids(self, tmp_path: Path):
        a = _stable_doc_id(tmp_path / "a.md")
        b = _stable_doc_id(tmp_path / "b.md")
        assert a != b


# ── Lazy property initialisation ──────────────────────────────────────────────


class TestLazyProperties:
    def test_embedder_not_created_at_init(self, tmp_path: Path):
        pipeline = SemanticPipeline(config=PipelineConfig(chroma_persist_dir=str(tmp_path)))
        assert pipeline._embedder is None

    def test_store_not_created_at_init(self, tmp_path: Path):
        pipeline = SemanticPipeline(config=PipelineConfig(chroma_persist_dir=str(tmp_path)))
        assert pipeline._store is None

    def test_injected_embedder_used_directly(self, tmp_path: Path):
        mock = _mock_embedder()
        pipeline = SemanticPipeline(
            config=PipelineConfig(chroma_persist_dir=str(tmp_path)),
            embedding_model=mock,
        )
        assert pipeline.embedder is mock

    def test_injected_store_used_directly(self, tmp_path: Path):
        mock = _mock_store()
        pipeline = SemanticPipeline(
            config=PipelineConfig(chroma_persist_dir=str(tmp_path)),
            vector_store=mock,
        )
        assert pipeline.store is mock


# ── process_file ─────────────────────────────────────────────────────────────


class TestProcessFile:
    def test_calls_all_stages(self, tmp_path: Path, sample_md_file: Path):
        pipeline = _make_pipeline(tmp_path)

        with (
            patch("sdd_pipeline.pipeline.generate_ast") as mock_ast,
            patch("sdd_pipeline.pipeline.build_structural_model") as mock_struct,
            patch("sdd_pipeline.pipeline.enrich_document") as mock_enrich,
            patch("sdd_pipeline.pipeline.chunk_document") as mock_chunk,
        ):
            stub_doc = DocumentModel(doc_id="t1", metadata=DocumentMetadata(title="T"))
            mock_ast.return_value = {"meta": {}, "blocks": []}
            mock_struct.return_value = stub_doc
            mock_enrich.return_value = stub_doc
            mock_chunk.return_value = []

            pipeline.process_file(sample_md_file)

            mock_ast.assert_called_once()
            mock_struct.assert_called_once()
            mock_enrich.assert_called_once()
            mock_chunk.assert_called_once()

    def test_passes_from_format_to_ast(self, tmp_path: Path, sample_md_file: Path):
        pipeline = _make_pipeline(tmp_path, pandoc_from_format="commonmark")

        with (
            patch("sdd_pipeline.pipeline.generate_ast") as mock_ast,
            patch("sdd_pipeline.pipeline.build_structural_model"),
            patch("sdd_pipeline.pipeline.enrich_document") as mock_enrich,
            patch("sdd_pipeline.pipeline.chunk_document", return_value=[]),
        ):
            stub = DocumentModel(doc_id="t1", metadata=DocumentMetadata(title="T"))
            mock_ast.return_value = {"meta": {}, "blocks": []}
            mock_enrich.return_value = stub

            with patch("sdd_pipeline.pipeline.build_structural_model", return_value=stub):
                pipeline.process_file(sample_md_file)

            _, kwargs = mock_ast.call_args
            assert mock_ast.call_args[0][1] == "commonmark" or (
                kwargs.get("from_format") == "commonmark"
            )

    def test_returns_list_of_chunks(self, tmp_path: Path, sample_md_file: Path):
        pipeline = _make_pipeline(tmp_path)

        fake_chunks: list[SemanticChunk] = [
            SemanticChunk(
                chunk_id=f"c{i}",
                doc_id="d1",
                breadcrumb=["S"],
                content=f"content {i}",
                content_type=ContentType.PARAGRAPH,
                language=None,
                section_type=SectionType.CONTENT,
                entities=[],
                tags=[],
                depends_on=[],
                exposes=[],
                space="",
                labels=[],
            )
            for i in range(4)
        ]

        with (
            patch("sdd_pipeline.pipeline.generate_ast", return_value={}),
            patch(
                "sdd_pipeline.pipeline.build_structural_model",
                return_value=DocumentModel(doc_id="t", metadata=DocumentMetadata(title="T")),
            ),
            patch(
                "sdd_pipeline.pipeline.enrich_document",
                side_effect=lambda d, **kw: d,
            ),
            patch("sdd_pipeline.pipeline.chunk_document", return_value=fake_chunks),
        ):
            result = pipeline.process_file(sample_md_file)

        assert result == fake_chunks


# ── index_file ────────────────────────────────────────────────────────────────


class TestIndexFile:
    def test_calls_embedder_and_store(self, tmp_path: Path, sample_md_file: Path):
        pipeline = _make_pipeline(tmp_path)

        with (
            patch("sdd_pipeline.pipeline.generate_ast", return_value={}),
            patch(
                "sdd_pipeline.pipeline.build_structural_model",
                return_value=DocumentModel(doc_id="t", metadata=DocumentMetadata(title="T")),
            ),
            patch("sdd_pipeline.pipeline.enrich_document", side_effect=lambda d, **kw: d),
            patch(
                "sdd_pipeline.pipeline.chunk_document",
                return_value=[
                    SemanticChunk(
                        chunk_id="c1",
                        doc_id="t",
                        breadcrumb=["S"],
                        content="x",
                        content_type=ContentType.PARAGRAPH,
                        language=None,
                        section_type=SectionType.CONTENT,
                        entities=[],
                        tags=[],
                        depends_on=[],
                        exposes=[],
                        space="",
                        labels=[],
                    )
                ],
            ),
        ):
            count = pipeline.index_file(sample_md_file)

        assert count == 1
        pipeline._embedder.embed_chunks.assert_called_once()
        pipeline._store.add_chunks.assert_called_once()
        # Provenance recorded with the dimension of the actual embedding vector.
        pipeline._store.set_provenance.assert_called_once()
        assert pipeline._store.set_provenance.call_args.kwargs["dimension"] == 3

    def test_returns_zero_for_empty_document(self, tmp_path: Path, sample_md_file: Path):
        pipeline = _make_pipeline(tmp_path)

        with (
            patch("sdd_pipeline.pipeline.generate_ast", return_value={}),
            patch(
                "sdd_pipeline.pipeline.build_structural_model",
                return_value=DocumentModel(doc_id="t", metadata=DocumentMetadata(title="T")),
            ),
            patch("sdd_pipeline.pipeline.enrich_document", side_effect=lambda d, **kw: d),
            patch("sdd_pipeline.pipeline.chunk_document", return_value=[]),
        ):
            count = pipeline.index_file(sample_md_file)

        assert count == 0
        pipeline._store.add_chunks.assert_not_called()


# ── index_directory ───────────────────────────────────────────────────────────


class TestIndexDirectory:
    def test_returns_count_per_file(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for i in range(3):
            (docs_dir / f"doc{i}.md").write_text(f"# Doc {i}\n", encoding="utf-8")

        pipeline = _make_pipeline(tmp_path)

        with patch.object(pipeline, "index_file", return_value=5):
            result = pipeline.index_directory(docs_dir)

        assert len(result) == 3
        assert all(v == 5 for v in result.values())

    def test_error_returns_minus_one(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "bad.md").write_text("# Bad\n", encoding="utf-8")

        pipeline = _make_pipeline(tmp_path)

        with patch.object(pipeline, "index_file", side_effect=RuntimeError("boom")):
            result = pipeline.index_directory(docs_dir)

        assert list(result.values()) == [-1]


# ── index_directory: cross-corpus scan ────────────────────────────────────────


def _corpus_doc(doc_id: str, title: str, body: str) -> DocumentModel:
    from sdd_pipeline.models import ContentBlock, Section

    return DocumentModel(
        doc_id=doc_id,
        metadata=DocumentMetadata(title=title, space="SP"),
        root_sections=[
            Section(
                level=1,
                title=title,
                section_id="s1",
                breadcrumb=[title],
                blocks=[ContentBlock(block_id="b1", content_type=ContentType.PARAGRAPH, text=body)],
            )
        ],
    )


class TestCrossCorpusScan:
    def test_term_from_doc_a_tags_doc_b(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "a.md").write_text("# A\n", encoding="utf-8")
        (docs_dir / "b.md").write_text("# B\n", encoding="utf-8")
        vocab_path = tmp_path / "vocab.json"

        # `settlement-engine` is backtick-quoted only in A; B mentions it in bare
        # prose the precise entity patterns would miss without the shared vocab.
        doc_a = _corpus_doc("da", "A", "The `settlement-engine` clears trades.")
        doc_b = _corpus_doc("db", "B", "Downstream consumers call settlement-engine directly.")
        by_name = {"a.md": doc_a, "b.md": doc_b}

        pipeline = _make_pipeline(tmp_path, entity_vocab_path=str(vocab_path))
        with patch.object(pipeline, "parse_file", side_effect=lambda p: by_name[p.name]):
            pipeline.index_directory(docs_dir)

        # Collect every indexed chunk from the mock store, grouped by doc.
        indexed = [c for call in pipeline._store.add_chunks.call_args_list for c in call.args[0]]
        b_entities = {e for c in indexed if c.doc_id == "db" for e in c.entities}
        assert "settlement-engine" in b_entities

    def test_persists_and_accumulates_vocabulary(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "a.md").write_text("# A\n", encoding="utf-8")
        vocab_path = tmp_path / "vocab.json"
        save_vocabulary(vocab_path, ["PriorTerm"])  # seed from a previous run

        doc_a = _corpus_doc("da", "A", "We apply the CQRS pattern.")
        pipeline = _make_pipeline(tmp_path, entity_vocab_path=str(vocab_path))
        with patch.object(pipeline, "parse_file", side_effect=lambda p: doc_a):
            pipeline.index_directory(docs_dir)

        vocab = load_vocabulary(vocab_path)
        assert "CQRS" in vocab  # freshly discovered
        assert "PriorTerm" in vocab  # accumulated across runs


class TestScanAndPersist:
    def test_returns_vocab_parsed_failed_and_writes_file(self, tmp_path: Path):
        vocab_path = tmp_path / "vocab.json"
        good = _corpus_doc("dg", "Good", "We apply the CQRS pattern.")
        # parse_file raises for the "bad" path → it lands in `failed`, not `parsed`.
        by_name = {"good.md": good}

        def fake_parse(p: Path):
            if p.name not in by_name:
                raise RuntimeError("parse boom")
            return by_name[p.name]

        pipeline = _make_pipeline(tmp_path, entity_vocab_path=str(vocab_path))
        with patch.object(pipeline, "parse_file", side_effect=fake_parse):
            vocab, parsed, failed = pipeline.scan_and_persist(
                [tmp_path / "good.md", tmp_path / "bad.md"]
            )

        assert "CQRS" in vocab
        assert [src.name for src, _ in parsed] == ["good.md"]
        assert [p.name for p in failed] == ["bad.md"]
        # Persisted file matches the returned vocabulary; no model was loaded.
        assert load_vocabulary(vocab_path) == vocab
        assert pipeline._embedder.embed_chunks.call_count == 0

    def test_seeds_from_entity_terms_and_prior_file(self, tmp_path: Path):
        vocab_path = tmp_path / "vocab.json"
        save_vocabulary(vocab_path, ["PriorTerm"])
        doc = _corpus_doc("d", "D", "plain prose")
        pipeline = _make_pipeline(
            tmp_path, entity_vocab_path=str(vocab_path), entity_terms=["SeedTerm"]
        )
        with patch.object(pipeline, "parse_file", side_effect=lambda p: doc):
            vocab, _, _ = pipeline.scan_and_persist([tmp_path / "d.md"])
        assert {"PriorTerm", "SeedTerm"} <= set(vocab)


# ── search ────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_delegates_to_store(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.search("how does token refresh work?", n_results=3)

        pipeline._embedder.embed_query.assert_called_once_with("how does token refresh work?")
        pipeline._store.search.assert_called_once()

    def test_passes_filters(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.search("q", section_type=SectionType.API, space="PLATFORM")
        _, kwargs = pipeline._store.search.call_args
        assert kwargs["section_type"] == SectionType.API
        assert kwargs["space"] == "PLATFORM"

    def test_dense_only_does_not_fetch_corpus(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.search("q", hybrid=False)
        pipeline._store.get_corpus.assert_not_called()

    def test_search_raises_on_provenance_mismatch(self, tmp_path: Path):
        # Config is local (all-MiniLM via _make_pipeline); index claims azure.
        pipeline = _make_pipeline(tmp_path)
        pipeline._store.get_provenance.return_value = {
            "embedding_provider": "azure",
            "embedding_model": "text-embedding-3-small",
        }
        with pytest.raises(ValueError, match="provenance mismatch"):
            pipeline.search("q")

    def test_search_proceeds_when_provenance_absent(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        pipeline._store.get_provenance.return_value = {}  # legacy index
        pipeline.search("q")  # must not raise
        pipeline._store.search.assert_called_once()

    def test_search_proceeds_when_provenance_matches(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        pipeline._store.get_provenance.return_value = {
            "embedding_provider": "local",
            "embedding_model": "all-MiniLM-L6-v2",
        }
        pipeline.search("q")  # matches config → no raise
        pipeline._store.search.assert_called_once()

    def test_hybrid_fuses_lexical_signal(self, tmp_path: Path):
        from sdd_pipeline.vector_store import SearchResult

        # Dense puts the topical meta-sentence first; the real answer second.
        meta = SearchResult(
            "meta",
            "Following the setup section instructions.",
            {"breadcrumb": "FE > Setup"},
            distance=0.35,
        )
        steps = SearchResult(
            "steps", "Install VSCode and connect over SSH.", {"breadcrumb": "Setup"}, distance=0.46
        )
        pipeline = _make_pipeline(tmp_path, hybrid_search=True)
        pipeline._store.search.return_value = [meta, steps]
        pipeline._store.get_corpus.return_value = [meta, steps]

        results = pipeline.search("install vscode", n_results=2)

        # BM25 lifts the chunk that literally contains "install vscode".
        assert results[0].chunk_id == "steps"
        assert results[0].fused_score is not None
        assert results[0].score == results[0].fused_score
        pipeline._store.get_corpus.assert_called_once()


# ── Slow integration (requires real pandoc) ───────────────────────────────────


def _pandoc_ok() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
class TestProcessFileIntegration:
    def test_produces_non_empty_chunks(self, tmp_path: Path, sample_md_file: Path):
        pipeline = _make_pipeline(tmp_path)
        chunks = pipeline.process_file(sample_md_file)
        assert len(chunks) > 0

    def test_all_chunks_have_breadcrumb(self, tmp_path: Path, sample_md_file: Path):
        pipeline = _make_pipeline(tmp_path)
        for chunk in pipeline.process_file(sample_md_file):
            assert len(chunk.breadcrumb) >= 1

    def test_section_types_are_classified(self, tmp_path: Path, sample_md_file: Path):
        pipeline = _make_pipeline(tmp_path)
        chunks = pipeline.process_file(sample_md_file)
        types = {c.section_type for c in chunks}
        # The sample document has overview, architecture, api, decision, deployment
        assert SectionType.OVERVIEW in types or SectionType.ARCHITECTURE in types
