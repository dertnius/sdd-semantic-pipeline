"""
Pipeline orchestrator.

Composes all seven stages into a single :class:`SemanticPipeline` object that
can process individual files, index directories, and answer search queries.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .ast_parser import generate_ast
from .chunking import chunk_document
from .config import PipelineConfig
from .embeddings import EmbedderProtocol, embedder_identity, make_embedder
from .enrichment import (
    classify_document,
    enrich_document,
    extract_entities,
    extract_keyphrases,
    scan_corpus,
)
from .models import (
    EMBED_FORMAT_VERSION,
    ContentType,
    DocumentModel,
    Genre,
    SectionType,
    SemanticChunk,
)
from .quality import ChunkQualityReport, check_chunk
from .structural import build_structural_model
from .vector_store import SearchResult, VectorStoreProtocol, make_vector_store
from .vocabulary import load_vocabulary, save_vocabulary

logger = logging.getLogger(__name__)


class ChunkQualityError(RuntimeError):
    """Raised when the chunk hygiene gate blocks a document from indexing.

    A *poisoned* chunk (markup/macro residue, over-hard-cap embed text, or empty)
    means a vector would be wrong, so the whole file is blocked rather than
    quietly indexed. Disable with ``config.chunk_gate = False`` to override.
    """


def _stable_doc_id(path: Path) -> str:
    """Derive a short, stable document ID from the file path."""
    return hashlib.md5(str(path.resolve()).encode()).hexdigest()[:12]


# Sentinel provenance + vectors for a model-free (lexical/BM25) index. Chunks are stored
# with a constant unit vector so the backend accepts them; dense search never runs against
# a lexical index — ``search`` reads ``provider="lexical"`` from provenance and auto-routes
# to BM25, so no real embedding model is ever loaded for a lexical index.
_LEXICAL_PROVIDER = "lexical"
_LEXICAL_MODEL = "none"
_LEXICAL_DIM = 1


def _lexical_vectors(n: int) -> list[list[float]]:
    """Return *n* sentinel unit vectors for a vectorless (lexical) index."""
    return [[1.0] for _ in range(n)]


class SemanticPipeline:
    """
    Full Confluence-MD → semantic-search pipeline.

    Stages
    ------
    1. Read Confluence markdown file.
    2. Generate pandoc JSON AST (``ast_parser``).
    3+4. Parse AST into a structural model (``structural``).
    5. Semantically enrich sections (``enrichment``).
    6. Chunk into SemanticChunks (``chunking``).
    7. Embed and index (``embeddings`` + ``vector_store``).

    Dependencies (*embedding_model*, *vector_store*) are created lazily on
    first use so unit tests can inject lightweight mocks without side-effects.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        embedding_model: EmbedderProtocol | None = None,
        vector_store: VectorStoreProtocol | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self._embedder: EmbedderProtocol | None = embedding_model
        self._store: VectorStoreProtocol | None = vector_store

    # ── Lazy accessors ────────────────────────────────────────────────────────

    @property
    def embedder(self) -> EmbedderProtocol:
        if self._embedder is None:
            self._embedder = make_embedder(self.config)
        return self._embedder

    @property
    def store(self) -> VectorStoreProtocol:
        if self._store is None:
            self._store = make_vector_store(self.config)
        return self._store

    # ── Core pipeline ─────────────────────────────────────────────────────────

    def parse_file(self, md_path: Path) -> DocumentModel:
        """Run stages 2–4: pandoc AST → structural :class:`DocumentModel`.

        No enrichment yet, so the result can feed a cross-corpus scan before
        Stage 5. When ``config.language == "auto"``, the document's language is
        detected here and stashed on ``metadata.extra['language']`` so the later
        enrichment uses the right rule pack.
        """
        logger.info("Processing %s", md_path.name)
        doc_id = _stable_doc_id(md_path)
        ast = generate_ast(md_path, self.config.pandoc_from_format)
        model = build_structural_model(ast, doc_id=doc_id, source_path=str(md_path))
        if self.config.language == "auto":
            from .detection import detect_language

            model.metadata.extra["language"] = detect_language(self._language_sample(model))
        return model

    @staticmethod
    def _language_sample(doc: DocumentModel, *, max_chars: int = 2000) -> str:
        """Build a representative text sample (title + leading prose) for detection."""
        parts: list[str] = [doc.metadata.title]
        for section in doc.iter_sections():
            parts.append(section.title)
            parts.extend(b.text for b in section.blocks)
            if sum(len(p) for p in parts) >= max_chars:
                break
        return "\n".join(p for p in parts if p)[:max_chars]

    def _resolve_language(self, doc: DocumentModel) -> str:
        """Pick the enrichment language for *doc*: detected (auto) else configured."""
        detected = doc.metadata.extra.get("language")
        if detected:
            return str(detected)
        # No per-doc detection: an explicit code is used verbatim; bare "auto" with no
        # detection available degrades to English.
        return "en" if self.config.language == "auto" else self.config.language

    def _build_inventory(self, doc: DocumentModel):
        """Stage 3.5: merge structural (table) + prose entity records per section."""
        from .extract_prose import build_prose_inventory
        from .extract_structural import build_structural_inventory

        merged: dict[str, list] = {}
        prose_inv = build_prose_inventory(doc, enable_ner=self.config.prose_ner)
        for inv in (build_structural_inventory(doc), prose_inv):
            for section_id, records in inv.items():
                merged.setdefault(section_id, []).extend(records)
        return merged

    def enrich_and_chunk(
        self,
        doc: DocumentModel,
        entity_terms: list[str],
    ) -> list[SemanticChunk]:
        """Run stages 5–6 with a given vocabulary; section- and chunk-level
        entities share *entity_terms*. An inventory of structural + prose records
        (stage 3.5) drives depends_on/exposes/metadata field routing, unless
        ``config.inventory_enrichment`` is disabled (legacy enrichment only)."""
        language = self._resolve_language(doc)
        inventory = self._build_inventory(doc) if self.config.inventory_enrichment else None
        doc = enrich_document(
            doc, entity_terms=entity_terms, inventory=inventory, language=language
        )
        merge_prose, merge_definitions = self._resolve_merge_strategy(doc)
        keyphrase_fn = (
            (lambda t: extract_keyphrases(t, language=language))
            if self.config.prose_keyphrases
            else None
        )
        chunks = chunk_document(
            doc,
            self.config.max_chunk_chars,
            merge_prose=merge_prose,
            entity_fn=lambda t: extract_entities(t, entity_terms),
            merge_definitions=merge_definitions,
            embed_char_budget=self.config.embed_char_budget,
            keyphrase_fn=keyphrase_fn,
            overlap_sentences=self.config.chunk_overlap_sentences,
        )
        logger.info("→ %d chunks", len(chunks))
        return chunks

    def _resolve_merge_strategy(self, doc: DocumentModel) -> tuple[bool, bool]:
        """Pick ``(merge_prose, merge_definitions)`` for *doc*.

        Returns the configured flags verbatim unless ``config.doc_profile_enabled``
        is on *and* the user set neither merge flag — in which case the document
        profile chooses a default (technical→definitions, prose→prose, mixed→none).
        The profile is recorded on ``doc.metadata.extra['profile']`` either way.
        Advisory only: an explicit merge flag is always respected.
        """
        mp = self.config.chunk_merge_prose
        md = self.config.chunk_merge_definitions
        if not self.config.doc_profile_enabled:
            return mp, md

        profile = classify_document(
            doc,
            code_ratio_threshold=self.config.doc_profile_code_ratio,
            table_ratio_threshold=self.config.doc_profile_table_ratio,
        )
        doc.metadata.extra["profile"] = profile
        if mp or md:  # user opted in explicitly → respect it
            return mp, md
        if profile == "technical":
            return False, True
        if profile == "prose":
            return True, False
        return False, False  # mixed → today's default (no merge)

    def process_file(self, md_path: Path) -> list[SemanticChunk]:
        """
        Run stages 2–6 for a single markdown file.

        Returns the list of :class:`SemanticChunk` objects **without indexing**.
        Useful for inspection and unit testing.
        """
        return self.enrich_and_chunk(self.parse_file(md_path), self.config.entity_terms)

    def gate_chunks(self, chunks: list[SemanticChunk]) -> list[ChunkQualityReport]:
        """Run the hygiene invariant (Arm 1) over *chunks*, non-raising.

        Returns one :class:`ChunkQualityReport` per chunk so callers can inspect
        poison/weak findings (e.g. ``export``) without blocking. ``index_doc``
        uses this and enforces the *poison → block-the-file* rule.
        """
        return [
            check_chunk(
                c,
                embed_char_budget=self.config.embed_char_budget,
                embed_char_hard_cap=self.config.embed_char_hard_cap,
            )
            for c in chunks
        ]

    def _enforce_chunk_gate(self, chunks: list[SemanticChunk]) -> None:
        """Block the file when any chunk is poisoned (Arm 1, ``config.chunk_gate``)."""
        if not self.config.chunk_gate:
            return
        reports = self.gate_chunks(chunks)
        poisoned: list[tuple[str, str]] = []
        for rpt in reports:
            for issue in rpt.issues:
                if issue.severity == "block":
                    poisoned.append((rpt.chunk_id, issue.detail))
                else:
                    logger.warning("weak chunk %s: %s — %s", rpt.chunk_id, issue.rule, issue.detail)
        if poisoned:
            sample = "; ".join(f"{cid} ({detail})" for cid, detail in poisoned[:5])
            raise ChunkQualityError(
                f"{len(poisoned)} poisoned chunk(s) blocked indexing of doc "
                f"{chunks[0].doc_id}: {sample}. Fix the source/conversion, or set "
                "PIPELINE_CHUNK_GATE=false to override."
            )

    def index_doc(self, doc: DocumentModel, entity_terms: list[str]) -> int:
        """Enrich, chunk, embed, and index an already-parsed *doc*.

        Returns the number of chunks indexed (0 if the doc produced no content).
        In ``config.lexical_only`` mode the chunks are stored **without an embedding
        model** (sentinel vectors + ``provider="lexical"`` provenance) so search can run
        BM25-only — a fully model-free index for any language.

        Raises:
            ChunkQualityError: when ``config.chunk_gate`` is on and a chunk is
                poisoned (markup/macro residue, truncation risk, or empty).
        """
        chunks = self.enrich_and_chunk(doc, entity_terms)
        if not chunks:
            return 0
        self._enforce_chunk_gate(chunks)
        if self.config.lexical_only:
            self.store.add_chunks(chunks, _lexical_vectors(len(chunks)))
            self.store.set_provenance(_LEXICAL_PROVIDER, _LEXICAL_MODEL, dimension=_LEXICAL_DIM)
            return len(chunks)
        embeddings = self.embedder.embed_chunks(chunks)
        self.store.add_chunks(chunks, embeddings)
        if embeddings:
            provider, model = embedder_identity(self.config)
            self.store.set_provenance(provider, model, dimension=len(embeddings[0]))
        return len(chunks)

    def index_file(self, md_path: Path) -> int:
        """
        Process and index a single file.

        Returns:
            Number of chunks indexed (0 if the file produced no content).
        """
        return self.index_doc(self.parse_file(md_path), self.config.entity_terms)

    def index_directory(
        self,
        docs_dir: Path,
        glob: str = "**/*.md",
    ) -> dict[str, int]:
        """
        Process and index all markdown files matched by *glob*.

        When ``config.entity_vocab_path`` is set, a two-pass cross-corpus scan
        runs first (parse all → discover vocabulary → persist), so a term seen in
        one document is recognised in every document. Otherwise files are indexed
        independently with the static ``config.entity_terms``.

        Returns:
            Mapping ``{str(path): chunk_count}``; -1 on error.
        """
        paths = list(docs_dir.glob(glob))
        logger.info("Found %d markdown files in %s", len(paths), docs_dir)

        if self.config.entity_vocab_path:
            return self._index_with_corpus_scan(paths)

        results: dict[str, int] = {}
        for path in paths:
            try:
                results[str(path)] = self.index_file(path)
            except Exception:
                logger.exception("Failed to process %s", path)
                results[str(path)] = -1
        return results

    def scan_and_persist(
        self, paths: list[Path]
    ) -> tuple[list[str], list[tuple[Path, DocumentModel]], list[Path]]:
        """Pass 1 (model-free): parse every path, discover the cross-corpus
        vocabulary, and persist it to ``config.entity_vocab_path``.

        Seeds the scan with ``config.entity_terms`` plus the previously persisted
        vocabulary, so coverage accumulates across runs. The embedder is never
        touched, so no model is loaded.

        Returns ``(vocabulary, parsed_ok, failed_paths)``.
        """
        vocab_path = self.config.entity_vocab_path
        parsed: list[tuple[Path, DocumentModel]] = []
        failed: list[Path] = []
        for path in paths:
            try:
                parsed.append((path, self.parse_file(path)))
            except Exception:
                logger.exception("Failed to parse %s", path)
                failed.append(path)

        seed = list(self.config.entity_terms) + load_vocabulary(vocab_path)
        vocabulary = scan_corpus((doc for _, doc in parsed), seed_terms=seed)
        save_vocabulary(vocab_path, vocabulary)
        logger.info("Corpus vocabulary: %d terms → %s", len(vocabulary), vocab_path)
        return vocabulary, parsed, failed

    def _index_with_corpus_scan(self, paths: list[Path]) -> dict[str, int]:
        """Two-pass index: parse all docs, build a shared vocabulary, then index."""
        vocabulary, parsed, failed = self.scan_and_persist(paths)
        results: dict[str, int] = {str(p): -1 for p in failed}

        # Pass 2 — enrich + index every doc with the full vocabulary.
        for path, doc in parsed:
            try:
                results[str(path)] = self.index_doc(doc, vocabulary)
            except Exception:
                logger.exception("Failed to index %s", path)
                results[str(path)] = -1
        return results

    # ── Search ────────────────────────────────────────────────────────────────

    def _index_is_lexical(self) -> bool:
        """True when the index was built model-free (``provider="lexical"``).

        Read-only and tolerant: a missing/legacy/non-dict provenance returns False, so a
        normal semantic index follows the dense path unchanged.
        """
        stored = self.store.get_provenance()
        return bool(
            stored
            and isinstance(stored, dict)
            and stored.get("embedding_provider") == _LEXICAL_PROVIDER
        )

    def _verify_provenance(self) -> None:
        """
        Fail fast if the configured embedder differs from the one that built the
        index (different provider/model → different vector space).

        Degrades gracefully: legacy indexes or mocks with no provenance return
        an empty/non-dict value and are allowed through.
        """
        stored = self.store.get_provenance()
        if not stored or not isinstance(stored, dict):
            return
        provider, model = embedder_identity(self.config)
        sp, sm = stored.get("embedding_provider"), stored.get("embedding_model")
        if (sp, sm) != (provider, model):
            raise ValueError(
                "Embedding provenance mismatch: index was built with "
                f"provider={sp!r} model={sm!r}, but search is configured with "
                f"provider={provider!r} model={model!r}. Re-index or switch --provider/--model."
            )
        # The embedder matches but the embed-text layout may have moved on since the
        # index was built. That is not a hard incompatibility (same vector space), so
        # it warns rather than raises — the results are merely sub-optimal until a
        # re-index. Absent on legacy indexes (None) → skip, like the checks above.
        stored_fmt = stored.get("embed_format_version")
        if stored_fmt is not None and stored_fmt != EMBED_FORMAT_VERSION:
            logger.warning(
                "Index embed-format v%s != current v%s: stored document vectors encode an "
                "older to_embed_text layout than your queries. Re-index for best results.",
                stored_fmt,
                EMBED_FORMAT_VERSION,
            )

    def search(
        self,
        query: str,
        n_results: int = 5,
        section_type: SectionType | None = None,
        content_type: ContentType | None = None,
        space: str | None = None,
        hybrid: bool | None = None,
        genre: Genre | None = None,
    ) -> list[SearchResult]:
        """
        Return the *n_results* chunks most relevant to *query*.

        With ``hybrid`` enabled (defaults to ``config.hybrid_search``), the
        dense vector ranking is fused with a lexical BM25 ranking via Reciprocal
        Rank Fusion, so passages that literally contain the query terms are not
        out-ranked by topically-near but less specific passages.

        Optional filters narrow results by section type, content type, Confluence
        space key, or prose ``genre`` (glossary/faq/howto/policy/narrative).
        """
        # Model-free path: rank by BM25 only, never touching the embedder or its
        # provenance — so German/French/Italian (and English) search works with no model.
        # Triggered explicitly (config.lexical_only / --lexical) OR auto-detected when the
        # index itself was built lexical (provider="lexical"); the latter means a plain
        # `search` over a lexical index is steered to BM25 instead of raising a mismatch.
        if self.config.lexical_only or self._index_is_lexical():
            return self._lexical_search(
                query=query,
                n_results=n_results,
                section_type=section_type,
                content_type=content_type,
                space=space,
                genre=genre,
            )

        self._verify_provenance()
        use_hybrid = self.config.hybrid_search if hybrid is None else hybrid
        query_embedding = self.embedder.embed_query(query)

        if not use_hybrid:
            return self.store.search(
                query_embedding=query_embedding,
                n_results=n_results,
                section_type=section_type,
                content_type=content_type,
                space=space,
                genre=genre,
            )

        return self._hybrid_search(
            query=query,
            query_embedding=query_embedding,
            n_results=n_results,
            section_type=section_type,
            content_type=content_type,
            space=space,
            genre=genre,
        )

    def _hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        n_results: int,
        section_type: SectionType | None,
        content_type: ContentType | None,
        space: str | None,
        genre: Genre | None = None,
    ) -> list[SearchResult]:
        """Fuse dense and BM25 rankings with Reciprocal Rank Fusion."""
        from .retrieval import BM25Index, reciprocal_rank_fusion

        pool = self.config.hybrid_candidate_pool

        # Dense candidates (over-fetched so fusion has depth to work with).
        dense = self.store.search(
            query_embedding=query_embedding,
            n_results=pool,
            section_type=section_type,
            content_type=content_type,
            space=space,
            genre=genre,
        )

        # Lexical candidates over the same (filtered) corpus. The breadcrumb is
        # folded into the BM25 document so section titles count as keywords.
        corpus = self.store.get_corpus(
            section_type=section_type,
            content_type=content_type,
            space=space,
            genre=genre,
        )
        index = BM25Index(
            [(c.chunk_id, f"{c.metadata.get('breadcrumb', '')} {c.content}") for c in corpus],
            language=self.config.language,
            stem=self.config.lexical_stemming,
        )
        lexical_ids = index.top(query, pool)

        # Fuse, then map fused ids back to a result (dense carries distances).
        by_id = {c.chunk_id: c for c in corpus}
        by_id.update({d.chunk_id: d for d in dense})
        fused = reciprocal_rank_fusion(
            [[d.chunk_id for d in dense], lexical_ids], k=self.config.rrf_k
        )

        out: list[SearchResult] = []
        for chunk_id, fused_score in fused[:n_results]:
            base = by_id.get(chunk_id)
            if base is None:
                continue
            out.append(
                SearchResult(base.chunk_id, base.content, base.metadata, base.distance, fused_score)
            )
        return out

    def _lexical_search(
        self,
        query: str,
        n_results: int,
        section_type: SectionType | None,
        content_type: ContentType | None,
        space: str | None,
        genre: Genre | None = None,
    ) -> list[SearchResult]:
        """Rank the (filtered) corpus by BM25 alone — no embedding model is loaded.

        The model-free counterpart of :meth:`search`. Returns the top BM25 matches with the
        raw BM25 score exposed via ``SearchResult.score`` (``fused_score``). Zero-score docs
        are dropped. Returns ``[]`` when the index is empty.
        """
        from .retrieval import BM25Index

        corpus = self.store.get_corpus(
            section_type=section_type,
            content_type=content_type,
            space=space,
            genre=genre,
        )
        if not corpus:
            return []
        index = BM25Index(
            [(c.chunk_id, f"{c.metadata.get('breadcrumb', '')} {c.content}") for c in corpus],
            language=self.config.language,
            stem=self.config.lexical_stemming,
        )
        scores = index.scores(query)
        by_id = {c.chunk_id: c for c in corpus}
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

        out: list[SearchResult] = []
        for chunk_id, score in ranked:
            if score <= 0.0:
                continue
            base = by_id.get(chunk_id)
            if base is None:
                continue
            out.append(
                SearchResult(base.chunk_id, base.content, base.metadata, base.distance, score)
            )
            if len(out) >= n_results:
                break
        return out
