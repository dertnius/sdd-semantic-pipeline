#!/usr/bin/env python3
"""
html_to_gitlab_md.py
====================
Convert a Confluence (or generic) HTML document to a clean GitLab-flavoured
Markdown file using a 4-stage pipeline (docs/confluence-conversion-rules.md):

  Stage A — Pre-process  : BeautifulSoup strips UI chrome and rewrites
                            Confluence constructs into the pandoc-friendly
                            intermediate (PFI-HTML: div/span + data-* attrs)
  Stage B — Read         : pandoc converts clean HTML → JSON AST
  Stage C — Filter       : in-process panflute filter (confluence_pf_filter)
                            renders admonitions/expands/lozenges/layouts and
                            simplifies tables on the AST
  Stage B' — Write       : pandoc converts JSON AST → GFM markdown
  Stage D — Post-process : fence-aware regex fixes + YAML-safe front matter

Usage
-----
  python html_to_gitlab_md.py input.html
  python html_to_gitlab_md.py input.html -o docs/architecture.md
  python html_to_gitlab_md.py input.html --selector "article.main" --title "My Doc"
  python html_to_gitlab_md.py input.html --no-frontmatter --toc

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
  v2.1  Full conformance with docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md:
        spec §18 selector priority, panel title/body, anchor macros, standalone
        syntaxhighlighter pres, &nbsp; cleanup, pageSection unwrap, column-layout
        flattening, merged/nested-table warnings, ac:/ri:/at: storage handlers
        (links, images, template vars + catch-all), and a ConversionNotes
        report of warnings / macro counts / languages (spec §16).
  v3.0  Rendered-HTML scope of docs/confluence-conversion-rules.md: 4-stage
        pipeline with an in-process panflute Stage C (PFI contract — the
        unwrap/scrub is PFI-aware); admonitions/panels → plain blockquote
        labels (no emoji); expand → bold paragraph (no <details>); lozenges →
        bold text; layouts flattened with NO <hr>; anchor policy (targets
        dropped, same-page links → plain text, ids scrubbed); emoticons →
        plain words; HX-MENTION/-JIRA/-PROFILE/-GALLERY/-VIEWFILE handlers;
        data-URI images → alt text; attachments/comments pageSections dropped
        before unwrap; pre-root chrome harvest → notes.metadata feeds
        YAML-safe frontmatter (author: singular, date:, page_id:); Stage-D
        regexes fence-aware (angle-bracket unescape DELETED); checkbox-input
        task lists; bare-pre language detection removed (HX-PRE).
        BREAKING: --no-toc replaced by opt-in --toc (default OFF);
        convert_file(add_toc=) default flipped to False; notes dict gains
        "metadata"; the id attribute no longer survives the scrub.
"""

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

# ── Optional: warn if bs4 not installed ──────────────────────────────────────
try:
    from bs4 import BeautifulSoup, Comment
    from bs4.element import Tag
except ImportError:
    sys.exit("ERROR: beautifulsoup4 not installed.\n  Run:  pip install beautifulsoup4 lxml")

# Shared engine-agnostic layer + Stage-C panflute filter (flow-B helpers; the
# filter never invokes pandoc). The fallback branch supports script mode
# (`python src/sdd_pipeline/convert/html_to_gitlab_md.py`) under an editable install.
try:
    from .base import (
        ConversionError,
        ConversionNotes,
        _run_pandoc,
        postprocess,
        resolve_pandoc,
        stats,
    )
    from .confluence_pf_filter import LANG_ALIASES, apply_confluence_filter
