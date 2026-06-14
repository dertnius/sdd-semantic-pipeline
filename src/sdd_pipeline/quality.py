"""
Raw-source ``.md`` quality lint — pre-pandoc, report-only.

Audits a markdown *source file* for syntax/structure that degrades embedding
quality once it reaches the vector: leaked HTML tags, un-translated Confluence
macros, whole-doc code dumps, TOC/nav link-dumps, near-empty stubs, and
genuinely-empty section headings.

This is a diagnostic only — it never drops, blocks, or rewrites anything; the
``lint`` CLI command surfaces a :class:`MarkdownQualityReport` per file. Logic is
pure (no I/O, no network), deterministic, and stdlib-only, matching the style of
``enrichment.py`` / ``chunking.py``.

The prose checks run on a *de-fenced* copy of the source (fenced ``` ``` ``` /
``~~~`` blocks, 4-space indented blocks, and inline ``code`` are blanked out)
so that an HTML/macro *example shown inside a code block* is not mistaken for
leaked residue. ``code_ratio`` is the one check that runs on the raw text,
because it needs the code it is measuring. De-fencing preserves line numbering
(code lines become empty lines), so reported line numbers map back to the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import SemanticChunk

# ── Thresholds (first-pass guesses — calibrate against a real corpus run) ──────
_HTML_LEAK_BLOCK = 3  # > this many HTML fragments → block (1.._ → warn)
_CODE_RATIO_WARN = 0.75  # fraction of chars that are code → warn (whole-doc dump)
_LINK_DENSITY_WARN = 0.5  # fraction of words that are link text → warn (TOC/nav)
_STUB_MIN_CHARS = 200  # fewer meaningful chars after stripping syntax → block

# ── Patterns ──────────────────────────────────────────────────────────────────
# HTML leakage in prose. ``br`` is deliberately excluded: the converter emits
# ``<br/>`` inside table cells on purpose, so flagging it would fire on our own
# intended output. The inline-text tags (u/sup/sub/s/del) and code/pre/img are
# included because pandoc's gfm writer passes them through as raw HTML — the
# converter must normalise them before they ever reach a corpus file.
_HTML_LEAKAGE = re.compile(
    r"<(?!--)(?:span|div|p|a|strong|em|table|td|tr|th|u|sup|sub|s|del|code|pre|img)\b[^>]*>"
    r"|&(?:nbsp|amp|lt|gt|quot|#\d+);",
    re.IGNORECASE,
)
# Un-translated Confluence storage-format residue.
_CONFLUENCE = re.compile(
    r"\{(?:panel|note|warning|info|tip|code)[^}]*\}|<ac:[^>]+>|<ri:[^>]+>",
    re.IGNORECASE,
)
# Code spans for the (raw-text) code-ratio measure.
_CODE_SPANS = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`]+`")
# A markdown inline link; group 1 is the visible text.
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
# Markdown structural punctuation, stripped to estimate meaningful text length.
_SYNTAX_CHARS = re.compile(r"[#*_`\[\]()>|~^\\!=+-]")
# A fence opener/closer: 3+ backticks or tildes.
_OPEN_FENCE = re.compile(r"^(`{3,}|~{3,})")
# Inline code, blanked out (with same-length whitespace) on prose lines.
_INLINE_CODE = re.compile(r"`+[^`]*`+")
# An ATX heading line; group 1 is the ``#`` run (its length is the level).
_HEADING = re.compile(r"^(#{1,6})\s+\S")


@dataclass
class QualityIssue:
    """A single quality finding for one file."""

    rule: str
    severity: str  # "block" | "warn"
    detail: str  # human-readable; carries first-occurrence line number(s)


@dataclass
class MarkdownQualityReport:
    """All quality findings for one source file."""

    source_id: str
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def is_embeddable(self) -> bool:
        """True when no ``block``-severity issue was found."""
        return not any(i.severity == "block" for i in self.issues)

    @property
    def issue_summary(self) -> dict[str, str]:
        """``{rule: detail}`` for a compact view (one issue per rule)."""
        return {i.rule: i.detail for i in self.issues}


def check_markdown(source_id: str, markdown: str) -> MarkdownQualityReport:
    """Run all quality checks on *markdown* and return a report for *source_id*."""
    de_fenced = _strip_code_preserving_lines(markdown)
    candidates = (
        _check_html_leakage(de_fenced),
        _check_confluence_artifacts(de_fenced),
        _check_code_ratio(markdown),
        _check_link_density(de_fenced),
        _check_content_density(de_fenced),
        _check_orphaned_headings(de_fenced, markdown),
    )
    return MarkdownQualityReport(
        source_id=source_id, issues=[c for c in candidates if c is not None]
    )


# ── Code stripping (line-count preserving) ────────────────────────────────────


def _strip_code_preserving_lines(markdown: str) -> str:
    """Blank out fenced/indented/inline code, keeping line positions intact.

    Code lines become empty lines (not deleted) so a regex match in the result
    has the same line number as in the source. Indented-code detection is
    heuristic (a 4-space/tab block that opens after a blank line); when in doubt
    it errs toward treating content as code, which only *under*-reports prose
    issues — the safe direction for a linter.
    """
    lines = markdown.split("\n")
    out: list[str] = []
    fence_char = ""  # "`" or "~" while inside a fenced block
    fence_len = 0
    in_indent = False
    prev_blank = True
    for raw in lines:
        stripped = raw.lstrip()
        if fence_char:
            close = re.match(r"^(`{3,}|~{3,})\s*$", stripped)
            if close and close.group(1)[0] == fence_char and len(close.group(1)) >= fence_len:
                fence_char = ""
                fence_len = 0
            out.append("")
            prev_blank = False
            continue
        opener = _OPEN_FENCE.match(stripped)
        if opener:
            fence_char = opener.group(1)[0]
            fence_len = len(opener.group(1))
            out.append("")
            prev_blank = False
            continue
        if not raw.strip():
            out.append(raw)
            in_indent = False
            prev_blank = True
            continue
        is_indented = bool(re.match(r"^( {4}|\t)", raw))
        if is_indented and (in_indent or prev_blank):
            in_indent = True
            out.append("")
            prev_blank = False
            continue
        in_indent = False
        out.append(_INLINE_CODE.sub(lambda m: " " * len(m.group(0)), raw))
        prev_blank = False
    return "\n".join(out)


def _line_of(text: str, pos: int) -> int:
    """1-based line number of character offset *pos* in *text*."""
    return text.count("\n", 0, pos) + 1


# ── Individual checks (each returns one issue or None) ─────────────────────────


def _check_html_leakage(text: str) -> QualityIssue | None:
    matches = list(_HTML_LEAKAGE.finditer(text))
    if not matches:
        return None
    line = _line_of(text, matches[0].start())
    n = len(matches)
    severity = "block" if n > _HTML_LEAK_BLOCK else "warn"
    return QualityIssue("html_leakage", severity, f"{n} HTML fragment(s) (first at line {line})")


def _check_confluence_artifacts(text: str) -> QualityIssue | None:
    matches = list(_CONFLUENCE.finditer(text))
    if not matches:
        return None
    found = sorted({m.group(0)[:24] for m in matches})
    line = _line_of(text, matches[0].start())
    return QualityIssue(
        "confluence_artifacts",
        "block",
        f"{len(matches)} untranslated macro(s) (first at line {line}): {found}",
    )


def _check_code_ratio(markdown: str) -> QualityIssue | None:
    code_chars = sum(len(m) for m in _CODE_SPANS.findall(markdown))
    total = len(markdown)
    if total == 0:
        return None
    ratio = code_chars / total
    if ratio <= _CODE_RATIO_WARN:
        return None
    return QualityIssue("code_ratio", "warn", f"{ratio:.0%} of the document is code")


def _check_link_density(text: str) -> QualityIssue | None:
    links = _MD_LINK.findall(text)
    words = len(text.split())
    if not words:
        return None
    link_words = sum(len(t.split()) for t in links)
    ratio = link_words / words
    if ratio <= _LINK_DENSITY_WARN:
        return None
    return QualityIssue(
        "link_density", "warn", f"{ratio:.0%} of words are link text (likely a TOC/nav page)"
    )


def _check_content_density(text: str) -> QualityIssue | None:
    stripped = _SYNTAX_CHARS.sub("", text)
    meaningful = re.sub(r"\s+", " ", stripped).strip()
    if len(meaningful) >= _STUB_MIN_CHARS:
        return None
    return QualityIssue(
        "content_density",
        "block",
        f"only {len(meaningful)} chars of substantive text (near-empty stub)",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Chunk-level hygiene gate (the binding gate — runs on produced chunks)
# ══════════════════════════════════════════════════════════════════════════════
#
# ``check_markdown`` above audits *raw source markdown*; it is a useful pre-filter
# but it cannot see the chunk transforms that happen downstream of it (merge,
# table-summary, embed-budget split). The chunk gate runs on the rendered
# ``SemanticChunk.to_embed_text()`` / content — the thing that actually becomes a
# vector — and is the binding "poisoned → block, weak → warn" check.
#
# It is an *invariant / structural-absence* check, not a residue blocklist: clean
# rendered prose simply cannot contain markup *shape*. So the test is "does this
# look like markup?" rather than "is this on my list of known-bad strings", which
# makes it robust to constructs the converter has never seen. Code chunks are
# exempt from the markup-shape check (code legitimately contains ``<``/``{``/``:``);
# ``<br>`` is exempt everywhere because the converter emits ``<br />`` in table
# cells on purpose (mirrors ``_HTML_LEAKAGE``).

# Tag residue is flagged only when it carries a *real markup signal*, not on any
# bare ``<word>`` — because technical docs legitimately use angle-bracket
# placeholder notation (``<output>``, ``<filename>``, ``<replace_file>``) that is
# structurally identical to an HTML element. The signals:
#   1. a known structural HTML tag (the raw-source linter's set; excludes ``br``,
#      intended in table cells, and form-ish names like ``output``/``input`` that
#      double as placeholders);
_CHUNK_KNOWN_TAG = re.compile(
    r"</?(?:span|div|p|a|strong|em|table|td|tr|th|thead|tbody|ul|ol|li|h[1-6]|"
    r"blockquote|u|sup|sub|s|del|code|pre|img|hr)\b",
    re.IGNORECASE,
)
#   2. a namespaced Confluence storage tag (``<ac:image …>`` etc.);
_CHUNK_NS_TAG = re.compile(r"</?(?:ac|ri|at|fab):[A-Za-z]")
#   3. an (unknown) opening tag that carries attributes, or any closing tag —
#      real markup, unlike a lone ``<placeholder>``.
_CHUNK_MARKUP = re.compile(
    r"<[A-Za-z][A-Za-z0-9:.-]*\s+[^<>]*=[^<>]*?/?>|</[A-Za-z][A-Za-z0-9:.-]*\s*>"
)
# A bare Confluence storage-namespace token surviving into prose (``ac:image`` …).
# Requires a letter immediately after the colon, so prose like "At: see below"
# (space after colon) does not match.
_CHUNK_NS = re.compile(r"(?:^|[^\w])(?:ac|ri|at|fab):[A-Za-z][\w-]*")
# HTML entity that should have been rendered to a Unicode char by the gfm writer.
_CHUNK_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#\d+|#x[0-9A-Fa-f]+);")
# A long base64 run — a leftover data-URI payload.
_CHUNK_BASE64 = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
_REPLACEMENT_CHAR = "�"


@dataclass
class ChunkQualityReport:
    """Hygiene findings for one produced :class:`SemanticChunk`."""

    chunk_id: str
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True when no ``block``-severity (poisoned) issue was found."""
        return not any(i.severity == "block" for i in self.issues)

    @property
    def poison(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == "block"]


