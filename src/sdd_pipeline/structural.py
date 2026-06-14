"""
Stages 3 + 4: Parse a pandoc JSON AST into a typed DocumentModel.

Uses panflute to walk AST elements.  All business logic stays in this module;
nothing here calls external services or the network.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from urllib.parse import urlsplit

import panflute as pf

from .models import (
    ContentBlock,
    ContentType,
    DocumentMetadata,
    DocumentModel,
    Section,
)

logger = logging.getLogger(__name__)

# ── Internal helpers ──────────────────────────────────────────────────────────


def _short_hash(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:8]


def _meta_str(val: pf.MetaValue | None) -> str:
    """Stringify any pandoc MetaValue to plain text."""
    if val is None:
        return ""
    try:
        text: str = pf.stringify(val)
        return text.strip()
    except Exception:
        return ""


def _extract_metadata(doc: pf.Doc) -> DocumentMetadata:
    """Parse YAML frontmatter from a panflute Doc's metadata block."""
    meta = doc.metadata

    def get(key: str) -> str:
        return _meta_str(meta.get(key))

    title = get("title") or get("Title")
    space = get("space") or get("space-key") or get("spaceKey") or ""
    url = get("url") or get("source") or get("confluence-url") or ""
    author = get("author") or ""
    last_modified = get("date") or get("last-modified") or ""

    # Labels may be a comma-separated string or a MetaList
    labels: list[str] = []
    raw_labels = meta.get("labels") or meta.get("tags")
    if raw_labels is not None:
        if isinstance(raw_labels, pf.MetaList):
            labels = [_meta_str(item) for item in raw_labels.content if _meta_str(item)]
        else:
            raw_str = _meta_str(raw_labels)
            labels = [s.strip() for s in raw_str.split(",") if s.strip()]

    return DocumentMetadata(
        title=title,
        space=space,
        url=url,
        labels=labels,
        author=author,
        last_modified=last_modified,
    )


# ── Structure-preserving serializers ─────────────────────────────────────────
# Unlike pf.stringify (which flattens everything to bare text), these keep the
# semantic structure — link targets, inline code, list numbering/nesting, and
# table headers — so the text that ultimately gets embedded carries more signal.