except ImportError:  # script mode: python …/convert/html_to_gitlab_md.py
    from sdd_pipeline.convert.base import (
        ConversionError,
        ConversionNotes,
        _run_pandoc,
        postprocess,
        resolve_pandoc,
        stats,
    )
    from sdd_pipeline.convert.confluence_pf_filter import LANG_ALIASES, apply_confluence_filter


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

    # Record the detected Confluence flavour — a confidence signal for the gate
    # ("unknown" alone is only informational; combined with other signals it is
    # part of a quarantine verdict).
    notes.metadata.setdefault("confluence_version", detect_confluence_version(soup))

    # ── 0. Harvest page chrome on the FULL soup (HX-CHROME-TITLE/-METADATA) ──
    #      The harvest sources (#main-header, page-metadata) live OUTSIDE the
    #      typical content root — read them BEFORE root selection discards them.
    _harvest_page_chrome(soup, notes)

    # ── 1a. Find content root ────────────────────────────────────────────────
    content: Tag = _find_content_root(soup, selector, notes)

    # ── 1a.1 Drop attachments/comments pageSections (HX-CHROME-ATTACH/-COMMENTS)
    #        BEFORE the generic unwrap below would leak their link dumps.
    _drop_attachment_comment_sections(content, notes)

    # ── 1a.2 Unwrap structural pageSection wrappers (spec §19) ───────────────
    for el in _select(content, "div.pageSection"):
        el.unwrap()

    # ── 1b. Remove UI chrome ─────────────────────────────────────────────────
    _remove_ui_chrome(content)

    # ── 1b.05 Early inline-text rules (HX-TEXT-STRIKE / SMALLBIG / TIME) ─────
    #        MUST run before any unwrap/scrub: the scrub strips style attrs and
    #        pandoc drops self-closing <time> at read.
    _normalise_inline_text(content)

    # ── 1b.1 Emoticon images → plain words (HX-EMOTICON) ─────────────────────
    _normalise_emoticons(content, notes)

    # ── 1b.2 User mentions → plain names (HX-MENTION) ────────────────────────
    _run(notes, "mentions", lambda: _normalise_mentions(content, notes))

    # ── 1b.3 Jira issue spans (HX-JIRA) — before lozenges (consumes its own) ──
    _run(notes, "jira", lambda: _normalise_jira(soup, content, notes))

    # ── 1b.4 Profile macros → display names (HX-PROFILE) ─────────────────────
    _run(notes, "profiles", lambda: _normalise_profiles(content, notes))

    # ── 1c. Admonitions / panels → PFI div.adm (HX-ADMONITION / HX-PANEL) ────
    _normalise_admonitions(soup, content, notes)

    # ── 1c.0 Expand macros → PFI div.expand (HX-EXPAND — no <details>) ───────
    _normalise_expands(soup, content, notes)

    # ── 1c.1 Anchor policy: same-page links → text; empty targets dropped ────
    _flatten_samepage_links(content, notes)

    # ── 1d. Flatten ADR cards ─────────────────────────────────────────────────
    _flatten_adr_cards(soup, content)

    # ── 1e. Badge spans → inline code; status lozenges → PFI span.lozenge ────
    _normalise_badges(soup, content, notes)

    # ── 1e.1 Task lists → real checkbox inputs (pandoc emits ``- [x]``) ──────
    _normalise_task_lists(soup, content, notes)

    # ── 1f.0 Galleries / view-files / embedded-image alt copy (HX-IMG family) ─
    #        Order is load-bearing: the gallery consumes embedded-image cells.
    _run(notes, "gallery", lambda: _normalise_gallery(soup, content, notes))
    _run(notes, "viewfile", lambda: _normalise_viewfiles(soup, content, notes))
    _run(notes, "embedded-img", lambda: _normalise_embedded_images(content))

    # ── 1f. Diagrams: data-URI → alt text; SVG figures → caption (HX-IMG-DATA)
    if not keep_diagrams:
        _normalise_diagrams(soup, content, notes)

    # ── 1g. Code blocks: strip colour spans, add language class ─────────────
    _normalise_code_blocks(soup, content, notes)

    # ── 1g.1 Multi-column layouts → PFI layout divs (HX-LAYOUT, no <hr>) ─────
    _run(notes, "layouts", lambda: _normalise_layouts(soup, content, notes))

    # ── 1g.2 Flag tables GFM can't represent (merged/nested cells) ───────────
    _run(notes, "tables", lambda: _flag_tables(content, notes))

    # ── 1h. Page-props macro table ───────────────────────────────────────────
    _normalise_page_props(soup, content)

    # ── 1i. TOC macro → delete (incl. Cloud client-side variant) ─────────────
    for toc in _select(content, ".toc-macro, .toc, #toc, .client-side-toc-macro"):
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
        if _PFI_CLASSES & set(_as_list(wrapper.get("class"))):
            continue  # PFI carriers must reach the Stage-C filter intact (§1)
        wrapper.unwrap()

    # ── 1l. Scrub attributes to a safe allow-list (PFI-aware) ────────────────
    #        Keep only attrs that carry meaning downstream. PFI elements keep
    #        class + data-macro/data-title/data-colour (the Stage-C contract);
    #        checkbox inputs keep type/checked (task lists); "language-*"
    #        classes stay on <code> so pandoc fences code with the right
    #        language. ``id`` is NOT kept — anchor policy: targets are dropped
    #        and same-page links are plain text, so ids are zero-content HTML.
    allowed_attrs = {"href", "src", "alt", "title", "colspan", "rowspan"}
    pfi_attrs = {"class", "data-macro", "data-title", "data-colour"}
    for tag in _find_all(content, True):
        is_pfi = bool(_PFI_CLASSES & set(_as_list(tag.get("class"))))
        for attr in list(tag.attrs.keys()):
            if attr in allowed_attrs:
                continue
            if is_pfi and attr in pfi_attrs:
                continue
            if tag.name == "input" and attr in ("type", "checked"):
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


# PFI-HTML classes (the Stage A ↔ Stage C contract, conversion-rules §1): the
# blanket unwrap and the attribute scrub must let these carriers through, or
# the entire Stage-C filter is dead code.
_PFI_CLASSES = {"adm", "expand", "lozenge", "layout", "layout-col"}