def check_chunk(
    chunk: SemanticChunk,
    *,
    embed_char_budget: int = 1800,
    embed_char_hard_cap: int = 2048,
) -> ChunkQualityReport:
    """Audit one chunk's rendered embed text for poison (vector-corrupting) issues.

    *Poisoned* (``block``) — the vector would be **certainly** wrong: markup/macro
    residue in the prose or metadata, or no content. These are model-free,
    unambiguous, and block the file.

    *Weak* (``warn``) — the vector is merely degraded, not wrong: over the embed
    budget (and, past the hard cap, likely truncated by the model). Truncation is
    model- and tokenizer-dependent and cannot be *certified* from a char count, so
    it is surfaced as a warning rather than blocking — keeping embed text within
    budget is chunking's job (see ``chunking._header_reserve``). Code chunks are
    exempt from the markup-shape residue check; the budget and empty checks apply.
    """
    issues: list[QualityIssue] = []
    is_code = getattr(chunk.content_type, "value", chunk.content_type) == "code"

    # ── Positive: the chunk must carry signal ────────────────────────────────
    if not re.search(r"[A-Za-z0-9]", (chunk.content or "").replace("`", "")):
        issues.append(QualityIssue("chunk_empty", "block", "chunk has no alphanumeric content"))

    # ── Markup-shape residue in the content (prose/table only) ────────────────
    if not is_code:
        body = _strip_code_preserving_lines(chunk.content or "")
        issues += _scan_residue(body, "content")

    # ── Residue in the metadata that feeds the embed header ───────────────────
    header_values = "\n".join([*chunk.breadcrumb, chunk.title or "", *chunk.entities, *chunk.tags])
    issues += _scan_residue(header_values, "metadata")

    # ── Budget: over the hard cap = likely truncated; over target = fat ───────
    # Both are *warnings* — truncation is model-dependent and not certifiable from
    # a char count, so it never blocks the file (chunking owns budget adherence).
    embed_len = len(chunk.to_embed_text())
    if embed_len > embed_char_hard_cap:
        issues.append(
            QualityIssue(
                "chunk_truncation_risk",
                "warn",
                f"embed_text is {embed_len} chars (> hard cap {embed_char_hard_cap}); "
                "the model will likely truncate the vector — split this section smaller",
            )
        )
    elif embed_len > embed_char_budget:
        issues.append(
            QualityIssue(
                "chunk_over_budget",
                "warn",
                f"embed_text is {embed_len} chars (> target {embed_char_budget})",
            )
        )

    return ChunkQualityReport(chunk_id=chunk.chunk_id, issues=issues)


