"""Stage C — panflute AST filter for the Confluence converter (PF-* rules).

Implements the Stage-C rules of ``docs/confluence-conversion-rules.md`` §5.
Runs in-process between ``pandoc html→json`` and ``pandoc json→gfm`` (two
subprocesses per document, mirroring the ``ast_parser.py``/``structural.py``
``pf.load`` pattern). Imported only by ``html_to_gitlab_md`` (flow B); this
module never invokes pandoc itself.

Stage A (the BeautifulSoup pre-clean) rewrites Confluence constructs into the
pandoc-friendly intermediate (PFI-HTML): plain ``div``/``span`` elements with
classes + ``data-*`` attributes. Pandoc's ``+native_divs``/``+native_spans``
turn those into AST ``Div``/``Span`` whose attributes this filter consumes.

Notes flow in via a structural protocol (no import of ``ConversionNotes`` —
avoids a circular import); counts and warnings land on the same notes object
Stage A used, so the per-file report aggregates all stages.
"""

from __future__ import annotations

import io
import re
from typing import Any, Protocol

import panflute as pf


class SupportsNotes(Protocol):
    """Structural protocol satisfied by ``html_to_gitlab_md.ConversionNotes``."""

    def warn(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...

    def bump(self, key: str, n: int = 1) -> None: ...

    def add_lang(self, lang: str) -> None: ...


# Map classes that Confluence or highlight.js may already set → pandoc lang.
# Values target ``models._EMBED_LANGS`` names so ``lang:`` embed tags stay
# trusted downstream (PF-CODELANG). Owned here; ``html_to_gitlab_md`` imports
# it back as ``_CLASS_MAP`` (single source, one-direction import).
LANG_ALIASES: dict[str, str] = {
    "sql": "sql",
    "yaml": "yaml",
    "yml": "yaml",
    "python": "python",
    "py": "python",
    "java": "java",
    "go": "go",
    "golang": "go",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "bash": "bash",
    "shell": "bash",
    "sh": "bash",
    "json": "json",
    "xml": "xml",
    "html": "html",
    "dockerfile": "dockerfile",
    "docker": "dockerfile",
    "hcl": "hcl",
    "terraform": "hcl",
    "kotlin": "kotlin",
    "scala": "scala",
    "ruby": "ruby",
    "rb": "ruby",
    "csharp": "csharp",
    "cs": "csharp",
    "cpp": "cpp",
    "c": "c",
    "markdown": "markdown",
    "md": "markdown",
    "asyncapi": "yaml",
    "openapi": "yaml",
    "github_actions": "yaml",
}

# Languages whose normalized form means "no language" (untrusted fences).
_NO_LANG = {"none", "text", "plain", ""}

# PFI layout classes flattened by PF-LAYOUT-FLATTEN (incl. any rendered-export
# layers that survived Stage A).
_LAYOUT_CLASSES = {"layout", "layout-col", "columnLayout", "cell", "innerCell"}

_ALNUM = re.compile(r"[A-Za-z0-9]")
_FOOTNOTE_MARK = re.compile(r"^[\d*†‡]$")


def pfi_attr(el: pf.Element, name: str) -> str:
    """Attribute lookup honouring the pandoc ``data-`` gotcha (§5).

    Pandoc strips the ``data-`` prefix inconsistently: ``data-macro`` becomes
    key ``macro``, but ``data-title`` stays ``data-title`` because bare
    ``title`` collides with a known HTML attribute. Check both spellings.
    """
    attrs: dict[str, str] = getattr(el, "attributes", {}) or {}
    return attrs.get(name) or attrs.get(f"data-{name}") or ""


def apply_confluence_filter(ast_json: str, notes: SupportsNotes) -> str:
    """Run the Stage-C filter over a pandoc JSON AST string; JSON in, JSON out."""
    doc = pf.load(io.StringIO(ast_json))
    run_confluence_filter(doc, notes)
    out = io.StringIO()
    pf.dump(doc, out)
    return out.getvalue()


def run_confluence_filter(doc: pf.Doc, notes: SupportsNotes) -> pf.Doc:
    """Apply all PF-* rules to *doc* in place (unit-testable without pandoc)."""

    def action(el: pf.Element, _doc: pf.Doc | None) -> Any:
        return _dispatch(el, notes)

    return pf.run_filter(action, doc=doc)


def _dispatch(el: pf.Element, notes: SupportsNotes) -> Any:
    """Route one element to its PF rule. A rule failure degrades to the hygiene
    unwrap for Div/Span (never raw-HTML leakage) and to keep-as-is otherwise."""
    try:
        if isinstance(el, pf.Div):
            classes = set(el.classes)
            if "adm" in classes:
                return _admonition(el, notes)
            if "expand" in classes:
                return _expand(el, notes)
            if classes & _LAYOUT_CLASSES:
                notes.bump("layout_flattened")
                return list(el.content)
            return list(el.content)  # PF-HYGIENE-UNWRAP
        if isinstance(el, pf.Span):
            if "lozenge" in el.classes:
                return _lozenge(el, notes)
            return list(el.content)  # PF-HYGIENE-UNWRAP
        if isinstance(el, pf.CodeBlock):
            return _codelang(el, notes)
        if isinstance(el, pf.Underline):
            return list(el.content)  # PF-INLINE-TEXT: GFM has no underline
        if isinstance(el, pf.Superscript):
            return _superscript(el, notes)
        if isinstance(el, pf.Subscript):
            return list(el.content)  # PF-INLINE-TEXT: CO2-style reads fine glued
        # pf.Strikeout: no clause — gfm renders ``~~ ~~`` natively.
        if isinstance(el, pf.Image) and el.url.startswith("data:"):
            notes.bump("data_uri_image")
            return list(el.content)  # PF-DROP: alt text is the only content
        if isinstance(el, pf.Table):
            return _table_simplify(el, notes)
        if isinstance(el, (pf.Para, pf.Plain)):
            return _junk_para(el, notes)
    except Exception as exc:  # a rule bug must never kill the file
        notes.error(f"PF filter ({type(el).__name__}): {exc}")
        if isinstance(el, (pf.Div, pf.Span)):
            return list(el.content)
    return None


# ── PF-ADMONITION ─────────────────────────────────────────────────────────────


def _admonition(el: pf.Div, notes: SupportsNotes) -> pf.BlockQuote:
    """``div.adm[data-macro][data-title]`` → blockquote with a plain bold label.

    "Warning" as a plain English word is searchable; emoji prefixes add no
    vector signal. The body blocks ride inside the same quote (same chunk).
    """
    macro = pfi_attr(el, "macro") or "info"
    title = pfi_attr(el, "title")
    label = f"{macro.capitalize()}{' — ' + title if title else ''}:"
    notes.bump("adm_rendered")
    return pf.BlockQuote(pf.Para(pf.Strong(pf.Str(label))), *list(el.content))


# ── PF-EXPAND ─────────────────────────────────────────────────────────────────


def _expand(el: pf.Div, notes: SupportsNotes) -> list[pf.Element]:
    """``div.expand[data-title]`` → bold title paragraph + body as first-class
    prose (bold, not a heading — keeps the section tree stable; no ``<details>``)."""
    title = pfi_attr(el, "title") or "Details"
    notes.bump("expand_rendered")
    return [pf.Para(pf.Strong(pf.Str(title))), *list(el.content)]


# ── PF-LOZENGE ────────────────────────────────────────────────────────────────


def _lozenge(el: pf.Span, notes: SupportsNotes) -> pf.Strong:
    """``span.lozenge`` → ``**text**`` (the status word is the signal; colour is
    styling — plain bold beats inline code, which mints fake code entities)."""
    notes.bump("status_rendered")
    return pf.Strong(pf.Str(pf.stringify(el).strip()))


# ── PF-CODELANG ───────────────────────────────────────────────────────────────


def _codelang(el: pf.CodeBlock, notes: SupportsNotes) -> None:
    """Normalize the fence language through the alias map so only trusted
    languages earn ``lang:`` embed tags downstream."""
    if not el.classes:
        return None
    first = el.classes[0].lower().removeprefix("language-").strip()
    mapped = LANG_ALIASES.get(first, first)
    if mapped in _NO_LANG:
        el.classes = []
    else:
        el.classes = [mapped]
        notes.add_lang(mapped)
    return None


# ── PF-INLINE-TEXT (superscript half) ─────────────────────────────────────────


def _superscript(el: pf.Superscript, notes: SupportsNotes) -> Any:
    """Footnote-style markers drop (welding ``word1`` mutates tokens for entity
    extraction); unit-style superscripts become ``^`` notation (``m^2`` — gluing
    to ``m2`` corrupts units)."""
    text = pf.stringify(el).strip()
    if _FOOTNOTE_MARK.fullmatch(text) and not _follows_word(el):
        notes.bump("sup_footnote_dropped")
        return []
    return [pf.Str("^"), *list(el.content)]


def _follows_word(el: pf.Element) -> bool:
    """True when the previous sibling is a Str ending in a letter/digit — the
    ``m<sup>2</sup>`` unit context, as opposed to a standalone footnote mark."""
    parent = el.parent
    if parent is None or not el.index:
        return False
    try:
        prev = parent.content[el.index - 1]
    except (IndexError, TypeError):
        return False
    return isinstance(prev, pf.Str) and bool(prev.text) and prev.text[-1].isalnum()


# ── PF-JUNK-PARA ──────────────────────────────────────────────────────────────


def _junk_para(el: pf.Element, notes: SupportsNotes) -> Any:
    """Paragraphs with no alphanumeric content die at the source (the lone
    ``\\`` from ``<p><br/></p>`` is the junk-chunk source CLAUDE.md documents).
    Image- or link-bearing paragraphs survive (alt-less images are not junk)."""
    if _ALNUM.search(pf.stringify(el)):
        return None
    if any(_contains_media(inline) for inline in el.content):
        return None
    notes.bump("junk_para_dropped")
    return []


def _contains_media(el: pf.Element) -> bool:
    if isinstance(el, (pf.Image, pf.Link)):
        return True
    content = getattr(el, "content", None)
    if content is None:
        return False
    return any(_contains_media(child) for child in content)


# ── PF-TABLE-SIMPLIFY + PF-TABLE-PIPE-IN-CODE ─────────────────────────────────


def _table_simplify(el: pf.Table, notes: SupportsNotes) -> None:
    """Unconditionally total simplification: every cell becomes ONE Plain of
    inlines (blocks joined with ``;``), spans reset, short rows padded — the gfm
    writer then always emits a pipe table. Raw-HTML table output is a conversion
    failure (lint-blocked AND silently dropped downstream), never an output mode.

    Row-header tables (``th`` in column 1, no header row) get their column-1
    cells bolded in place; ``_summarize_table_for_embed`` keys on row 1
    regardless — acceptable, flagged via the notes.
    """
    n_cols = len(el.colspec) if el.colspec else 0
    head_rows = list(el.head.content) if el.head is not None else []

    # Row-header handling: no real header row + body declares row-head columns.
    head_is_empty = not head_rows or all(not pf.stringify(row).strip() for row in head_rows)
    for body in el.content:
        if not isinstance(body, pf.TableBody):
            continue
        if head_is_empty and body.row_head_columns >= 1:
            for row in body.content:
                cells = list(row.content)
                if cells:
                    _bold_cell(cells[0])
            body.row_head_columns = 0
            notes.bump("row_header_table")
            notes.warn(
                "Row-header table: column-1 headers bolded in place; embed "
                "summaries key on row 1 regardless"
            )

    # Intermediate header rows (tiered/rowspan ``th`` rows pandoc parks in
    # ``TableBody.head``) that GFM cannot render — captured BEFORE the loop below
    # resets spans. Only >1 such row, or a spanning header cell, forces the raw
    # ``<table>`` fallback; a lone span-free header row renders fine, so leave it.
    unsafe_head_bodies = [
        body
        for body in el.content
        if isinstance(body, pf.TableBody)
        and len(body.head) > 0
        and (
            len(body.head) > 1
            or any(c.colspan > 1 or c.rowspan > 1 for r in body.head for c in r.content)
        )
    ]

    had_span = False
    for row in _iter_rows(el):
        cells = list(row.content)
        for cell in cells:
            if cell.colspan > 1 or cell.rowspan > 1:
                had_span = True
            _flatten_cell(cell, notes)
            cell.colspan = 1
            cell.rowspan = 1
        if n_cols and len(cells) < n_cols:
            for _ in range(n_cols - len(cells)):
                row.content.append(pf.TableCell(pf.Plain()))
    if had_span:
        notes.bump("merged_table_simplified")

    # GFM pipe tables have at most ONE header row and no intermediate header
    # rows. Pandoc parks tiered/rowspan ``th`` rows in ``TableBody.head`` (and,
    # for a multi-row ``thead``, in ``Table.head``); the gfm writer can represent
    # neither, so it dumps the WHOLE table as a raw ``<table>`` — lint-blocked AND
    # silently dropped downstream (§1). Fold every such row into the body as an
    # ordinary (already flattened + padded) data row: no content is lost, only the
    # header *tiering* is flattened — which is all GFM can express.
    collapsed = False
    for body in unsafe_head_bodies:
        body.content = list(body.head) + list(body.content)
        body.head = []
        collapsed = True
    if el.head is not None and len(el.head.content) > 1:
        extra = list(el.head.content[1:])
        el.head.content = el.head.content[:1]
        bodies = [b for b in el.content if isinstance(b, pf.TableBody)]
        if bodies:
            bodies[0].content = extra + list(bodies[0].content)
        else:
            el.content.append(pf.TableBody(*extra))
        collapsed = True
    if collapsed:
        notes.bump("multi_header_collapsed")
        notes.warn(
            "Table had tiered/merged header rows; extra rows folded into the body "
            "to keep a valid pipe table (header tiering is not representable in GFM)"
        )

    # Post-assertion: a still-unflattened cell means a raw-<table> risk (§1).
    for row in _iter_rows(el):
        for cell in row.content:
            blocks = list(cell.content)
            if len(blocks) > 1 or (blocks and not isinstance(blocks[0], pf.Plain)):
                notes.error("PF-TABLE-SIMPLIFY incomplete — raw <table> risk")
                return None
    return None


def _iter_rows(table: pf.Table) -> list[pf.TableRow]:
    rows: list[pf.TableRow] = []
    if table.head is not None:
        rows.extend(table.head.content)
    for body in table.content:
        if isinstance(body, pf.TableBody):
            rows.extend(body.head)  # intermediate header rows (tiered/rowspan th)
            rows.extend(body.content)
    if table.foot is not None:
        rows.extend(table.foot.content)
    return rows


def _bold_cell(cell: pf.TableCell) -> None:
    """Wrap a cell's flattened inline run in Strong (row-header rendering)."""
    _flatten_cell(cell, None)
    blocks = list(cell.content)
    if blocks and isinstance(blocks[0], pf.Plain) and list(blocks[0].content):
        cell.content = [pf.Plain(pf.Strong(*list(blocks[0].content)))]


def _flatten_cell(cell: pf.TableCell, notes: SupportsNotes | None) -> None:
    """Reduce a cell's blocks to a single Plain of inlines, joined with ``;``."""
    blocks = list(cell.content)
    if len(blocks) == 1 and isinstance(blocks[0], pf.Plain):
        _replace_linebreaks(blocks[0])
        _escape_pipes(blocks[0], notes)
        return
    runs: list[list[pf.Element]] = []
    for block in blocks:
        inlines = _block_inlines(block)
        if inlines:
            runs.append(inlines)
    joined: list[pf.Element] = []
    for i, run in enumerate(runs):
        if i:
            joined += [pf.Str(";"), pf.Space()]
        joined += run
    plain = pf.Plain(*joined)
    _replace_linebreaks(plain)
    _escape_pipes(plain, notes)
    cell.content = [plain]


def _replace_linebreaks(plain: pf.Plain) -> None:
    """A LineBreak inside a cell is unrepresentable in a pipe table — pandoc
    would fall back to a raw HTML table (conversion failure, §1). Emit the
    repo-conventional raw ``<br />`` inline instead (``quality.py`` deliberately
    excludes ``br`` from the leakage check for exactly this case)."""
    new: list[pf.Element] = []
    for inline in plain.content:
        if isinstance(inline, pf.LineBreak):
            new.append(pf.RawInline("<br />", format="html"))
        elif isinstance(inline, pf.SoftBreak):
            new.append(pf.Space())
        else:
            new.append(inline)
    plain.content = new


def _block_inlines(block: pf.Element) -> list[pf.Element]:
    """Best-effort inline run for one block inside a table cell."""
    if isinstance(block, (pf.Para, pf.Plain)):
        return list(block.content)
    if isinstance(block, pf.CodeBlock):
        return [pf.Code(block.text)]
    if isinstance(block, (pf.BulletList, pf.OrderedList)):
        runs: list[list[pf.Element]] = []
        for item in block.content:
            item_inlines: list[pf.Element] = []
            for sub in item.content:
                item_inlines += _block_inlines(sub)
            if item_inlines:
                runs.append(item_inlines)
        joined: list[pf.Element] = []
        for i, run in enumerate(runs):
            if i:
                joined += [pf.Str(";"), pf.Space()]
            joined += run
        return joined
    text = pf.stringify(block).strip()
    return [pf.Str(text)] if text else []


def _escape_pipes(plain: pf.Plain, notes: SupportsNotes | None) -> None:
    """PF-TABLE-PIPE-IN-CODE: pandoc emits ``|`` unescaped inside Code in cells
    and GitLab splits the row on it. Escape as ``\\|`` (GitLab/GitHub render it
    as a literal pipe inside code spans) — never substitute a different
    character: content must stay byte-recoverable for BM25 and entity search."""
    for inline in plain.content:
        if isinstance(inline, pf.Code) and "|" in inline.text:
            inline.text = inline.text.replace("|", "\\|")
            if notes is not None:
                notes.bump("pipe_in_code")