def _harvest_page_chrome(soup: BeautifulSoup, notes: ConversionNotes) -> None:
    """Harvest title/space/author/date/page_id into ``notes.metadata``
    (HX-CHROME-TITLE / HX-CHROME-METADATA / FM-TITLE / FM-PAGEID).

    Runs on the FULL soup before ``_find_content_root`` — the sources live
    outside the content root. Harvest only; deletion stays with the chrome
    selectors after root selection.
    """
    meta = notes.metadata

    title_el = _select_one(soup, "span#title-text") or _select_one(soup, "head > title")
    if title_el is not None:
        raw = title_el.get_text(" ", strip=True)
        if " : " in raw:
            space, _, title = raw.partition(" : ")
            if space.strip():
                meta.setdefault("space", space.strip())
            if title.strip():
                meta.setdefault("title", title.strip())
        elif raw:
            meta.setdefault("title", raw)

    pm = _select_one(soup, "div.page-metadata")
    if pm is not None:
        author_el = _select_one(pm, "span.author") or _select_one(pm, "a.url.fn")
        if author_el is not None:
            author = author_el.get_text(" ", strip=True)
            if author:
                meta.setdefault("author", author)
        m = re.search(r"\bon (.+?)\s*$", pm.get_text(" ", strip=True))
        if m:
            meta.setdefault("date", m.group(1).strip())

    for el in _find_all(soup, ["img", "a"]):
        ref = str(el.get("src") or el.get("href") or "")
        m = re.search(r"attachments/(\d+)/", ref)
        if m:
            meta.setdefault("page_id", m.group(1))
            break


def _drop_attachment_comment_sections(content: Tag, notes: ConversionNotes) -> None:
    """Drop the export-footer "Attachments"/"Comments" pageSections wholesale
    (HX-CHROME-ATTACH-SECTION / HX-CHROME-COMMENTS).

    When the content root is ``#content`` these sections sit INSIDE it, and the
    generic pageSection unwrap would leak their raw link dumps into the corpus
    — the canonical ``link_density`` failure.
    """
    for el in _select(content, "div.pageSection"):
        if _select_one(el, "h2#attachments") is not None:
            el.decompose()
            notes.bump("attachments_section")
        elif _select_one(el, "h2#comments") is not None:
            el.decompose()
            notes.bump("comments_section")


def _normalise_inline_text(content: Tag) -> None:
    """Early inline-text rules, BEFORE any unwrap/scrub (conversion-rules §2.1/§3):

    - ``span[style*=line-through]`` → ``<del>`` (HX-TEXT-STRIKE — the scrub
      strips the style attr and the unwrap deletes the span, erasing the
      rejected-decision signal);
    - ``small``/``big`` → unwrap (deprecated presentation tags);
    - ``<time datetime>`` → ISO date text (pandoc drops self-closing ``time``
      at read, so a Stage-C rule is physically unreachable).
    """
    for span in _find_all(content, "span"):
        style = str(span.get("style") or "")
        if "line-through" in style:
            span.name = "del"
            del span["style"]
    for el in _find_all(content, ["small", "big"]):
        el.unwrap()
    for t in _find_all(content, "time"):
        iso = str(t.get("datetime") or "").strip()
        t.replace_with(iso or t.get_text(" ", strip=True))