def _scan_residue(text: str, where: str) -> list[QualityIssue]:
    """Return ``block`` issues for any markup/macro shape found in *text*.

    Legitimate ``lang:python`` style metadata tags match none of these shapes
    (the namespace scan only fires on ``ac:``/``ri:``/``at:``/``fab:`` prefixes),
    so they pass cleanly; everything that matches a tag / storage-namespace /
    entity / macro / base64 shape is treated as poison.
    """
    out: list[QualityIssue] = []
    if _CHUNK_KNOWN_TAG.search(text) or _CHUNK_NS_TAG.search(text) or _CHUNK_MARKUP.search(text):
        out.append(QualityIssue(f"chunk_html_residue_{where}", "block", f"HTML/XML tag in {where}"))
    if _CHUNK_NS.search(text):
        out.append(
            QualityIssue(
                f"chunk_macro_residue_{where}", "block", f"Confluence ac:/ri: token in {where}"
            )
        )
    if _CONFLUENCE.search(text):
        out.append(
            QualityIssue(
                f"chunk_macro_residue_{where}", "block", f"Confluence macro braces in {where}"
            )
        )
    if _CHUNK_ENTITY.search(text):
        out.append(
            QualityIssue(
                f"chunk_entity_residue_{where}", "block", f"unrendered HTML entity in {where}"
            )
        )
    if _CHUNK_BASE64.search(text):
        out.append(QualityIssue(f"chunk_base64_{where}", "block", f"long base64 blob in {where}"))
    if _REPLACEMENT_CHAR in text:
        out.append(
            QualityIssue(
                f"chunk_replacement_char_{where}", "block", f"U+FFFD replacement char in {where}"
            )
        )
    return out


