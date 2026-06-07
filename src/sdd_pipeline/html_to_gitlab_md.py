#!/usr/bin/env python3
"""
html_to_gitlab_md.py
====================
Convert a Confluence (or generic) HTML document to a clean GitLab-flavoured
Markdown file using a 3-stage pipeline:

  Stage 1 — Pre-process  : BeautifulSoup strips UI chrome, normalises
                            Confluence macros, ADR cards, code blocks, etc.
  Stage 2 — Convert      : pandoc converts clean HTML → GFM markdown
  Stage 3 — Post-process : Fix fence spacing, unescape bold, inject YAML
                           front matter and [[_TOC_]]

Usage
-----
  python html_to_gitlab_md.py input.html
  python html_to_gitlab_md.py input.html -o docs/architecture.md
  python html_to_gitlab_md.py input.html --selector "article.main" --title "My Doc"
  python html_to_gitlab_md.py input.html --no-frontmatter --no-toc

Requirements
------------
  pip install beautifulsoup4 lxml
  # pandoc must be installed: https://pandoc.org/installing.html
  # Windows (Conda):  conda install -c conda-forge pandoc

Options
-------
  -o / --output         Output .md path (default: same name as input)
  --selector            CSS selector for the main content div
                        (default: auto-detect — tries Confluence Cloud + DC,
                         then <main>, then <article>, then <body>)
  --title               Override document title in YAML front matter
  --author              Author string(s) for YAML front matter
  --no-frontmatter      Skip YAML front matter block
  --no-toc              Skip [[_TOC_]] GitLab directive
  --keep-diagrams       Keep SVG diagram HTML instead of replacing with placeholder
  --confluence-version  auto (detect), cloud, or dc — flavour reported in output
                        (default: auto; handling is additive so this is a label)
  --pandoc-path         Path to pandoc binary if not on PATH
  -v / --verbose        Print each pipeline stage result

Changelog
---------
  v1.0  Confluence Cloud / generic HTML → GitLab Markdown.
  v2.0  Confluence Data Center / Server 8.5.x support: version auto-detection
        (detect_confluence_version + --confluence-version), DC info-macro
        subtypes, syntaxhighlighter code blocks (brush → language), AUI status
        lozenges, expand → <details>, DC content selectors, emoticons,
        task lists, inline-comment unwrap, and page-info/children macro removal.
  v2.1  Full conformance with docs/CONFLUENCE_FORMAT_INSTRUCTIONS.md: spec §18
        selector priority, panel title/body, anchor macros, standalone
        syntaxhighlighter pres, &nbsp; cleanup, pageSection unwrap, column-layout
        flattening, merged/nested-table warnings, ac:/ri:/at: storage handlers
        (links, images, template vars + catch-all), and a ConversionNotes
        report of warnings / macro counts / languages (spec §16).
"""

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

# ── Optional: warn if bs4 not installed ──────────────────────────────────────
try:
    from bs4 import BeautifulSoup, Comment
    from bs4.element import Tag
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed.\n  Run:  pip install beautifulsoup4 lxml")


class ConversionError(RuntimeError):
    """Raised when an HTML→Markdown conversion cannot be completed."""


@dataclass
class ConversionNotes:
    """Structured per-document conversion notes for the report (spec §16).

    Handlers append to this as they run; it is surfaced (via :meth:`to_dict`) as
    the 4th element of :func:`convert_file` and written into the JSON report.
    """

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    macro_counts: dict[str, int] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def bump(self, key: str, n: int = 1) -> None:
        self.macro_counts[key] = self.macro_counts.get(key, 0) + n

    def add_lang(self, lang: str) -> None:
        if lang and lang not in self.languages:
            self.languages.append(lang)

    def to_dict(self) -> dict[str, Any]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "macro_counts": dict(self.macro_counts),
            "languages": list(self.languages),
        }


def _select(el: Any, selector: str) -> list[Tag]:
    return cast(list[Tag], el.select(selector))


def _select_one(el: Any, selector: str) -> Tag | None:
    return cast(Tag | None, el.select_one(selector))


def _find(el: Any, name: Any = None, class_: str | None = None) -> Tag | None:
    kwargs: dict[str, Any] = {}
    if class_ is not None:
        kwargs["class_"] = class_
    return cast(Tag | None, el.find(name, **kwargs))


def _find_all(el: Any, name: Any = None, class_: str | None = None) -> list[Tag]:
    kwargs: dict[str, Any] = {}
    if class_ is not None:
        kwargs["class_"] = class_
    return cast(list[Tag], el.find_all(name, **kwargs))