def _find_content_root(
    soup: BeautifulSoup, selector: str | None, notes: ConversionNotes | None = None
) -> Tag:
    """Try selector → common Confluence selectors → semantic HTML → body.

    When none of the recognised content containers match and the whole ``<body>``
    is used as the root, record a low-confidence signal (``root_fallback``) and a
    warning: the export does not match a supported shape, so page chrome may leak
    into the corpus. The converter's confidence gate reads this signal.
    """
    candidates: list[str] = []
    if selector:
        candidates = [selector]

    candidates += [
        # Confluence DC 8.5.x export containers (spec §18 priority order;
        # #content-view is legacy code-derived — the research catalog documents
        # div#content.view, added below per HX-ROOT)
        "div#content-view",
        "div.wiki-content",
        "div#main-content",
        # Catalog-backed content wrapper; space index.html pages root at
        # #content (its attachments/comments pageSections are dropped first).
        "div#content.view",
        "div#content",
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

    if notes is not None:
        notes.metadata["root_fallback"] = "true"
        notes.warn(
            "No recognised content container found — using the whole <body> as the "
            "content root; page chrome may leak (export does not match a supported shape)."
        )
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


# Confluence info-macro class → (PFI ``data-macro`` value, report count key).
# Subtype classes MUST precede the generic ``confluence-information-macro``:
# every DC info panel carries the base class too, so the generic entry would
# otherwise grab (and mislabel) warnings/tips/notes as info before the subtype
# matches. No emoji anywhere — PF-ADMONITION renders a plain searchable word.
_ADMONITION_TYPES = {
    "macro-info": ("info", "info"),
    "macro-note": ("note", "note"),
    "macro-warning": ("warning", "warning"),
    "macro-tip": ("tip", "tip"),
    "confluence-information-macro-information": ("info", "info"),
    "confluence-information-macro-warning": ("warning", "warning"),
    "confluence-information-macro-tip": ("tip", "tip"),
    "confluence-information-macro-note": ("note", "note"),
    "aui-message-info": ("info", "info"),
    "aui-message-warning": ("warning", "warning"),
    "aui-message-error": ("warning", "error"),
    "aui-message-success": ("tip", "tip"),
    "confluence-information-macro": ("info", "info"),  # generic — keep LAST
}


def _replace_with_adm(soup: BeautifulSoup, el: Tag, macro: str, title: str, body: Tag) -> None:
    """Replace *el* with a PFI ``div.adm[data-macro][data-title]`` whose body
    children are moved as real blocks (no ``get_text`` flattening — lists and
    code inside the body survive; PF-ADMONITION renders the blockquote)."""
    div = _new_tag(soup, "div")
    div["class"] = cast(Any, ["adm"])
    div["data-macro"] = macro
    if title:
        div["data-title"] = title
    for child in list(body.contents):
        div.append(child.extract())
    el.replace_with(div)


def _normalise_admonitions(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """HX-ADMONITION / HX-PANEL → PFI ``div.adm`` (all generations).

    Covers modern ``confluence-information-macro`` divs, AUI messages, generic
    panels, and legacy pre-5.x ``div.panelMacro > table.{x}Macro``.
    """
    for cls, (macro, key) in _ADMONITION_TYPES.items():
        for el in _select(content, f".{cls}"):
            # Skip Confluence code-macro wrappers (<div class="code panel pdl">):
            # they share macro-ish classes but are code blocks, handled later by
            # _normalise_code_blocks.
            if "code" in _as_list(el.get("class")):
                continue
            title = ""
            title_el = _select_one(el, "p.title, .macro-title, .aui-message-header")
            if title_el is not None:
                title = title_el.get_text(" ", strip=True)
                title_el.decompose()
            for icon in _select(el, ".aui-icon, .confluence-information-macro-icon"):
                icon.decompose()
            body = _select_one(el, ".confluence-information-macro-body, .aui-message-content")
            _replace_with_adm(soup, el, macro, title, body or el)
            notes.bump(key)

    # ── Panel macro: title from .panelHeader, body from .panelContent ────────
    for el in _select(content, "div.panel, div.macro-panel"):
        classes = _as_list(el.get("class"))
        if "code" in classes or "preformatted" in classes:
            continue  # code/noformat panels are handled by _normalise_code_blocks
        header_el = _select_one(el, ".panelHeader, .panel-heading")
        title = header_el.get_text(" ", strip=True) if header_el else ""
        if header_el:
            header_el.decompose()
        body_el = _select_one(el, ".panelContent, .panel-body")
        _replace_with_adm(soup, el, "panel", title, body_el or el)
        notes.bump("panel")

    # ── Legacy pre-5.x admonitions (VER-LEGACY-ADMONITION) ───────────────────
    legacy = {
        "infoMacro": "info",
        "noteMacro": "note",
        "warningMacro": "warning",
        "tipMacro": "tip",
    }
    for el in _select(content, "div.panelMacro"):
        table = _find(el, "table")
        macro = "info"
        if table is not None:
            for c in _as_list(table.get("class")):
                if c in legacy:
                    macro = legacy[c]
                    break
        cells = _find_all(el, "td")
        body_cell = cells[-1] if cells else el  # icon img sits in the first td
        _replace_with_adm(soup, el, macro, "", body_cell)
        notes.bump(macro)


def _normalise_expands(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """HX-EXPAND → PFI ``div.expand[data-title]`` (no ``<details>`` — raw HTML
    in the corpus hides content from naive renderers; PF-EXPAND renders a bold
    title paragraph + the body as first-class prose)."""
    for exp in _select(content, ".expand-container"):
        label_el = _select_one(exp, ".expand-control-text") or _select_one(exp, ".expand-control")
        label = label_el.get_text(strip=True) if label_el else ""

        div = _new_tag(soup, "div")
        div["class"] = cast(Any, ["expand"])
        if label:
            div["data-title"] = label
        body = _select_one(exp, ".expand-content")
        for child in list((body or exp).contents):
            div.append(child.extract())
        for ctl in _select(div, ".expand-control"):
            ctl.decompose()  # control row, when the body was the container itself
        exp.replace_with(div)
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


# AUI lozenge colour subtypes recognised for the PFI data-colour attribute.
_LOZENGE_COLOURS = ("success", "error", "current", "complete", "moved", "warning")


def _normalise_badges(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """Badge spans (ADR cards) → inline code; AUI status lozenges → PFI
    ``span.lozenge[data-colour]`` (HX-STATUS).

    PF-LOZENGE renders ``**text**`` — the status word is the signal; colour is
    styling. Plain bold beats inline-code-with-emoji: backticked status text
    gets mistaken for code entities, and emoji add no vector signal.
    """
    for el in _select(content, "span.badge, span[class*='badge']"):
        if "lozenge" in " ".join(_as_list(el.get("class"))):
            continue  # lozenges are handled below
        code = _new_tag(soup, "code")
        code.string = el.get_text(strip=True)
        el.replace_with(code)

    for el in _select(content, "span.status-macro, span.aui-lozenge"):
        colour = ""
        for c in _as_list(el.get("class")):
            m = re.match(r"aui-lozenge-(\w+)", c)
            if m and m.group(1) in _LOZENGE_COLOURS:
                colour = m.group(1)
                break
        span = _new_tag(soup, "span")
        span["class"] = cast(Any, ["lozenge"])
        if colour:
            span["data-colour"] = colour
        span.string = el.get_text(strip=True)
        el.replace_with(span)
        notes.bump("status")


def _normalise_mentions(content: Tag, notes: ConversionNotes) -> None:
    """HX-MENTION: user-profile links → the display name as plain text.

    Profile hrefs are dead outside Confluence and inflate ``link_density``;
    the name is the entity.
    """
    for a in _select(content, "a.confluence-userlink"):
        a.replace_with(a.get_text(" ", strip=True))
        notes.bump("mention")


def _normalise_jira(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """HX-JIRA: jira-issue spans → ``[KEY](clean-url) summary (status)``.

    Key + summary + status is dense, query-matching text; widget chrome is not.
    Runs BEFORE the lozenge handler — it consumes the status lozenge inside.
    """
    for span in _select(content, "span.jira-issue, span.confluence-jim-macro"):
        if span.find_parent(class_="jira-issue") is not None:
            continue  # nested decoration — handled with its root
        key_a = _select_one(span, "a.jira-issue-key") or _select_one(span, "a[href*='/browse/']")
        if key_a is None:
            inner_table = _find(span, "table")
            if inner_table is not None:
                span.replace_with(inner_table.extract())  # table mode: keep the table
            else:
                span.decompose()  # degraded error paragraph / empty widget
            notes.bump("jira")
            continue
        href = re.sub(r"[?&]src=confmacro\b", "", str(key_a.get("href") or ""))
        key_text = key_a.get_text(strip=True)
        summary_el = _select_one(span, "span.summary")
        summary = summary_el.get_text(" ", strip=True) if summary_el else ""
        status_el = _select_one(span, "span.aui-lozenge")
        status = status_el.get_text(strip=True) if status_el else ""
        resolved = "resolved" in _as_list(span.get("class"))

        a = _new_tag(soup, "a", href=href)
        a.string = key_text or href
        bits = [b for b in (summary, f"({status})" if status else "") if b]
        if resolved:
            bits.append("(resolved)")
        parts: list[Any] = [a]
        if bits:
            parts.append(" " + " ".join(bits))
        span.replace_with(*parts)
        notes.bump("jira")

    for el in _select(content, ".refresh-module, .jira-error"):
        el.decompose()  # refresh-widget wrappers / error paragraphs


def _normalise_profiles(content: Tag, notes: ConversionNotes) -> None:
    """HX-PROFILE: profile-macro vcards → the display name as plain text."""
    for el in _select(content, "div.profile-macro"):
        img = _select_one(el, "img.userLogo")
        name = ""
        if img is not None:
            name = re.sub(r"^User icon:\s*", "", str(img.get("alt") or "")).strip()
        if not name:
            link = _select_one(el, "a")
            name = link.get_text(" ", strip=True) if link else el.get_text(" ", strip=True)
        el.replace_with(name)
        notes.bump("profile")


# Confluence emoticon NAME → plain searchable WORD (HX-EMOTICON — never emoji:
# a word is an ASCII token the embedder and BM25 can match; literal emoji add
# no vector signal and trip the documented cp1252 console pitfalls). Keys are
# the stripped emoticon name (parens removed, e.g. "(smile)" → "smile").
_EMOTICON_WORDS = {
    "smile": "smile",
    "sad": "sad",
    "cheeky": "cheeky",
    "laugh": "laugh",
    "wink": "wink",
    "thumbs-up": "thumbs-up",
    "thumbs-down": "thumbs-down",
    "information": "info",
    "tick": "yes",
    "cross": "no",
    "warning": "warning",
    "star": "star",
    "heart": "heart",
    "broken-heart": "broken-heart",
    "light-on": "idea",
    "light-off": "idea",
    "yellow-star": "star",
    "red-star": "star",
    "green-star": "star",
    "blue-star": "star",
    # Legacy / classic alt spellings (space- and word-variants) — non-conflicting.
    "info": "info",
    "error": "error",
    "big grin": "grin",
    "thumbs up": "thumbs-up",
    "thumbs down": "thumbs-down",
    "tongue": "cheeky",
    "plus": "plus",
    "minus": "minus",
    "question": "question",
    "flag": "flag",
}


def _emoticon_key(raw: str) -> str:
    """Normalise an emoticon alt/name to a map key: strip parens + lowercase."""
    return raw.strip().strip("()").strip().lower()


def _normalise_emoticons(content: Tag, notes: ConversionNotes) -> None:
    """Replace Confluence emoticons with plain words (HX-EMOTICON).

    Key preference: ``data-emoticon-name`` → stripped ``alt`` — A1/A2 symmetry
    with the storage path's shortname→word chain; never emit emoji.
    """
    for img in _find_all(content, "img"):
        if not any("emoticon" in c for c in _as_list(img.get("class"))):
            continue
        raw = str(img.get("data-emoticon-name") or img.get("alt") or "").strip()
        key = _emoticon_key(raw)
        img.replace_with(_EMOTICON_WORDS.get(key, key))
        notes.bump("emoticon")

    # Storage form — best effort; <ac:emoticon> only survives some HTML exports.
    for em in _find_all(content, "ac:emoticon"):
        name = str(em.get("ac:name") or em.get("name") or "")
        key = _emoticon_key(name)
        em.replace_with(_EMOTICON_WORDS.get(key, key))
        notes.bump("emoticon")


def _normalise_task_lists(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """Convert Confluence task lists to GitLab markdown checkboxes (spec §5).

    Handles the rendered export form (``ul.inline-task-list`` whose ``li`` items
    carry a ``checked`` class — synthesized as real ``<input type="checkbox">``
    elements, which pandoc converts natively to ``- [x]`` / ``- [ ]``) and the
    storage form (``<ac:task>`` with an ``<ac:task-status>`` of ``complete``,
    still text markers; MD-TASKBOX in Stage D remains as its backstop).
    """
    # Rendered export form → real checkbox inputs (HX-TASKLIST)
    for ul in _select(content, "ul.inline-task-list"):
        for li in _find_all(ul, "li"):
            attrs: dict[str, Any] = {"type": "checkbox"}
            if "checked" in _as_list(li.get("class")):
                attrs["checked"] = ""
            li.insert(0, _new_tag(soup, "input", **attrs))
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


def _flatten_samepage_links(content: Tag, notes: ConversionNotes) -> None:
    """Anchor policy (HX-ANCHOR + SF-LINK-EXT carve-out, conversion-rules §3):
    same-page links degrade to plain text and empty anchor targets are deleted.

    The rendered-export anchor-id scheme (``#PageTitle-Heading``) never matches
    GitLab's heading slugs, and the targets are dropped anyway — a kept
    ``[text](#anchor)`` would be a guaranteed-dead link inflating
    ``link_density``. Heading ids fall out via the attribute scrub.
    """
    for a in _find_all(content, "a"):
        href = str(a.get("href") or "")
        if not href.startswith("#"):
            continue
        if a.get_text(strip=True) or _find_all(a, True):
            a.unwrap()
        else:
            a.decompose()
        notes.bump("anchor_link_flattened")
    for el in _find_all(content, ["a", "span"]):
        if el.get("id") and not el.get_text(strip=True) and not _find_all(el, True):
            el.decompose()
            notes.bump("anchor_dropped")


def _normalise_layouts(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """HX-LAYOUT → PFI ``div.layout`` / ``div.layout-col``.

    PF-LAYOUT-FLATTEN linearizes the cells in document order — plain
    concatenation, NO ``<hr>`` separators (resolved decision, conversion-rules
    §10: columns are visual; reading order is what chunkers need).
    """
    for inner in _select(content, "div.columnLayout div.innerCell"):
        inner.unwrap()
    for cell in _select(content, "div.columnLayout div.cell"):
        cell.attrs = {}
        cell["class"] = cast(Any, ["layout-col"])
        notes.bump("layout")
    for layout in _select(content, "div.columnLayout"):
        layout.attrs = {}
        layout["class"] = cast(Any, ["layout"])
    for outer in _select(content, "div.contentLayout2"):
        outer.unwrap()


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


def _caption_para(soup: BeautifulSoup, caption: str) -> Tag:
    """Build the ``<p><em>{caption}</em></p>`` italic caption paragraph."""
    p = _new_tag(soup, "p")
    em = _new_tag(soup, "em")
    em.string = caption
    p.append(em)
    return p


def _normalise_diagrams(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """HX-IMG-DATA: data-URI images → alt text only; inline SVG / diagram
    wrappers → an italic caption paragraph.

    A base64 blob is pure entropy in the corpus (pandoc would emit a multi-KB
    ``![alt](data:image/png;base64,…)`` token blob — ``src`` passes the scrub
    allowlist); the alt/figcaption is the only retrievable content. Stage B
    must never receive an inline SVG tree (its text children leak as garbled
    prose). Plain figures with raster images keep their image; only the
    caption is normalised.
    """
    for img in _find_all(content, "img"):
        if str(img.get("src") or "").startswith("data:"):
            alt = str(img.get("alt") or "").strip()
            if alt:
                img.replace_with(alt)
            else:
                img.decompose()
            notes.bump("data_uri_image")

    for wrap in _select(content, ".diagram-wrap, .drawio-diagram, figure"):
        if wrap.parent is None:
            continue  # already removed via an ancestor
        cap_el = _find(wrap, "figcaption")
        caption = cap_el.get_text(strip=True) if cap_el else ""
        is_vector = _find(wrap, "svg") is not None or wrap.name != "figure"
        if is_vector:
            if not caption:
                inner_img = _find(wrap, "img")
                caption = str((inner_img.get("alt") if inner_img else "") or "").strip()
            if caption:
                wrap.replace_with(_caption_para(soup, caption))
            else:
                wrap.decompose()
            notes.bump("diagram")
        else:
            # Plain figure with a raster image: keep the image, caption → italic.
            if cap_el is not None:
                cap_el.replace_with(_caption_para(soup, caption))
            wrap.unwrap()

    for svg in _find_all(content, "svg"):
        svg.decompose()  # any bare inline SVG outside a recognised wrapper
        notes.bump("diagram")


def _normalise_gallery(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """HX-GALLERY: thumbnail tables → one italic filenames line.

    A grid of thumbnail img tags embeds as nothing; the filenames are the
    searchable content.
    """
    for table in _select(content, "table.gallery"):
        names: list[str] = []
        for img in _select(table, "img.confluence-embedded-image"):
            name = str(
                img.get("data-linked-resource-default-alias") or img.get("alt") or ""
            ).strip()
            if not name:
                name = Path(str(img.get("src") or "")).name
            if name:
                names.append(name)
        text = (
            f"Image gallery ({len(names)} images): {', '.join(names)}"
            if names
            else "Image gallery."
        )
        table.replace_with(_caption_para(soup, text))
        notes.bump("gallery")


def _normalise_viewfiles(soup: BeautifulSoup, content: Tag, notes: ConversionNotes) -> None:
    """HX-VIEWFILE: embedded-file links → ``[alias](href) (nice-type)`` —
    filename + type are the artifact's identity."""
    for a in _select(content, "a.confluence-embedded-file"):
        alias = (
            str(a.get("data-linked-resource-default-alias") or "").strip()
            or a.get_text(" ", strip=True)
            or "attachment"
        )
        nice = str(a.get("data-nice-type") or "").strip()
        new_a = _new_tag(soup, "a", href=str(a.get("href") or ""))
        new_a.string = alias
        parts: list[Any] = [new_a]
        if nice:
            parts.append(f" ({nice})")
        a.replace_with(*parts)
        notes.bump("viewfile")


def _normalise_embedded_images(content: Tag) -> None:
    """HX-IMG: copy the original filename (``data-linked-resource-default-alias``)
    into an empty ``alt`` — the numeric-id src is opaque; the filename is the
    only searchable token. Unwrap wrapper spans and attachment thumbnail links.
    """
    for img in _select(content, "img.confluence-embedded-image"):
        alias = str(img.get("data-linked-resource-default-alias") or "").strip()
        if alias and not str(img.get("alt") or "").strip():
            img["alt"] = alias
    for wrap in _select(content, "span.confluence-embedded-file-wrapper"):
        wrap.unwrap()
    for a in _find_all(content, "a"):
        kids = [c for c in a.contents if not (isinstance(c, str) and not c.strip())]
        if (
            len(kids) == 1
            and getattr(kids[0], "name", None) == "img"
            and "attachments/" in str(a.get("href") or "")
        ):
            a.unwrap()  # thumbnail link to the full-size attachment


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

# Map classes that Confluence or highlight.js may already set → pandoc lang.
# Owned by the Stage-C filter module (PF-CODELANG, single source of truth);
# aliased here for the Stage-A handlers and existing callers/tests.
_CLASS_MAP = LANG_ALIASES


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
    # ── (§17 #1) DC 8.5.x syntaxhighlighter wrappers (HX-CODE) ───────────────
    for wrapper in _select(content, "div.code.panel"):
        pre = _select_one(wrapper, "pre.syntaxhighlighter-pre") or _find(wrapper, "pre")
        if pre is None:
            continue
        raw_code = pre.get_text()
        lang = _lang_from_syntaxhighlighter(pre)
        # Confluence defaults brush to java even for shell — distrust it ONLY
        # when the content carries an unambiguous non-java signature (HX-CODE).
        # Keyword-overlap languages (python/go/…) stay java: `class A{}` is
        # plausible java and must not be re-guessed.
        if lang == "java":
            detected = _detect_language(raw_code, [])
            if detected in {"bash", "sql", "dockerfile", "json", "yaml", "xml"}:
                lang = detected
        nodes: list[Tag] = []
        title_el = _select_one(wrapper, ".codeHeader b")
        if title_el is not None and title_el.get_text(strip=True):
            p = _new_tag(soup, "p")
            strong = _new_tag(soup, "strong")
            strong.string = title_el.get_text(strip=True)
            p.append(strong)
            nodes.append(p)  # code-macro title → bold paragraph before the fence
        nodes.append(_rebuild_pre(soup, raw_code, lang))
        wrapper.replace_with(*nodes)
        notes.add_lang(lang)
        notes.bump("code_block")

    # ── (HX-NOFORMAT) DC noformat panels → fenced block with NO language ─────
    for wrapper in _select(content, "div.preformatted.panel"):
        pre = _find(wrapper, "pre")
        if pre is None:
            continue
        nodes = []
        title_el = _select_one(wrapper, ".preformattedHeader b")
        if title_el is not None and title_el.get_text(strip=True):
            p = _new_tag(soup, "p")
            strong = _new_tag(soup, "strong")
            strong.string = title_el.get_text(strip=True)
            p.append(strong)
            nodes.append(p)
        nodes.append(_rebuild_pre(soup, pre.get_text(), ""))
        wrapper.replace_with(*nodes)
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

    # ── (§17 #4 / HX-PRE) Bare <pre> blocks: NO language detection ────────────
    #     Pasted/legacy text is usually not code in any specific language — an
    #     invented class would mint an untrusted ``lang:`` embed tag downstream.
    #     Only an EXPLICIT class already on the element is honoured (mapped).
    for pre in _find_all(content, "pre"):
        code = _find(pre, "code")
        # Skip blocks already normalised above (their <code> carries language-*).
        if code is not None and any("language-" in c for c in _as_list(code.get("class"))):
            continue
        if code:
            raw_code = code.get_text()
            label = ""
            for cls in _as_list(code.get("class")):
                cls_n = cls.lower().removeprefix("language-").strip()
                if cls_n in _CLASS_MAP:
                    label = _CLASS_MAP[cls_n]
                    break
            code.string = raw_code  # strip colour spans
            if label:
                code["class"] = cast(Any, [f"language-{label}"])
            elif code.get("class") is not None:
                del code["class"]
        else:
            # Bare <pre> with no <code> — wrap it, no language class
            raw_code = pre.get_text()
            label = ""
            new_code = _new_tag(soup, "code")
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


def convert(clean_html: str, pandoc_path: str, notes: ConversionNotes | None = None) -> str:
    """Stages 2+3: pandoc html→json, in-process panflute Confluence filter
    (PF-* rules, ``confluence_pf_filter``), pandoc json→gfm.

    The reader stays at HTML defaults (``+native_divs``/``+native_spans`` turn
    the PFI elements into AST Div/Span for the filter; no ``+raw_html``). The
    writer is plain ``gfm`` — ``pipe_tables`` is a gfm default and ``+smart``
    is deliberately NOT added (the downstream gfm reader has ``-smart``, so
    nothing would ever re-smarten the injected ``---``/``...`` runs).

    Raises:
        ConversionError: if either pandoc invocation exits non-zero.
    """
    notes = notes or ConversionNotes()
    ast_json = _run_pandoc(
        pandoc_path,
        clean_html,
        ["--from", "html", "--to", "json", "--strip-comments"],
    )
    filtered = apply_confluence_filter(ast_json, notes)
    return _run_pandoc(
        pandoc_path,
        filtered,
        ["--from", "json", "--to", "gfm", "--wrap=none", "--markdown-headings=atx"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 3 — POST-PROCESSOR
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API — programmatic single-file conversion
# ═══════════════════════════════════════════════════════════════════════════════


# Storage-format front door (spec §1.2): a literal ``<ac:`` / ``<ri:`` / ``<at:``
# tag opener only occurs in Confluence *storage format* — the rendered export
# escapes code samples to ``&lt;ac:``, so this byte sequence cannot appear in
# supported rendered input. Detect it and refuse loudly rather than silently
# mangling it (lxml drops the CDATA macro bodies, etc.).
_STORAGE_FORMAT_SNIFF = re.compile(r"<(?:ac|ri|at):[A-Za-z]")


def _reject_if_storage_format(html: str, src: Path) -> None:
    """Raise :class:`ConversionError` if *html* is Confluence storage format."""
    if _STORAGE_FORMAT_SNIFF.search(html):
        raise ConversionError(
            f"{src} looks like Confluence *storage format* (ac:/ri:/at: tags), which is "
            "not supported. This converter handles *rendered HTML* exports only (Space "
            "export / 'Export to HTML'). Re-export the page as HTML and retry."
        )


def convert_file(
    src: Path,
    output: Path | None = None,
    *,
    selector: str | None = None,
    title: str = "",
    author: str = "",
    add_frontmatter: bool = True,
    add_toc: bool = False,
    keep_diagrams: bool = False,
    pandoc_path: str | None = None,
    space: str = "",
    source_url: str = "",
    labels: list[str] | None = None,
    write: bool = True,
) -> tuple[Path, str, dict[str, int], dict[str, Any]]:
    """Convert a single HTML file to GitLab-flavoured Markdown.

    Runs the full 4-stage pipeline (pre-process → pandoc html→json → panflute
    filter → pandoc json→gfm → post-process) and, when *write* is true, writes
    the result to *output* (default: ``<src>.md``).

    ``add_toc`` defaults to **False** (MD-TOC-INJECT: a ``[[_TOC_]]`` paragraph
    survives chunking as a junk chunk — opt in for human-docs output only).
    Explicit ``title``/``author``/``space`` arguments win over values harvested
    from the page chrome (``notes.metadata``).

    Returns:
        ``(output_path, markdown, metrics, notes)`` where ``metrics`` is
        :func:`stats` and ``notes`` is :meth:`ConversionNotes.to_dict`
        (``warnings`` / ``errors`` / ``macro_counts`` / ``languages`` /
        ``metadata``).

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
    _reject_if_storage_format(html, src)  # P0.1 front door — rendered HTML only
    clean_html = preprocess(html, selector, keep_diagrams, notes)
    raw_md = convert(clean_html, pandoc, notes)

    meta = notes.metadata
    page_id = meta.get("page_id", "")
    if not page_id:
        m = re.search(r"_(\d+)\.html?$", src.name)
        if m:
            page_id = m.group(1)

    final_md = postprocess(
        md=raw_md,
        title=title or meta.get("title", ""),
        author=author or meta.get("author", ""),
        source_path=src,
        add_frontmatter=add_frontmatter,
        add_toc=add_toc,
        space=space or meta.get("space", ""),
        source_url=source_url,
        labels=labels,
        date=meta.get("date", ""),
        page_id=page_id,
        notes=notes,
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
    p.add_argument(
        "--toc",
        action="store_true",
        help="Inject [[_TOC_]] (human-docs profile; default OFF for the embedding corpus)",
    )
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
            add_toc=args.toc,
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