def _link_hint(url: str) -> str:
    """Compact, embeddable hint for a link target (host for URLs, else the path)."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        host = urlsplit(url).netloc
        return host[4:] if host.startswith("www.") else host
    return url


def _serialize_inline_list(inlines) -> str:
    """Serialize a list of panflute inline elements, preserving semantic markers."""
    parts: list[str] = []
    for el in inlines:
        if isinstance(el, pf.Str):
            parts.append(el.text)
        elif isinstance(el, (pf.Space, pf.SoftBreak)):
            parts.append(" ")
        elif isinstance(el, pf.LineBreak):
            parts.append("\n")
        elif isinstance(el, pf.Code):
            # Keep backticks so identifiers stand out and survive entity regexes.
            parts.append(f"`{el.text}`")
        elif isinstance(el, pf.Link):
            inner = _serialize_inline_list(el.content)
            hint = _link_hint(el.url)
            parts.append(f"{inner} ({hint})" if hint else inner)
        elif isinstance(el, pf.Image):
            # Alt text only — the asset URL is noise for embedding.
            parts.append(_serialize_inline_list(el.content))
        elif isinstance(el, (pf.Emph, pf.Strong)):
            # Surface the text without markdown markers, so word boundaries in
            # the enrichment entity patterns are not broken.
            parts.append(_serialize_inline_list(el.content))
        elif hasattr(el, "content"):
            parts.append(_serialize_inline_list(el.content))
        else:
            parts.append(pf.stringify(el))
    return "".join(parts)


def _serialize_inlines(elem: pf.Element) -> str:
    """Serialize the inline content of a block element to structure-aware text."""
    return _serialize_inline_list(elem.content)


def _serialize_list(elem: pf.Element, indent: int = 0) -> str:
    """Serialize a bullet/ordered list, preserving numbering and nesting.

    Numbering is continuous within a single ordered list and advances only for
    items that actually render, so an empty item never opens a gap. A non-empty
    item always emits its marker — even when it leads with a nested list rather
    than text — so ordered numbers stay visible. Extra paragraphs and code in an
    item are kept as indented continuation lines under the marker, so item
    boundaries (e.g. ``- Pro arguments`` vs ``- Contra arguments``) survive.

    Note: pandoc emits *sibling* loose lists as separate AST nodes, each
    restarting its own numbering — a Markdown-source artifact this serializer
    cannot reunify into one continuous sequence.
    """
    ordered = isinstance(elem, pf.OrderedList)
    start = (getattr(elem, "start", 1) or 1) if ordered else 1
    pad = "  " * indent
    # Continuation lines align under the marker text ("N. " is 3+ cols, "- " 2).
    cont = pad + ("   " if ordered else "  ")
    lines: list[str] = []

    number = start
    for item in elem.content:
        marker = f"{number}. " if ordered else "- "
        # A ListItem's content is a list of blocks; the leading Para/Plain is the
        # item text, any nested list is recursed one level deeper.
        lead = ""
        nested: list[str] = []
        for block in item.content:
            if isinstance(block, (pf.Para, pf.Plain)):
                rendered = _serialize_inlines(block).strip()
                if not rendered:
                    continue
                if not lead:
                    lead = rendered
                else:
                    nested.append(cont + rendered)
            elif isinstance(block, (pf.BulletList, pf.OrderedList)):
                nested.append(_serialize_list(block, indent + 1))
            elif isinstance(block, pf.CodeBlock):
                # Keep the fence + language marker so enrichment's `lang:` tag
                # rule fires for code nested inside a list item.
                lang = block.classes[0] if block.classes else ""
                nested.append(cont + f"```{lang}")
                nested.extend(cont + line for line in block.text.strip().splitlines())
                nested.append(cont + "```")
        if not lead and not nested:
            continue  # genuinely empty item — skip without consuming a number
        lines.append(f"{pad}{marker}{lead}".rstrip())
        lines.extend(n for n in nested if n)
        number += 1

    return "\n".join(lines)


def _serialize_table(elem: pf.Table) -> str:
    """Render a panflute Table as a GitHub pipe table, keeping the header row."""

    def cells(row) -> list[str]:
        out: list[str] = []
        for cell in row.content:
            text_parts = [
                _serialize_inlines(b) if hasattr(b, "content") else pf.stringify(b)
                for b in cell.content
            ]
            text = " ".join(p.strip() for p in text_parts if p.strip())
            out.append(text.replace("\n", " ").replace("|", "\\|"))
        return out

    header: list[str] = []
    head_rows = list(getattr(elem.head, "content", []))
    if head_rows:
        header = cells(head_rows[0])

    body_lines: list[str] = []
    for body in elem.content:
        for row in list(getattr(body, "head", [])) + list(getattr(body, "content", [])):
            body_lines.append("| " + " | ".join(cells(row)) + " |")

    if not header and body_lines:
        # No header row — synthesize a blank one so the pipe table stays valid.
        width = body_lines[0].count("|") - 1
        header = [""] * max(width, 1)

    if not header:
        return ""

    sep = "| " + " | ".join("---" for _ in header) + " |"
    header_line = "| " + " | ".join(header) + " |"
    return "\n".join([header_line, sep, *body_lines])


def _elem_to_content_block(
    elem: pf.Block,
    doc_id: str,
    section_id: str,
    idx: int,
) -> ContentBlock | None:
    """Convert a panflute Block element to a ContentBlock, or None if ignorable."""
    block_id = _short_hash(doc_id, section_id, str(idx))

    if isinstance(elem, pf.Para):
        text = _serialize_inlines(elem).strip()
        if not text:
            return None
        return ContentBlock(
            block_id=block_id,
            content_type=ContentType.PARAGRAPH,
            text=text,
        )

    if isinstance(elem, pf.CodeBlock):
        lang: str | None = elem.classes[0] if elem.classes else None
        # Emit a fenced block so the language marker is part of the text. This
        # also activates enrichment's `lang:` tag rule (which scans for ```lang).
        text = f"```{lang or ''}\n{elem.text}\n```"
        return ContentBlock(
            block_id=block_id,
            content_type=ContentType.CODE,
            text=text,
            language=lang,
        )

    if isinstance(elem, (pf.BulletList, pf.OrderedList)):
        text = _serialize_list(elem)
        if not text:
            return None
        return ContentBlock(
            block_id=block_id,
            content_type=ContentType.LIST,
            text=text,
        )

    if isinstance(elem, pf.Table):
        text = _serialize_table(elem)
        if not text:
            return None
        return ContentBlock(
            block_id=block_id,
            content_type=ContentType.TABLE,
            text=text,
        )

    if isinstance(elem, pf.BlockQuote):
        lines: list[str] = []
        for block in elem.content:
            if isinstance(block, (pf.Para, pf.Plain)):
                rendered = _serialize_inlines(block).strip()
            elif isinstance(block, (pf.BulletList, pf.OrderedList)):
                rendered = _serialize_list(block)
            elif isinstance(block, pf.CodeBlock):
                # Keep the fence + language marker (each line is `> `-prefixed
                # below) so enrichment's `lang:` tag rule fires for quoted code.
                lang = block.classes[0] if block.classes else ""
                rendered = f"```{lang}\n{block.text.strip()}\n```"
            else:
                rendered = pf.stringify(block).strip()
            for line in rendered.splitlines():
                lines.append(f"> {line}")
        text = "\n".join(lines).strip()
        if not text:
            return None
        return ContentBlock(
            block_id=block_id,
            content_type=ContentType.BLOCKQUOTE,
            text=text,
        )

    return None


# ── Public API ────────────────────────────────────────────────────────────────


def build_structural_model(
    ast_json: dict,
    doc_id: str,
    source_path: str = "",
) -> DocumentModel:
    """
    Convert a pandoc JSON AST dict into a typed :class:`DocumentModel`.

    The heading hierarchy is reconstructed using a level-tracking stack; each
    :class:`Section` accumulates the :class:`ContentBlock` objects that appear
    between it and the next heading of equal or higher level.

    Args:
        ast_json:    Pandoc JSON AST (output of :func:`~ast_parser.generate_ast`).
        doc_id:      Stable unique identifier for the document.
        source_path: Original file path (stored as metadata, not used for I/O).

    Returns:
        A fully-populated :class:`DocumentModel`.
    """
    # panflute parses from a JSON string via a file-like object
    doc = pf.load(io.StringIO(json.dumps(ast_json)))

    metadata = _extract_metadata(doc)

    root_sections: list[Section] = []
    stack: list[Section] = []  # active ancestor path
    block_counter = 0

    # Content that appears *before* the first heading (or in a doc with no
    # headings at all) would otherwise be dropped — a real exposure, since a
    # Confluence page's title is harvested into metadata and is not guaranteed to
    # be emitted as a body H1. Buffer such blocks and, if any exist, attach them
    # to a synthesized title-derived root section so the page still produces
    # chunks instead of silently yielding none.
    preamble_id = _short_hash(doc_id, "__preamble__")
    preamble_blocks: list[ContentBlock] = []

    for elem in doc.content:
        if isinstance(elem, pf.Header):
            title = pf.stringify(elem).strip()
            section_id = elem.identifier or _short_hash(doc_id, title, str(elem.level))
            breadcrumb = [s.title for s in stack if s.level < elem.level] + [title]

            section = Section(
                level=elem.level,
                title=title,
                section_id=section_id,
                breadcrumb=breadcrumb,
            )

            # Pop the stack until we find a valid parent
            while stack and stack[-1].level >= elem.level:
                stack.pop()

            if stack:
                stack[-1].subsections.append(section)
            else:
                root_sections.append(section)

            stack.append(section)

        else:
            owner_id = stack[-1].section_id if stack else preamble_id
            cb = _elem_to_content_block(elem, doc_id, owner_id, block_counter)
            if cb is not None:
                (stack[-1].blocks if stack else preamble_blocks).append(cb)
                block_counter += 1

    if preamble_blocks:
        preamble_title = (metadata.title or "Document").strip() or "Document"
        root_sections.insert(
            0,
            Section(
                level=1,
                title=preamble_title,
                section_id=preamble_id,
                breadcrumb=[preamble_title],
                blocks=preamble_blocks,
            ),
        )
        logger.warning(
            "Synthesized a root section %r for %d block(s) before the first heading in %s",
            preamble_title,
            len(preamble_blocks),
            doc_id,
        )

    return DocumentModel(
        doc_id=doc_id,
        metadata=metadata,
        root_sections=root_sections,
        source_path=source_path,
    )