def _check_orphaned_headings(de_fenced: str, raw: str) -> QualityIssue | None:
    # Headings are detected on the de-fenced text (so a ``#`` comment inside a
    # code block is not mistaken for a heading), but body presence is judged on
    # the RAW text — a section whose only content is a code block is NOT empty.
    df_lines = de_fenced.split("\n")
    raw_lines = raw.split("\n")
    heads = [
        (idx, len(m.group(1))) for idx, line in enumerate(df_lines) if (m := _HEADING.match(line))
    ]
    orphans: list[int] = []
    for i, (idx, level) in enumerate(heads):
        next_idx = heads[i + 1][0] if i + 1 < len(heads) else len(raw_lines)
        next_level = heads[i + 1][1] if i + 1 < len(heads) else 0  # EOF = highest rank
        has_body = any(raw_lines[k].strip() for k in range(idx + 1, next_idx))
        # A heading that opens with a *deeper* subsection (next_level > level) is
        # fine; only flag when nothing precedes a same-or-higher heading / EOF.
        if not has_body and next_level <= level:
            orphans.append(idx + 1)
    if not orphans:
        return None
    return QualityIssue(
        "orphaned_headings",
        "warn",
        f"{len(orphans)} empty section heading(s) (first at line {orphans[0]})",
    )