def _new_tag(soup: BeautifulSoup, name: str, **kwargs: Any) -> Tag:
    return soup.new_tag(name, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFLUENCE VERSION DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


def detect_confluence_version(soup: BeautifulSoup) -> str:
    """Best-effort guess of which Confluence flavour produced this HTML export.

    Returns one of ``"dc"`` (Server / Data Center, e.g. 8.5.x), ``"cloud"``, or
    ``"unknown"``. DC is checked first because some DC exports also carry generic
    ``wiki-content`` wrappers that would otherwise look like Cloud.
    """
    # ── Data Center / Server markers ─────────────────────────────────────────
    if (
        _select_one(soup, "meta[name='ajs-version-number']") is not None
        or _select_one(soup, "[class*='syntaxhighlighter-pre']") is not None
        or _select_one(soup, ".confluenceTable") is not None
    ):
        return "dc"

    # ── Cloud markers ────────────────────────────────────────────────────────
    if (
        _select_one(soup, "meta[name='confluence-version']") is not None
        or _select_one(soup, ".content-area") is not None
        or _select_one(soup, ".wiki-content") is not None
    ):
        return "cloud"

    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 1 — HTML PRE-PROCESSOR
# ═══════════════════════════════════════════════════════════════════════════════


def preprocess(
    html: str,
    selector: str | None,
    keep_diagrams: bool,
    notes: ConversionNotes | None = None,
) -> str:
    """
    Strip UI chrome, normalise Confluence macros, and return clean HTML
    that pandoc can convert reliably.

    *notes* collects warnings / macro counts / languages for the report; a
    fresh one is created when not supplied so existing callers keep working.
    """
    notes = notes or ConversionNotes()
    soup: BeautifulSoup = BeautifulSoup(html, "lxml")

    # ── 1a. Find content root ────────────────────────────────────────────────
    content: Tag = _find_content_root(soup, selector)

    # ── 1a.2 Unwrap structural pageSection wrappers (spec §19) ───────────────
    for el in _select(content, "div.pageSection"):
        el.unwrap()

    # ── 1b. Remove UI chrome ─────────────────────────────────────────────────
    _remove_ui_chrome(content)

    # ── 1b.1 Emoticon images → unicode ───────────────────────────────────────
    _normalise_emoticons(content, notes)

    # ── 1c. Normalise Confluence macros → blockquotes ────────────────────────
    _normalise_macros(soup, content, notes)

    # ── 1c.1 Anchor macro: empty span[id] → <a id> ───────────────────────────
    _normalise_anchors(soup, content)

    # ── 1d. Flatten ADR cards ─────────────────────────────────────────────────
    _flatten_adr_cards(soup, content)

    # ── 1e. Badge spans → inline code ────────────────────────────────────────
    _normalise_badges(soup, content, notes)

    # ── 1e.1 Task lists → markdown checkboxes ────────────────────────────────
    _normalise_task_lists(soup, content, notes)

    # ── 1f. Diagrams → placeholder (or keep SVG) ─────────────────────────────
    if not keep_diagrams:
        _replace_diagrams(soup, content)

    # ── 1g. Code blocks: strip colour spans, add language class ─────────────
    _normalise_code_blocks(soup, content, notes)

    # ── 1g.1 Multi-column layouts → linear sections + <hr> ───────────────────
    _run(notes, "layouts", lambda: _normalise_layouts(soup, content, notes))

    # ── 1g.2 Flag tables GFM can't represent (merged/nested cells) ───────────
    _run(notes, "tables", lambda: _flag_tables(content, notes))

    # ── 1h. Page-props macro table ───────────────────────────────────────────
    _normalise_page_props(soup, content)

    # ── 1i. TOC macro → placeholder ──────────────────────────────────────────
    for toc in _select(content, ".toc-macro, .toc, #toc"):
        toc.decompose()

    # ── 1j. Expand/details wrappers — keep GitLab-compatible <details> ───────
    for el in _select(content, ".expand-body, .macro-expand"):
        el.unwrap()

    # ── 1k. Strip sec-num helper spans ───────────────────────────────────────
    for span in _select(content, "span.sec-num"):
        span.decompose()

    # ── 1k.1 Inline comment markers → unwrap (keep the commented-on text) ────
    for span in _select(content, "span.inline-comment-marker"):
        span.unwrap()

    # ── 1k.2–1k.5 Confluence storage-format (ac:/ri:/at:) handlers ───────────
    #     Edge cases — present only in raw/template exports. The catch-all (1k.5)
    #     MUST run last so pandoc never receives raw XML (spec §19).
    _run(notes, "ac:link", lambda: _normalise_ac_links(soup, content, notes))
    _run(notes, "ac:image", lambda: _normalise_ac_images(soup, content, notes))
    _run(notes, "template-vars", lambda: _normalise_template_vars(content))
    _run(notes, "leftover-ac", lambda: _drop_leftover_ac(content, notes))

    # ── 1k.6 Unwrap leftover non-semantic wrappers ───────────────────────────
    #        Live/rendered Confluence pages nest content in structural
    #        <div>/<span> wrappers; once their macros are normalised the bare
    #        wrappers carry no meaning and pandoc would emit them as raw HTML
    #        soup. Unwrap them (keeping children) so only real block/inline
    #        content reaches pandoc. <pre>/<table>/<details>/etc. are untouched.
    for wrapper in _find_all(content, "div") + _find_all(content, "span"):
        if wrapper.find_parent("pre") is not None:
            continue  # leave anything inside code blocks alone
        wrapper.unwrap()

    # ── 1l. Scrub attributes to a safe allow-list ────────────────────────────
    #        Keep only attrs that carry meaning downstream; preserve "language-*"
    #        classes on <code> so pandoc fences code with the right language.
    allowed_attrs = {"href", "src", "alt", "title", "id", "colspan", "rowspan"}
    for tag in _find_all(content, True):
        for attr in list(tag.attrs.keys()):
            if attr in allowed_attrs:
                continue
            # Keep language-* classes on <code> so pandoc fences them correctly
            if tag.name == "code" and attr == "class":
                lang_classes = [c for c in _as_list(tag.get("class")) if c.startswith("language-")]
                if lang_classes:
                    tag["class"] = cast(Any, lang_classes)
                    continue
            del tag[attr]

    clean_html = (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8"/></head>\n'
        f"<body>\n{content.decode_contents()}\n</body></html>"
    )
    return clean_html


def _find_content_root(soup: BeautifulSoup, selector: str | None) -> Tag:
    """Try selector → common Confluence selectors → semantic HTML → body."""
    candidates: list[str] = []
    if selector:
        candidates = [selector]

    candidates += [
        # Confluence DC 8.5.x export containers (spec §18 priority order)
        "div#content-view",
        "div.wiki-content",
        "div#main-content",
        "div#page-content",
        "div.content-body",
        # Confluence Cloud export classes
        "div.content-area",
        "div.view",
        # Generic semantic HTML
        "main",
        "article",
        "[role='main']",
        # DC §19 quirk: content sometimes wrapped in #content > #main
        "div#content div#main",
        "div#main",
    ]

    for sel in candidates:
        el = _select_one(soup, sel)
        if el:
            return el

    return cast(Tag, soup.body or soup)  # fallback: entire body


def _remove_ui_chrome(content: Tag) -> None:
    """Remove navigation, sidebar, buttons, and other non-content elements."""
    chrome_selectors = [
        # Confluence chrome
        ".code-copy",
        ".page-tabs",
        ".page-footer",
        ".page-header",
        "nav",
        ".atl-nav",
        ".sidebar",
        ".page-sidebar",
        ".sidebar-section",
        ".sidebar-item",
        # Generic UI noise
        "button",
        "[role='navigation']",
        "header",
        "footer",
        ".breadcrumb",
        ".breadcrumbs",
        # Confluence action bars
        ".page-metadata",
        ".page-controls",
        # DC 8.5.x report-style macros that carry no real content (spec §10h)
        ".pageInfoSection",
        ".recently-updated",
        ".children-macro",
        ".plugin_pagetree",
        ".childpages-macro-container",
        ".child-display",
    ]
    for sel in chrome_selectors:
        for el in _select(content, sel):
            el.decompose()


# Confluence info-macro class → (blockquote label, report count key). Subtype
# classes MUST precede the generic ``confluence-information-macro``: every DC
# info panel carries the base class too, so the generic entry would otherwise
# grab (and mislabel) warnings/tips/notes as INFO before the subtype matches.
_MACRO_LABELS = {
    "macro-info": ("ℹ️ **INFO**", "info"),
    "macro-note": ("📝 **NOTE**", "note"),
    "macro-warning": ("⚠️ **WARNING**", "warning"),
    "macro-tip": ("✅ **TIP**", "tip"),
    "confluence-information-macro-information": ("ℹ️ **INFO**", "info"),
    "confluence-information-macro-warning": ("⚠️ **WARNING**", "warning"),
    "confluence-information-macro-tip": ("✅ **TIP**", "tip"),
    "confluence-information-macro-note": ("📝 **NOTE**", "note"),
    "aui-message-info": ("ℹ️ **INFO**", "info"),
    "aui-message-warning": ("⚠️ **WARNING**", "warning"),
    "aui-message-error": ("❌ **ERROR**", "error"),
    "aui-message-success": ("✅ **TIP**", "tip"),
    "confluence-information-macro": ("ℹ️ **INFO**", "info"),  # generic — keep LAST
}


def _normalise_macros(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """Convert Confluence info/note/warning/tip/panel macros to blockquotes, and
    expand macros to ``<details>`` (spec §10a/§10b/§10c)."""
    for cls, (label, key) in _MACRO_LABELS.items():
        for el in _select(content, f".{cls}"):
            # Skip Confluence code-macro wrappers (<div class="code panel pdl">):
            # they share macro-ish classes but are code blocks, handled later by
            # _normalise_code_blocks.
            if "code" in _as_list(el.get("class")):
                continue
            # Drop the inner title/icon elements — the label already identifies it
            for t in _select(
                el,
                ".macro-title, .title, .aui-message-header, .aui-icon, "
                ".confluence-information-macro-icon",
            ):
                t.decompose()
            inner = el.get_text(separator=" ", strip=True)
            bq = _new_tag(soup, "blockquote")
            p = _new_tag(soup, "p")
            p.string = f"{label}: {inner}"
            bq.append(p)
            el.replace_with(bq)
            notes.bump(key)

    # ── Panel macro (spec §10b): title from .panelHeader, body from .panelContent
    for el in _select(content, "div.panel, div.macro-panel"):
        if "code" in _as_list(el.get("class")):
            continue  # code panels are handled by _normalise_code_blocks
        header_el = _select_one(el, ".panelHeader, .panel-heading")
        title = header_el.get_text(" ", strip=True) if header_el else ""
        if header_el:
            header_el.decompose()
        body_el = _select_one(el, ".panelContent, .panel-body")
        panel_body = (body_el or el).get_text(" ", strip=True)
        label = f"📋 **{title}**" if title else "📋 **PANEL**"
        bq = _new_tag(soup, "blockquote")
        p = _new_tag(soup, "p")
        p.string = f"{label}: {panel_body}"
        bq.append(p)
        el.replace_with(bq)
        notes.bump("panel")

    # ── DC 8.5.x expand macros → native <details>/<summary> (spec §10c) ───────
    #     div.expand-container > div.expand-control (toggle) + div.expand-content
    for exp in _select(content, ".expand-container"):
        label_el = _select_one(exp, ".expand-control-text") or _select_one(exp, ".expand-control")
        label = label_el.get_text(strip=True) if label_el else "Details"

        details = _new_tag(soup, "details")
        summary = _new_tag(soup, "summary")
        summary.string = label
        details.append(summary)

        body = _select_one(exp, ".expand-content")
        if body is not None:
            for child in list(body.contents):
                details.append(child.extract())

        exp.replace_with(details)
        notes.bump("expand")


def _flatten_adr_cards(soup: BeautifulSoup, content: Tag) -> None:
    """Flatten ADR card components into heading + paragraphs."""
    for card in _select(content, ".adr-card"):
        header = _find(card, "div", class_="adr-card-header")
        new_nodes: list[Tag] = []

        if header:
            adr_id = _text(header, ".adr-id")
            adr_title = _text(header, ".adr-title")
            badge = _text(header, ".badge")

            h4 = _new_tag(soup, "h4")
            h4.string = f"{adr_id} — {adr_title}".strip(" —")
            new_nodes.append(h4)

            if badge:
                p = _new_tag(soup, "p")
                p.string = f"**Status:** {badge}"
                new_nodes.append(p)

        body_div = _find(card, "div", class_="adr-body")
        if body_div:
            for section in _find_all(body_div, "div", class_="adr-section"):
                lbl_el = _find(section, "div", class_="adr-section-label")
                if lbl_el:
                    lbl_text = lbl_el.get_text(strip=True)
                    lbl_el.decompose()
                    for p in _find_all(section, "p"):
                        strong = _new_tag(soup, "strong")
                        strong.string = lbl_text + ": "
                        p.insert(0, strong)
                new_nodes.append(section)

        for node in new_nodes:
            card.insert_before(node)
        card.decompose()

    # Clean up any orphaned card-header divs
    for el in _select(content, ".adr-card-header"):
        el.decompose()


def _normalise_badges(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """Replace coloured badge spans / AUI status lozenges with inline code."""
    for el in _select(content, "span.badge, span[class*='badge']"):
        code = _new_tag(soup, "code")
        code.string = el.get_text(strip=True)
        el.replace_with(code)

    # ── DC 8.5.x AUI status lozenges → inline code w/ emoji prefix (spec §10g)
    #     <span class="status-macro aui-lozenge aui-lozenge-success">Approved</span>
    #     Colour subtypes are matched FIRST so a coloured status macro keeps its
    #     emoji instead of falling through to the plain (no-prefix) handler below.
    #     Per spec the emoji goes INSIDE the <code> and the text is left as-is.
    lozenge_prefixes = [
        ("span.aui-lozenge-success", "✅ "),
        ("span.aui-lozenge-error", "❌ "),
        ("span.aui-lozenge-warning", "⚠️ "),
        ("span.aui-lozenge-current", "🔵 "),
        ("span.aui-lozenge-complete", "✓ "),
    ]
    for selector, prefix in lozenge_prefixes:
        for el in _select(content, selector):
            code = _new_tag(soup, "code")
            code.string = f"{prefix}{el.get_text(strip=True)}"
            el.replace_with(code)
            notes.bump("status")

    # Remaining status macros / lozenges with no colour subtype → plain code.
    for el in _select(content, "span.status-macro, span.aui-lozenge"):
        code = _new_tag(soup, "code")
        code.string = el.get_text(strip=True)
        el.replace_with(code)
        notes.bump("status")


# Confluence emoticon NAME → unicode (spec §11). Keys are the stripped emoticon
# name (parens removed from the img alt, e.g. "(smile)" → "smile"). Newer exports
# may already set the emoji as the alt, in which case it passes through unchanged.
_EMOTICON_MAP = {
    "smile": "😊",
    "sad": "😞",
    "cheeky": "😛",
    "laugh": "😄",
    "wink": "😉",
    "thumbs-up": "👍",
    "thumbs-down": "👎",
    "information": "ℹ️",
    "tick": "✅",
    "cross": "❌",
    "warning": "⚠️",
    "star": "⭐",
    "heart": "❤️",
    "broken-heart": "💔",
    "light-on": "💡",
    "light-off": "💡",
    "yellow-star": "⭐",
    "red-star": "🌟",
    "green-star": "💚",
    "blue-star": "💙",
    # Legacy / classic alt spellings (space- and word-variants) — non-conflicting.
    "info": "ℹ️",
    "error": "❌",
    "big grin": "😀",
    "thumbs up": "👍",
    "thumbs down": "👎",
    "tongue": "😛",
    "plus": "➕",
    "minus": "➖",
    "question": "❓",
    "flag": "🚩",
}


def _emoticon_key(raw: str) -> str:
    """Normalise an emoticon alt/name to a map key: strip parens + lowercase."""
    return raw.strip().strip("()").strip().lower()


def _normalise_emoticons(content: Tag, notes: ConversionNotes) -> None:
    """Replace Confluence emoticons (img or <ac:emoticon>) with unicode (spec §11)."""
    for img in _find_all(content, "img"):
        if not any("emoticon" in c for c in _as_list(img.get("class"))):
            continue
        alt = str(img.get("alt") or "").strip()
        key = _emoticon_key(alt)
        img.replace_with(_EMOTICON_MAP.get(key, alt or key))
        notes.bump("emoticon")

    # Storage form — best effort; <ac:emoticon> only survives some HTML exports.
    for em in _find_all(content, "ac:emoticon"):
        name = str(em.get("ac:name") or em.get("name") or "")
        key = _emoticon_key(name)
        em.replace_with(_EMOTICON_MAP.get(key, f"({key})" if key else ""))
        notes.bump("emoticon")


def _normalise_task_lists(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """Convert Confluence task lists to GitLab markdown checkboxes (spec §5).

    Handles the rendered export form (``ul.inline-task-list`` whose ``li`` items
    carry a ``checked`` class) and the storage form (``<ac:task>`` with an
    ``<ac:task-status>`` of ``complete``). The ``[ ]`` / ``[x]`` markers are
    emitted as text; ``postprocess`` later unescapes pandoc's ``\\[`` to ``[``.
    """
    # Rendered export form
    for ul in _select(content, "ul.inline-task-list"):
        for li in _find_all(ul, "li"):
            mark = "[x] " if "checked" in _as_list(li.get("class")) else "[ ] "
            li.insert(0, mark)
            notes.bump("task")

    # Storage form — best effort; <ac:*> tags only survive some HTML exports.
    for task in _find_all(content, "ac:task"):
        status = _find(task, "ac:task-status")
        body = _find(task, "ac:task-body")
        done = status is not None and status.get_text(strip=True).lower() == "complete"
        text = (body or task).get_text(" ", strip=True)
        li = _new_tag(soup, "li")
        li.string = f"{'[x]' if done else '[ ]'} {text}"
        task.replace_with(li)
        notes.bump("task")
    for tl in _find_all(content, "ac:task-list"):
        tl.name = "ul"


def _normalise_anchors(soup: BeautifulSoup, content: Tag) -> None:
    """Anchor macro (spec §10i): empty ``<span id="...">`` → ``<a id="...">``.

    GitLab Markdown supports inline HTML anchors, so this preserves in-page
    link targets that pandoc would otherwise drop with the stripped span.
    """
    for span in _find_all(content, "span"):
        anchor_id = span.get("id")
        if anchor_id and not span.get_text(strip=True) and not _find_all(span, True):
            span.replace_with(_new_tag(soup, "a", id=str(anchor_id)))


def _normalise_layouts(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """Flatten Confluence multi-column layouts (spec §12).

    GFM has no columns, so each cell's content is emitted linearly with an
    ``<hr>`` between cells, and a warning is recorded for manual review.
    """
    for layout in _select(content, "div.columnLayout"):
        cells = _select(layout, "div.cell") or _select(layout, "div.innerCell")
        if not cells:
            continue
        new_nodes: list[Any] = []
        for i, cell in enumerate(cells):
            if i:
                new_nodes.append(_new_tag(soup, "hr"))
            new_nodes.extend(child.extract() for child in list(cell.contents))
        layout.replace_with(*new_nodes)
        notes.warn("Layout columns flattened — review manually")
        notes.bump("layout")


def _flag_tables(content: Tag, notes: ConversionNotes) -> None:
    """Flag table features GFM pipe tables cannot represent (spec §9).

    Merged cells (colspan/rowspan) keep their content but lose the merge; nested
    tables are flattened one level. Both record a warning for manual review.
    """
    # Nested tables → flatten one level (rare; GFM has no nested tables).
    for table in _find_all(content, "table"):
        if table.find_parent("table") is not None:
            notes.warn("Nested table flattened one level — review manually")
            notes.bump("nested_table")
            table.unwrap()
    # Merged cells → warn (content survives; pandoc ignores the span attrs).
    for table in _find_all(content, "table"):
        cells = _find_all(table, "td") + _find_all(table, "th")
        if any(c.get("colspan") or c.get("rowspan") for c in cells):
            notes.warn("Table has merged cells (colspan/rowspan) — review manually")
            notes.bump("merged_table")


def _run(notes: ConversionNotes, label: str, fn: Callable[[], None]) -> None:
    """Run a per-element handler, recording (not raising) failures (spec §16)."""
    try:
        fn()
    except Exception as exc:
        notes.error(f"{label}: {exc}")


# ── Confluence storage-format (ac:/ri:/at:) handlers ─────────────────────────
# These tags only survive in raw / template exports, not normal rendered HTML.
# NOTE: the lxml HTML parser DROPS CDATA, so <ac:plain-text-link-body> text is
# unavailable — link text falls back to the page title / anchor name.


def _normalise_ac_links(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """Confluence <ac:link> → standard anchors (spec §6b–6e/§14)."""
    for link in _find_all(content, "ac:link"):
        body_el = _find(link, "ac:link-body") or _find(link, "ac:plain-text-link-body")
        text = body_el.get_text(" ", strip=True) if body_el else ""
        page = _find(link, "ri:page")
        attach = _find(link, "ri:attachment")
        anchor = link.get("ac:anchor")

        if page is not None:
            title = str(page.get("ri:content-title") or "")
            space = str(page.get("ri:space-key") or "")
            a = _new_tag(soup, "a", href="#")
            a.string = text or title or "link"
            marker = f" confluence-page: {title}{f' ({space})' if space else ''} "
            link.replace_with(a, Comment(marker))
            notes.warn(f"Unresolved Confluence page link: {title or '(unknown)'}")
        elif attach is not None:
            fname = str(attach.get("ri:filename") or "")
            a = _new_tag(soup, "a", href=f"./attachments/{fname}")
            a.string = text or fname or "attachment"
            link.replace_with(a)
            notes.warn(f"Attachment link — co-locate file: ./attachments/{fname}")
        elif anchor:
            a = _new_tag(soup, "a", href=f"#{anchor}")
            a.string = text or str(anchor)
            link.replace_with(a)
        else:
            link.unwrap()


def _normalise_ac_images(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """Confluence <ac:image> → standard <img> (spec §7)."""
    for img_el in _find_all(content, "ac:image"):
        attach = _find(img_el, "ri:attachment")
        url = _find(img_el, "ri:url")
        if attach is not None:
            fname = str(attach.get("ri:filename") or "")
            src = f"./attachments/{fname}"
            alt = str(img_el.get("ac:alt") or fname)
            notes.warn(f"Image references attachment — co-locate file: {src}")
        elif url is not None:
            src = str(url.get("ri:value") or "")
            alt = str(img_el.get("ac:alt") or "")
        else:
            img_el.decompose()
            continue
        attrs: dict[str, str] = {"src": src, "alt": alt}
        if img_el.get("ac:title"):
            attrs["title"] = str(img_el.get("ac:title"))
        for dim in ("width", "height"):
            if img_el.get(f"ac:{dim}"):
                attrs[dim] = str(img_el.get(f"ac:{dim}"))
        img_el.replace_with(_new_tag(soup, "img", **attrs))


def _normalise_template_vars(content: Tag) -> None:
    """Template vars / placeholders (spec §13): <at:var> → {name}, placeholder → *[text]*."""
    for var in _find_all(content, "at:var"):
        var.replace_with(f"{{{var.get('at:name') or ''!s}}}")
    for ph in _find_all(content, "ac:placeholder"):
        ph.replace_with(f"*[{ph.get_text(' ', strip=True)}]*")


def _drop_leftover_ac(content: Tag, notes: ConversionNotes) -> None:
    """Decompose/unwrap any surviving ac:/ri:/at: tags so pandoc never sees raw
    XML noise (spec §19). Runs LAST, after the specific ac: handlers."""
    seen: set[str] = set()
    for tag in _find_all(content, True):
        name = tag.name or ""
        if not name.startswith(("ac:", "ri:", "at:")):
            continue
        if tag.parent is None:
            continue  # already removed via an ancestor
        if name not in seen:
            notes.warn(f"Dropped leftover Confluence storage tag <{name}>")
            seen.add(name)
        notes.bump("dropped_tag")
        if name in ("ac:structured-macro", "ac:rich-text-body"):
            tag.unwrap()  # keep inner content
        else:
            tag.decompose()


def _replace_diagrams(soup: BeautifulSoup, content: Tag) -> None:
    """Replace SVG diagram wrappers with descriptive figure placeholders."""
    for wrap in _select(content, ".diagram-wrap, .drawio-diagram, figure"):
        cap_el = _find(wrap, "figcaption")
        caption = cap_el.get_text(strip=True) if cap_el else "Architecture Diagram"

        hr1 = _new_tag(soup, "hr")
        p_cap = _new_tag(soup, "p")
        p_cap.string = f"📊 *{caption}*"
        bq = _new_tag(soup, "blockquote")
        bq_p = _new_tag(soup, "p")
        bq_p.string = (
            "⚙️ Diagram: SVG rendered in source document. "
            "Attach an exported image or replace with a Mermaid diagram block."
        )
        hr2 = _new_tag(soup, "hr")
        bq.append(bq_p)

        for node in [hr1, p_cap, bq, hr2]:
            wrap.insert_before(node)
        wrap.decompose()


# Language detection heuristics for code blocks that carry no lang class
def _as_list(value: Any) -> list[str]:
    """Normalise a BS4 class value (may be str, list, or None) to a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        seq = cast(list[Any] | tuple[Any, ...] | set[Any], value)
        return [str(v) for v in seq]
    return [str(value)]


_LANG_PATTERNS = [
    (r"\bCREATE\s+TABLE\b|\bSELECT\b.+\bFROM\b|\bINSERT\s+INTO\b", "sql"),
    (r"^(FROM|RUN|CMD|COPY|ENV|EXPOSE|WORKDIR)\s", "dockerfile"),
    (r"^\s*(def |class |import |from \w+ import)", "python"),
    (r"^\s*(public|private|protected|class |interface |import )", "java"),
    (r"^\s*(func |package |import \()", "go"),
    (r"(^|\n)\s*[a-zA-Z_]+:\s*\n\s+\w", "yaml"),
    (r'^\s*\{[\s\S]*"[\w]+"\s*:', "json"),
    (r"#!(\/usr\/bin\/env\s+)?bash|#!/bin/sh", "bash"),
    (r"<\?xml|<[A-Z][a-zA-Z]+\s+xmlns", "xml"),
]

# Map classes that Confluence or highlight.js may already set → pandoc lang
_CLASS_MAP = {
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


def _detect_language(code_text: str, existing_classes: list[str]) -> str:
    """Return a pandoc-compatible language identifier string."""
    # 1. Try existing class attributes first
    for cls in existing_classes:
        cls = cls.lower().replace("language-", "").replace("sourceCode", "").strip()
        if cls in _CLASS_MAP:
            return _CLASS_MAP[cls]

    # 2. Heuristic scan of first 300 chars
    sample = code_text.strip()[:300]
    for pattern, lang in _LANG_PATTERNS:
        if re.search(pattern, sample, re.MULTILINE | re.IGNORECASE):
            return lang

    return ""


# Confluence syntaxhighlighter brush → pandoc language identifier (spec §8).
_BRUSH_MAP = {
    "java": "java",
    "sql": "sql",
    "python": "python",
    "py": "python",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "bash": "bash",
    "shell": "bash",
    "sh": "bash",
    "xml": "xml",
    "html": "html",
    "css": "css",
    "yaml": "yaml",
    "yml": "yaml",
    "json": "json",
    "groovy": "groovy",
    "scala": "scala",
    "kotlin": "kotlin",
    "ruby": "ruby",
    "rb": "ruby",
    "cpp": "cpp",
    "c": "c",
    "csharp": "csharp",
    "cs": "csharp",
    "go": "go",
    "golang": "go",
    "hcl": "hcl",
    "terraform": "hcl",
    "dockerfile": "dockerfile",
    "docker": "dockerfile",
    "powershell": "powershell",
    "ps1": "powershell",
    "none": "",
    "text": "",
    "plain": "",
}


def _lang_from_syntaxhighlighter(pre: Tag) -> str:
    """Language for a syntaxhighlighter <pre> from its ``brush:`` param (spec §8)."""
    params = str(pre.get("data-syntaxhighlighter-params") or "")
    m = re.search(r"brush:\s*([^;]+)", params)
    brush = m.group(1).strip().lower() if m else ""
    if not brush:
        return _detect_language(pre.get_text(), [])
    if brush in ("none", "text", "plain"):
        return ""
    return _BRUSH_MAP.get(brush, brush)


def _rebuild_pre(soup: BeautifulSoup, raw_code: str, lang: str) -> Tag:
    """Build a clean ``<pre><code class="language-X">`` block (class as a LIST)."""
    new_pre = _new_tag(soup, "pre")
    kw: dict[str, Any] = {"attrs": {"class": [f"language-{lang}"]}} if lang else {}
    new_code = _new_tag(soup, "code", **kw)
    new_code.string = raw_code
    new_pre.append(new_code)
    return new_pre


def _normalise_code_blocks(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """
    Normalise code blocks in spec §17 priority order:
      1. div.code.panel (DC 8.5.x code-macro wrapper)
      2. div.code-block (Cloud-style wrapper)
      3. pre.syntaxhighlighter-pre (standalone DC rendered pre)
      4. pre > code (any remaining bare code blocks)
    Each is rebuilt as <pre><code class="language-X"> with colour spans stripped.
    """
    # ── (§17 #1) DC 8.5.x syntaxhighlighter wrappers ─────────────────────────
    for wrapper in _select(content, "div.code.panel"):
        pre = _select_one(wrapper, "pre.syntaxhighlighter-pre") or _find(wrapper, "pre")
        if pre is None:
            continue
        lang = _lang_from_syntaxhighlighter(pre)
        wrapper.replace_with(_rebuild_pre(soup, pre.get_text(), lang))
        notes.add_lang(lang)
        notes.bump("code_block")

    # ── (§17 #2) Confluence .code-block macro wrappers ───────────────────────
    for block in _select(content, ".code-block"):
        label_el = _find(block, class_="code-lang")
        label = ""
        if label_el:
            raw = label_el.get_text(strip=True).lower()
            # Take up to first 3 words, join with _, strip punctuation
            words = re.sub(r"[^a-z0-9 ]", " ", raw).split()[:3]
            # Try progressively shorter tokens: "github_actions_service" → "github_actions" → "github"
            for length in range(len(words), 0, -1):
                candidate = "_".join(words[:length])
                if candidate in _CLASS_MAP:
                    label = _CLASS_MAP[candidate]
                    break
            else:
                label = _CLASS_MAP.get(words[0], words[0]) if words else ""
            label_el.decompose()

        pre = _find(block, "pre")
        if pre:
            raw_code = pre.get_text()
            if not label:
                existing = _as_list(pre.get("class"))
                inner_code = _find(pre, "code")
                if inner_code:
                    existing += _as_list(inner_code.get("class"))
                label = _detect_language(raw_code, existing)
            block.replace_with(_rebuild_pre(soup, raw_code, label))
            notes.add_lang(label)
            notes.bump("code_block")

    # ── (§17 #3) Standalone pre.syntaxhighlighter-pre (not in a div.code.panel)
    for pre in _select(content, "pre.syntaxhighlighter-pre"):
        lang = _lang_from_syntaxhighlighter(pre)
        pre.replace_with(_rebuild_pre(soup, pre.get_text(), lang))
        notes.add_lang(lang)
        notes.bump("code_block")

    # ── (§17 #4) Bare <pre> blocks (anything not already normalised) ──────────
    for pre in _find_all(content, "pre"):
        code = _find(pre, "code")
        # Skip blocks already normalised above (their <code> carries language-*).
        if code is not None and any("language-" in c for c in _as_list(code.get("class"))):
            continue
        if code:
            raw_code = code.get_text()
            existing = _as_list(code.get("class"))
            label = _detect_language(raw_code, existing)
            code.string = raw_code  # strip colour spans
            if label and not any("language-" in c for c in existing):
                code["class"] = cast(Any, [f"language-{label}"])
        else:
            # Bare <pre> with no <code> — wrap it
            raw_code = pre.get_text()
            label = _detect_language(raw_code, [])
            kw: dict[str, Any] = {"attrs": {"class": [f"language-{label}"]}} if label else {}
            new_code = _new_tag(soup, "code", **kw)
            new_code.string = raw_code
            pre.clear()
            pre.append(new_code)
        notes.add_lang(label)
        notes.bump("code_block")


def _normalise_page_props(soup: BeautifulSoup, content: Tag) -> None:
    """Convert .page-props macro to a plain heading + table."""
    for pp in _select(content, ".page-props"):
        title_el = _find(pp, class_="page-props-title")
        if title_el:
            h3 = _new_tag(soup, "h3")
            h3.string = title_el.get_text(strip=True)
            pp.insert_before(h3)
            title_el.decompose()
        pp.unwrap()


def _text(el: Tag, selector: str) -> str:
    found = _select_one(el, selector)
    return found.get_text(strip=True) if found else ""


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 2 — PANDOC CONVERSION
# ═══════════════════════════════════════════════════════════════════════════════


def convert(clean_html: str, pandoc_path: str) -> str:
    """Run pandoc on clean HTML and return GFM markdown string.

    Raises:
        ConversionError: if pandoc exits non-zero.
    """
    cmd = [
        pandoc_path,
        "--from",
        "html",
        "--to",
        "gfm+pipe_tables",
        "--wrap=none",
        "--strip-comments",
        "--no-highlight",
    ]

    result = subprocess.run(
        cmd,
        input=clean_html.encode("utf-8"),
        capture_output=True,
    )

    if result.returncode != 0:
        raise ConversionError(f"pandoc error:\n{result.stderr.decode()}")

    return result.stdout.decode("utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 3 — POST-PROCESSOR
# ═══════════════════════════════════════════════════════════════════════════════


def postprocess(
    md: str,
    title: str,
    author: str,
    source_path: Path,
    add_frontmatter: bool,
    add_toc: bool,
    space: str = "",
    source_url: str = "",
    labels: list[str] | None = None,
) -> str:
    """Clean up pandoc's GFM output for GitLab compatibility."""

    # ── Fix: &nbsp; (decoded to U+00A0) → regular space (spec §4) ────────────
    md = md.replace(" ", " ")

    # ── Fix: pandoc outputs "``` yaml" — GitLab needs "```yaml" ────────────
    md = re.sub(r"^``` (\w)", r"```\1", md, flags=re.M)

    # ── Fix: over-escaped bold/italic inside blockquotes ────────────────────
    md = re.sub(r"\\(\*\*)", r"\1", md)
    md = re.sub(r"\\(\*)", r"\1", md)

    # ── Fix: over-escaped angle brackets ────────────────────────────────────
    md = re.sub(r"\\<", "<", md)
    md = re.sub(r"\\>", ">", md)

    # ── Fix: task-list checkboxes — pandoc escapes "- [ ]" → "- \[ \]" ───────
    md = re.sub(r"(^\s*[-*+] )\\\[( |x)\\\]", r"\1[\2]", md, flags=re.M)

    # ── Fix: over-escaped underscores in [[_TOC_]] ──────────────────────────
    md = re.sub(
        r"\\_Table of contents[^\n]+\\\[\\\[\\?_TOC_\\\]\\\]\\_",
        "",
        md,
    )

    # ── Collapse 3+ blank lines to exactly 2 ────────────────────────────────
    md = re.sub(r"\n{3,}", "\n\n", md)

    # ── Trim trailing whitespace from every line ─────────────────────────────
    md = "\n".join(line.rstrip() for line in md.splitlines())

    # ── Ensure single trailing newline ──────────────────────────────────────
    md = md.rstrip("\n") + "\n"

    # ── Build YAML front matter ──────────────────────────────────────────────
    header_parts: list[str] = []

    if add_frontmatter:
        doc_title = title or _infer_title(md, source_path)
        doc_author = author or ""

        fm_lines = [
            "---",
            f'title: "{doc_title}"',
        ]
        if doc_author:
            fm_lines += [
                "authors:",
                f'  - "{doc_author}"',
            ]
        # Provenance keys, emitted with the exact names the pipeline's
        # structural._extract_metadata reads back (space / url / labels), so a
        # later `export` carries them onto every chunk.
        if space:
            fm_lines.append(f'space: "{space}"')
        if source_url:
            fm_lines.append(f'url: "{source_url}"')
        if labels:
            fm_lines.append("labels:")
            fm_lines += [f'  - "{lbl}"' for lbl in labels]
        fm_lines += [
            f'source_file: "{source_path.name}"',
            "---",
            "",
        ]
        header_parts.append("\n".join(fm_lines))

    if add_toc:
        header_parts.append("[[_TOC_]]\n")

    if header_parts:
        md = "\n".join(header_parts) + "\n" + md.lstrip()

    return md


def _infer_title(md: str, path: Path) -> str:
    """Derive a title from the first H1 in the markdown, or the filename."""
    m = re.search(r"^# (.+)", md, re.M)
    if m:
        return m.group(1).strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


# ═══════════════════════════════════════════════════════════════════════════════
#  VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


def validate(md: str, verbose: bool) -> bool:
    """Run a set of sanity checks and print results. Returns True if all pass."""
    checks = {
        "No raw <div class= attrs": "<div class=" not in md,
        "No base64 data URIs": "data:image/svg+xml;base64" not in md,
        "No Confluence CSS class refs": 'class="atl-' not in md,
        "Pipe tables present": "|---" in md or "| ---" in md,
        "Headings present": bool(re.search(r"^#{1,4} ", md, re.M)),
        "No 3+ consecutive blank lines": not re.search(r"\n{4,}", md),
    }

    all_pass = all(checks.values())
    if verbose or not all_pass:
        for desc, ok in checks.items():
            print(f"  {'✅' if ok else '❌'} {desc}")

    return all_pass


# ═══════════════════════════════════════════════════════════════════════════════
#  STATS
# ═══════════════════════════════════════════════════════════════════════════════


def _count_tables(md: str) -> int:
    """Count GitLab pipe tables by their delimiter rows (one per table).

    A delimiter row is a line made up only of ``| - : space`` characters that
    contains at least one pipe and at least one dash, e.g. ``| --- | :--: |``.
    """
    count = 0
    for line in md.splitlines():
        s = line.strip()
        if "|" in s and "-" in s and set(s) <= set("|-: "):
            count += 1
    return count


def _count_urls(md: str) -> int:
    """Count markdown links plus raw/auto http(s) URLs.

    Includes ``[text](target)`` links (excluding ``![alt](src)`` images),
    ``<https://…>`` autolinks, and bare ``https://…`` occurrences that are not
    already part of a markdown link or autolink.
    """
    md_links = re.findall(r"(?<!!)\[[^\]]*\]\([^)\s]+", md)
    autolinks = re.findall(r"<https?://[^>\s]+>", md)
    bare = re.findall(r"(?<![(<\w])https?://[^\s)>\]]+", md)
    return len(md_links) + len(autolinks) + len(bare)


def stats(md: str) -> dict[str, int]:
    """Per-file conversion metrics.

    ``sections``/``headings`` and ``code_snippets``/``code_blocks`` are
    synonyms kept for both the report schema and back-compatibility.
    """
    headings = len(re.findall(r"^#{1,6}[ \t]", md, re.M))
    pictures = len(re.findall(r"!\[[^\]]*\]\([^)]*\)", md))
    code_blocks = md.count("```") // 2
    lists = len(re.findall(r"^[ \t]*(?:[-*+]|\d+\.)[ \t]+\S", md, re.M))
    tables = _count_tables(md)
    urls = _count_urls(md)

    return {
        "lines": md.count("\n"),
        "words": len(md.split()),
        "chars": len(md),
        "sections": headings,
        "headings": headings,  # alias (back-compat)
        "pictures": pictures,
        "code_snippets": code_blocks,
        "code_blocks": code_blocks,  # alias (back-compat)
        "lists": lists,
        "tables": tables,
        "urls": urls,
        "blockquotes": len(re.findall(r"^> ", md, re.M)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API — programmatic single-file conversion
# ═══════════════════════════════════════════════════════════════════════════════


def resolve_pandoc(pandoc_path: str | None = None) -> str:
    """Return a usable pandoc executable path or raise ConversionError."""
    pandoc = pandoc_path or shutil.which("pandoc")
    if not pandoc:
        raise ConversionError(
            "pandoc not found on PATH.\n"
            "  Install: https://pandoc.org/installing.html\n"
            "  Conda:   conda install -c conda-forge pandoc\n"
            "  Or pass an explicit pandoc path."
        )
    return pandoc


def convert_file(
    src: Path,
    output: Path | None = None,
    *,
    selector: str | None = None,
    title: str = "",
    author: str = "",
    add_frontmatter: bool = True,
    add_toc: bool = True,
    keep_diagrams: bool = False,
    pandoc_path: str | None = None,
    space: str = "",
    source_url: str = "",
    labels: list[str] | None = None,
    write: bool = True,
) -> tuple[Path, str, dict[str, int], dict[str, Any]]:
    """Convert a single HTML file to GitLab-flavoured Markdown.

    Runs the full 3-stage pipeline (pre-process → pandoc → post-process) and,
    when *write* is true, writes the result to *output* (default: ``<src>.md``).

    Returns:
        ``(output_path, markdown, metrics, notes)`` where ``metrics`` is
        :func:`stats` and ``notes`` is :meth:`ConversionNotes.to_dict`
        (``warnings`` / ``errors`` / ``macro_counts`` / ``languages``).

    Raises:
        ConversionError: if the source is missing or pandoc fails.
    """
    src = Path(src)
    if not src.exists():
        raise ConversionError(f"input file not found: {src}")

    out_path = Path(output) if output is not None else src.with_suffix(".md")
    pandoc = resolve_pandoc(pandoc_path)

    notes = ConversionNotes()
    html = src.read_text(encoding="utf-8")
    clean_html = preprocess(html, selector, keep_diagrams, notes)
    raw_md = convert(clean_html, pandoc)
    final_md = postprocess(
        md=raw_md,
        title=title,
        author=author,
        source_path=src,
        add_frontmatter=add_frontmatter,
        add_toc=add_toc,
        space=space,
        source_url=source_url,
        labels=labels,
    )

    if write:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final_md, encoding="utf-8")

    return out_path, final_md, stats(final_md), notes.to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="html_to_gitlab_md",
        description="Convert Confluence / generic HTML to GitLab-flavoured Markdown.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("input", type=Path, help="Input HTML file")
    p.add_argument("-o", "--output", type=Path, help="Output .md file (default: <input>.md)")
    p.add_argument("--selector", default=None, help="CSS selector for main content div")
    p.add_argument("--title", default="", help="Document title for YAML front matter")
    p.add_argument("--author", default="", help="Author(s) for YAML front matter")
    p.add_argument("--no-frontmatter", action="store_true", help="Skip YAML front matter")
    p.add_argument("--no-toc", action="store_true", help="Skip [[_TOC_]] directive")
    p.add_argument("--keep-diagrams", action="store_true", help="Keep SVG diagram HTML as-is")
    p.add_argument(
        "--confluence-version",
        choices=["auto", "cloud", "dc"],
        default="auto",
        help="Confluence flavour: 'auto' detects it (default), 'cloud'/'dc' force it",
    )
    p.add_argument("--pandoc-path", default="", help="Path to pandoc binary")
    p.add_argument("-v", "--verbose", action="store_true", help="Print stage details")
    return p


def main() -> None:
    args = build_parser().parse_args()
    src = args.input.resolve()
    output = args.output or src.with_suffix(".md")

    # ── Validate dependencies ────────────────────────────────────────────────
    try:
        pandoc = resolve_pandoc(args.pandoc_path)
    except ConversionError as exc:
        sys.exit(f"ERROR: {exc}")

    if not src.exists():
        sys.exit(f"ERROR: Input file not found: {src}")

    # ── Resolve Confluence flavour: auto-detect, or honour the forced choice ──
    version_labels = {"dc": "DC / Server", "cloud": "Cloud", "unknown": "unknown"}
    if args.confluence_version == "auto":
        version = detect_confluence_version(BeautifulSoup(src.read_text(encoding="utf-8"), "lxml"))
        version_mode = f"{version_labels.get(version, version)} (auto-detected)"
    else:
        version = args.confluence_version
        version_mode = f"{version_labels.get(version, version)} (forced)"

    print(f"📄  Input   : {src}")
    print(f"📝  Output  : {output}")
    print(f"🔧  Pandoc  : {pandoc}")
    print(f"🔎  Version : {version_mode}")
    print()

    print("Converting (pre-process → pandoc → post-process)...")
    try:
        output, final_md, s, conv_notes = convert_file(
            src,
            output,
            selector=args.selector,
            title=args.title,
            author=args.author,
            add_frontmatter=not args.no_frontmatter,
            add_toc=not args.no_toc,
            keep_diagrams=args.keep_diagrams,
            pandoc_path=pandoc,
        )
    except ConversionError as exc:
        sys.exit(f"ERROR: {exc}")

    # ── Validate + Stats ────────────────────────────────────────────────────
    print()
    all_ok = validate(final_md, args.verbose)
    print()
    print(f"{'✅ Done' if all_ok else '⚠️  Done (with warnings)'}")
    print(
        f"   {s['lines']} lines · {s['words']} words · {s['chars']:,} chars · "
        f"{s['headings']} headings · {s['tables']} tables · "
        f"{s['code_blocks']} code blocks · {s['blockquotes']} blockquotes"
    )
    # ASCII-safe notes summary (cp1252 consoles choke on emoji when redirected).
    if conv_notes["warnings"] or conv_notes["errors"]:
        print(
            f"   notes: {len(conv_notes['warnings'])} warning(s), "
            f"{len(conv_notes['errors'])} error(s)"
        )
        if args.verbose:
            for w in conv_notes["warnings"]:
                print(f"     - warning: {w}")
            for e in conv_notes["errors"]:
                print(f"     - error:   {e}")
    print(f"   -> {output}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
