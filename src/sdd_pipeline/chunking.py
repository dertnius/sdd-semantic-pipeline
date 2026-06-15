"""
Stage 6: Semantic chunking.

Converts an enriched DocumentModel into a flat list of SemanticChunks.
Each chunk carries its section breadcrumb, semantic type, entities, and tags
so embedding and retrieval both benefit from structural context.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import ContentType, DocumentModel, Genre, Section, SectionType, SemanticChunk

# Prose block types that can be packed together into a single section-level
# chunk. CODE and TABLE stay separate by default — they carry a language /
# structure and are distinct retrieval units. ``merge_definitions`` additionally
# folds CODE into the run so an instruction's prose and syntax share one vector.
_PROSE_TYPES = frozenset(
    {
        ContentType.PARAGRAPH,
        ContentType.LIST,
        ContentType.BLOCKQUOTE,
        ContentType.DEFINITION,
    }
)

# Conservative allowance (chars) for the per-chunk keyword list when budgeting
# the embed header — keywords are computed after the content split, so we reserve
# room rather than measure them.
_ENTITY_RESERVE = 200

# ── Text splitting helpers ────────────────────────────────────────────────────


def _split_text(
    text: str,
    max_chars: int,
    content_type: ContentType | None = None,
    language: str | None = None,
    overlap_sentences: int = 0,
) -> list[str]:
    """
    Split *text* into pieces that each render ≤ *max_chars*.

    Prose strategy (cascading):
    1. Split on blank lines (paragraphs).
    2. If a single paragraph still exceeds the limit, split on sentence-ending
       punctuation followed by whitespace.
    3. As a last resort, hard-cut at *max_chars*.

    Code blocks (``content_type == ContentType.CODE``) take a separate path
    (:func:`_split_code`) that breaks on line boundaries — never mid-token or
    mid-fence — and re-fences each piece, so a split never strands an unbalanced
    fence or severs an identifier.

    When *overlap_sentences* > 0 and a *prose* block splits into multiple pieces,
    the trailing N sentences of each piece are carried into the front of the next
    so an answer straddling a boundary survives in at least one vector. Code and
    table content never overlap.
    """
    if len(text) <= max_chars:
        return [text]

    if content_type == ContentType.CODE:
        return _split_code(text, max_chars, language)

    if content_type == ContentType.LIST:
        return _split_list(text, max_chars)

    chunks: list[str] = []
    current = ""

    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
            else:
                # Split oversized paragraph on sentence boundaries
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= max_chars:
                        current = (current + " " + sent).strip() if current else sent
                    else:
                        if current:
                            chunks.append(current)
                        # Hard-cut sentences that are still too long
                        while len(sent) > max_chars:
                            chunks.append(sent[:max_chars])
                            sent = sent[max_chars:]
                        current = sent

    if current:
        chunks.append(current)

    result = [c for c in chunks if c.strip()]
    if overlap_sentences > 0 and content_type != ContentType.TABLE and len(result) > 1:
        result = _apply_sentence_overlap(result, overlap_sentences)
    return result


def _apply_sentence_overlap(pieces: list[str], overlap_sentences: int) -> list[str]:
    """Prepend the trailing *overlap_sentences* sentences of each piece to the next."""
    out = [pieces[0]]
    for i in range(1, len(pieces)):
        prev_sentences = re.split(r"(?<=[.!?])\s+", pieces[i - 1].strip())
        tail = " ".join(s for s in prev_sentences[-overlap_sentences:] if s).strip()
        out.append(f"{tail}\n\n{pieces[i]}" if tail else pieces[i])
    return out


import re  # noqa: E402 — imported here to keep the module-level import clean

_SIGNAL_RE = re.compile(r"[A-Za-z0-9]")
# A code-fence line (3+ backticks or tildes), as emitted by
# ``structural._elem_to_content_block`` for code blocks.
_FENCE_LINE = re.compile(r"^(`{3,}|~{3,})")
# A list-item line opener ("- ", "* ", "1. "), possibly indented — as emitted by
# ``structural._serialize_list``. Used to keep splits on item boundaries.
_LIST_ITEM_LINE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")


def _has_signal(text: str) -> bool:
    """True if *text* has any alphanumeric content (drops ``\\``-only artifacts)."""
    return bool(_SIGNAL_RE.search(text.replace("`", "")))


# A short, context-free *lead-in* label: a colon-terminated cue ("Release
# checklist:") or a bare filename ("application.yaml"). Such a block carries no
# standalone meaning and is coalesced into the block that follows it.
_LEADIN_MAX_CHARS = 48
_FILENAME_RE = re.compile(r"^[\w./-]+\.[A-Za-z0-9]{1,6}$")


def _is_leadin(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > _LEADIN_MAX_CHARS or "\n" in t:
        return False
    return t.endswith(":") or bool(_FILENAME_RE.match(t))


def _split_code(text: str, max_chars: int, language: str | None) -> list[str]:
    """Split an oversized fenced code block on line boundaries, re-fencing each piece.

    Structural code blocks arrive as ``\\`\\`\\`lang\\n<code>\\n\\`\\`\\``` . We strip
    that wrapping fence, pack the inner lines into pieces that — once re-fenced —
    stay within *max_chars*, and re-wrap each piece with the same fence so the
    language marker and a balanced fence travel with every chunk. Splitting is
    line-aligned (never mid-token); only a single line longer than the budget is
    hard-cut, as a last resort. Falls back to plain line packing if no wrapping
    fence is detected.
    """
    lines = text.split("\n")
    fence_open = fence_close = ""
    inner = lines
    if len(lines) >= 2 and _FENCE_LINE.match(lines[0]) and _FENCE_LINE.match(lines[-1].strip()):
        fence_open, fence_close = lines[0], lines[-1]
        inner = lines[1:-1]
    overhead = (len(fence_open) + len(fence_close) + 2) if fence_open else 0
    budget = max(1, max_chars - overhead)

    def wrap(body: str) -> str:
        return f"{fence_open}\n{body}\n{fence_close}" if fence_open else body

    pieces: list[str] = []
    cur: list[str] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur_len
        if cur:
            pieces.append(wrap("\n".join(cur)))
            cur.clear()
            cur_len = 0

    for line in inner:
        if len(line) > budget:
            # A single line longer than the budget: flush, then hard-cut it.
            flush()
            while len(line) > budget:
                pieces.append(wrap(line[:budget]))
                line = line[budget:]
            if line:
                cur.append(line)
                cur_len = len(line)
            continue
        add = len(line) + (1 if cur else 0)  # +1 for the joining newline
        if cur and cur_len + add > budget:
            flush()
            add = len(line)
        cur.append(line)
        cur_len += add
    flush()
    return [p for p in pieces if p.strip()]


def _split_list(text: str, max_chars: int) -> list[str]:
    """Split an oversized list on *item* boundaries, never mid-item.

    A line opening a new item (``- ``/``N. ``, possibly indented) starts a new
    item; continuation/nested lines attach to the current item. Items are then
    packed into pieces ≤ *max_chars*; a single item longer than the budget stays
    whole (over budget — the gate only *warns*), because severing an item is worse
    for retrieval than a slightly long chunk.
    """
    items: list[str] = []
    cur: list[str] = []
    for line in text.split("\n"):
        if _LIST_ITEM_LINE.match(line) and cur:
            items.append("\n".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        items.append("\n".join(cur))

    pieces: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for item in items:
        add = len(item) + (1 if buf else 0)
        if buf and buf_len + add > max_chars:
            pieces.append("\n".join(buf))
            buf, buf_len, add = [], 0, len(item)
        buf.append(item)
        buf_len += add
    if buf:
        pieces.append("\n".join(buf))
    return [p for p in pieces if p.strip()]


def _header_reserve(section: Section) -> int:
    """Conservative char length of the embed header for *section*'s chunks.

    Mirrors :meth:`SemanticChunk.to_embed_text`'s header (section type +
    breadcrumb + non-echo tags) plus a fixed keyword reserve, so content can be
    split with room left for the header within the embed budget.
    """
    crumb = " > ".join(section.breadcrumb)
    prefix = (
        crumb
        if section.section_type == SectionType.CONTENT
        else f"[{section.section_type.value}] {crumb}"
    )
    tags = [t for t in section.tags if t != section.section_type.value]
    tag_len = len("tags: " + ", ".join(tags)) if tags else 0
    genre_len = len(f"genre: {section.genre.value} | ") if section.genre != Genre.GENERAL else 0
    return (
        len(prefix) + tag_len + genre_len + _ENTITY_RESERVE + 24
    )  # 24 ≈ separators + "keywords: "


# ── Main chunking logic ───────────────────────────────────────────────────────


def _section_to_chunks(
    section: Section,
    doc_id: str,
    space: str,
    labels: list[str],
    max_chunk_chars: int,
    merge_prose: bool = False,
    title: str = "",
    source_url: str = "",
    entity_fn: Callable[[str], list[str]] | None = None,
    merge_definitions: bool = False,
    embed_char_budget: int | None = None,
    keyphrase_fn: Callable[[str], list[str]] | None = None,
    overlap_sentences: int = 0,
) -> list[SemanticChunk]:
    """Recursively convert a section and all its subsections into chunks."""
    chunks: list[SemanticChunk] = []

    # Leave room for the embed header so the rendered embed_text stays within the
    # model budget (the content cap alone would let header+content overflow).
    if embed_char_budget:
        width = max(256, min(max_chunk_chars, embed_char_budget - _header_reserve(section)))
    else:
        width = max_chunk_chars

    def emit(
        text: str, content_type: ContentType, language: str | None, first_block_id: str
    ) -> None:
        for idx, sub_text in enumerate(
            _split_text(text, width, content_type, language, overlap_sentences)
        ):
            if not _has_signal(sub_text):
                continue  # drop punctuation/whitespace-only artifacts (e.g. "\\")
            # Scope entities to the chunk's own content when an extractor is
            # supplied, so a term mentioned once in a section no longer bleeds
            # onto sibling chunks that never reference it. Otherwise fall back
            # to the section-level union.
            entities = entity_fn(sub_text) if entity_fn is not None else list(section.entities)
            # Prose sections (a non-null genre) additionally get deterministic RAKE
            # keyphrases, so multi-word prose phrases reach the embed `keywords:` line
            # where the casing-based entity patterns find little. Technical/code
            # sections (genre GENERAL) are left to the precise entity extractor.
            if keyphrase_fn is not None and section.genre != Genre.GENERAL:
                seen = {e.lower() for e in entities}
                for kp in keyphrase_fn(sub_text):
                    if kp.lower() not in seen:
                        entities.append(kp)
                        seen.add(kp.lower())
            chunks.append(
                SemanticChunk(
                    chunk_id=f"{doc_id}_{section.section_id}_{first_block_id}_{idx}",
                    doc_id=doc_id,
                    breadcrumb=list(section.breadcrumb),
                    content=sub_text,
                    content_type=content_type,
                    language=language,
                    section_type=section.section_type,
                    genre=section.genre,
                    entities=entities,
                    tags=list(section.tags),
                    depends_on=list(section.depends_on),
                    exposes=list(section.exposes),
                    # Scope per-mention buckets (audit-only raw_entities and the
                    # ner:* facets) to this chunk's own text, so a section's full
                    # mention list is not smeared onto every chunk. Named inventory
                    # fields stay section-level (a table applies to the whole section).
                    metadata={
                        k: (
                            [v for v in vals if v in sub_text]
                            if k == "raw_entities" or k.startswith("ner:")
                            else list(vals)
                        )
                        for k, vals in section.metadata.items()
                    },
                    space=space,
                    labels=list(labels),
                    title=title,
                    source_url=source_url,
                )
            )

    # Which content types pack together. Definition-merge folds CODE into the
    # prose run (tables still break it); merge_prose packs prose only.
    if merge_definitions:
        packable = _PROSE_TYPES | {ContentType.CODE}
    elif merge_prose:
        packable = _PROSE_TYPES
    else:
        packable = frozenset()

    if section.genre == Genre.FAQ:
        # Pair each question paragraph with the answer block(s) that follow it, so a
        # Q&A pair co-embeds in one vector instead of fragmenting across chunks. A new
        # question starts a new unit; leading non-question content forms its own unit.
        group: list[str] = []
        group_first_id = ""

        def flush_group() -> None:
            nonlocal group_first_id
            if group:
                emit("\n\n".join(group), ContentType.PARAGRAPH, None, group_first_id)
                group.clear()
                group_first_id = ""

        for block in section.blocks:
            text = block.text.strip()
            if not text or not _has_signal(text):
                continue
            is_question = block.content_type == ContentType.PARAGRAPH and text.endswith("?")
            if is_question and group:
                flush_group()
            if not group:
                group_first_id = block.block_id
            group.append(text)
        flush_group()
    elif packable:
        buf: list[str] = []
        buf_first_id: str = ""
        buf_len = 0

        def flush() -> None:
            nonlocal buf_first_id, buf_len
            if buf:
                emit("\n\n".join(buf), ContentType.PARAGRAPH, None, buf_first_id)
                buf.clear()
                buf_first_id = ""
                buf_len = 0

        for block in section.blocks:
            text = block.text.strip()
            if not text or not _has_signal(text):
                continue
            if block.content_type in packable:
                sep = 2 if buf else 0
                if buf and buf_len + sep + len(text) > width:
                    flush()
                    sep = 0
                if not buf:
                    buf_first_id = block.block_id
                buf.append(text)
                buf_len += sep + len(text)
            else:
                flush()
                emit(text, block.content_type, block.language, block.block_id)
        flush()
    else:
        # No merge: emit one chunk per block, but coalesce a short *lead-in* label
        # (ends with ':' or a bare filename) into the block that follows it, so
        # context-free fragments like "Release checklist:" or "application.yaml"
        # don't become hollow standalone chunks.
        signal_blocks = [b for b in section.blocks if b.text.strip() and _has_signal(b.text)]
        pending: tuple[str, str] | None = None  # (lead-in text, its block_id)
        for i, block in enumerate(signal_blocks):
            text = block.text.strip()
            if pending is not None:
                emit(f"{pending[0]}\n\n{text}", block.content_type, block.language, pending[1])
                pending = None
                continue
            if _is_leadin(text) and i + 1 < len(signal_blocks):
                pending = (text, block.block_id)
                continue
            emit(text, block.content_type, block.language, block.block_id)
        if pending is not None:  # trailing lead-in with nothing to attach to
            emit(pending[0], ContentType.PARAGRAPH, None, pending[1])

    for sub in section.subsections:
        chunks.extend(
            _section_to_chunks(
                sub,
                doc_id,
                space,
                labels,
                max_chunk_chars,
                merge_prose,
                title,
                source_url,
                entity_fn,
                merge_definitions,
                embed_char_budget,
                keyphrase_fn,
                overlap_sentences,
            )
        )

    return chunks


def chunk_document(
    doc: DocumentModel,
    max_chunk_chars: int = 2000,
    merge_prose: bool = False,
    entity_fn: Callable[[str], list[str]] | None = None,
    merge_definitions: bool = False,
    embed_char_budget: int | None = None,
    keyphrase_fn: Callable[[str], list[str]] | None = None,
    overlap_sentences: int = 0,
) -> list[SemanticChunk]:
    """
    Convert an enriched :class:`DocumentModel` into a flat list of
    :class:`SemanticChunk` objects ready for embedding.

    Args:
        doc:               Enriched DocumentModel.
        max_chunk_chars:   Maximum characters per chunk (default 2 000).
        merge_prose:       When True, pack consecutive prose blocks (paragraph,
                           list, blockquote) within a section into one chunk so
                           answers are not fragmented across vectors. Code and
                           table blocks stay as their own chunks.
        entity_fn:         Optional per-chunk entity extractor. When given, each
                           chunk's ``entities`` are derived from its own content
                           (no cross-section bleed); otherwise the section-level
                           union is copied.
        merge_definitions: When True, pack prose **and** code into one section
                           chunk (tables still stay separate), co-locating an
                           instruction's explanation with its syntax. Overrides
                           ``merge_prose``.
        embed_char_budget: When set, split content so the rendered ``embed_text``
                           (header + content) stays within this many chars,
                           avoiding silent model truncation.
        keyphrase_fn:      Optional deterministic keyphrase extractor. When given,
                           its phrases are merged into each *prose-genre* chunk's
                           keywords (technical/``GENERAL`` sections are untouched),
                           enriching the vector for non-technical content.
        overlap_sentences: When > 0, a prose block that splits carries its trailing
                           N sentences into the next piece (code/tables never
                           overlap), so a boundary-straddling answer survives.

    Returns:
        Ordered list of SemanticChunks (document order preserved).
    """
    space = doc.metadata.space
    labels = doc.metadata.labels
    title = doc.metadata.title
    source_url = doc.metadata.url
    chunks: list[SemanticChunk] = []

    for section in doc.root_sections:
        chunks.extend(
            _section_to_chunks(
                section,
                doc.doc_id,
                space,
                labels,
                max_chunk_chars,
                merge_prose,
                title,
                source_url,
                entity_fn,
                merge_definitions,
                embed_char_budget,
                keyphrase_fn,
                overlap_sentences,
            )
        )

    return chunks
