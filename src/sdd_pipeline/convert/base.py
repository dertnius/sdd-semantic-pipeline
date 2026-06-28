"""
Engine-agnostic conversion utilities shared across the ``convert`` subpackage.

These pieces don't care whether the source was HTML or (soon) docx: the pandoc
subprocess wrapper, the GFM post-process / YAML-safe frontmatter / metrics text
layer, and the conversion notes/error contracts. The HTML-specific pre-clean and
Stage-C panflute filter live in ``html_to_gitlab_md`` / ``confluence_pf_filter``;
a future ``docx_to_md`` will import from here too — which is why the bs4-bound
HTML code is kept out of this module's import graph.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml


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
    # Provenance harvested from page chrome (HX-CHROME-TITLE/-METADATA):
    # title / space / author / date / page_id — feeds the frontmatter.
    metadata: dict[str, str] = field(default_factory=dict)

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
            "metadata": dict(self.metadata),
        }


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


def _run_pandoc(pandoc_path: str, input_text: str, args: list[str]) -> str:
    """Run one pandoc subprocess (UTF-8 in/out); raise ConversionError on failure."""
    result = subprocess.run(
        [pandoc_path, *args],
        input=input_text.encode("utf-8"),
        capture_output=True,
    )
    if result.returncode != 0:
        raise ConversionError(f"pandoc error:\n{result.stderr.decode()}")
    return result.stdout.decode("utf-8")


def run_pandoc_file(
    pandoc_path: str, src: Path, args: list[str], *, cwd: Path | None = None
) -> str:
    """Run pandoc reading a *binary* file positionally (UTF-8 stdout).

    The docx reader needs the source as a real file argument — pandoc unzips it
    and pulls embedded media — so it cannot go through stdin like the HTML path's
    :func:`_run_pandoc`. ``stderr`` is decoded leniently (a pandoc warning may
    carry non-UTF-8 bytes) and raised as :class:`ConversionError` on failure.

    *cwd* runs pandoc from a working directory (with *src* given absolutely):
    used so a relative ``--extract-media=.`` yields image links relative to the
    output file rather than an absolute, backslashed path.
    """
    result = subprocess.run(
        [pandoc_path, str(src), *args],
        capture_output=True,
        cwd=str(cwd) if cwd is not None else None,
    )
    if result.returncode != 0:
        raise ConversionError(f"pandoc error:\n{result.stderr.decode('utf-8', 'replace')}")
    return result.stdout.decode("utf-8")


# ── Stage-D text layer: post-process, frontmatter, metrics (engine-agnostic) ──


def _apply_outside_fences(md: str, fn: Callable[[str], str]) -> str:
    """Apply *fn* to prose segments only, leaving fenced code byte-identical.

    Stage-D fence-awareness (conversion-rules §6): unguarded regexes silently
    corrupt fenced code (a ``\\``-only shell-continuation line, literal ``\\*``
    in regex examples, blank-line runs). Mirrors ``quality.py``'s de-fence
    approach: 3+ backticks/tildes open a fence; the closer must use the same
    marker character with at least the opener's length.
    """
    segments: list[str] = []
    prose: list[str] = []
    code: list[str] = []
    fence_marker: str | None = None

    def flush_prose() -> None:
        if prose:
            segments.append(fn("\n".join(prose)))
            prose.clear()

    for line in md.split("\n"):
        stripped = line.lstrip()
        if fence_marker is None:
            m = re.match(r"^(`{3,}|~{3,})", stripped)
            if m:
                flush_prose()
                fence_marker = m.group(1)
                code.append(line)
            else:
                prose.append(line)
        else:
            code.append(line)
            m = re.match(r"^(`{3,}|~{3,})\s*$", stripped)
            if m and m.group(1)[0] == fence_marker[0] and len(m.group(1)) >= len(fence_marker):
                segments.append("\n".join(code))
                code.clear()
                fence_marker = None
    if code:
        segments.append("\n".join(code))  # unclosed fence — keep verbatim
    flush_prose()
    return "\n".join(segments)


def _dump_frontmatter(fm: dict[str, Any], notes: ConversionNotes | None) -> str:
    """FM-YAML-SAFE: serialize via a real YAML dumper + round-trip self-check.

    Naive f-string quoting breaks on embedded quotes (``OPS : Deploy "v2"``);
    the downstream gfm reader has ``+yaml_metadata_block``, and a failed parse
    degrades the ``---`` block into document content — title/url lines leak
    into the first section's chunks and ALL provenance is lost.
    """

    def dump(d: dict[str, Any]) -> str:
        text = yaml.safe_dump(d, sort_keys=False, allow_unicode=True, default_flow_style=False)
        return cast(str, text).strip()

    body = dump(fm)
    try:
        yaml.safe_load(body)
    except yaml.YAMLError:
        fm = {
            k: (re.sub(r'[\x00-\x1f"]', "", v) if isinstance(v, str) else v) for k, v in fm.items()
        }
        body = dump(fm)
        if notes is not None:
            notes.warn("frontmatter sanitized: harvested values produced invalid YAML")
    return f"---\n{body}\n---\n"


def _infer_title(md: str, path: Path) -> str:
    """Derive a title from the first H1 in the markdown, or the filename."""
    m = re.search(r"^# (.+)", md, re.M)
    if m:
        return m.group(1).strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


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
    date: str = "",
    page_id: str = "",
    notes: ConversionNotes | None = None,
) -> str:
    """Clean up pandoc's GFM output for GitLab compatibility (fence-aware)."""

    # ── MD-NBSP (global): &nbsp; (decoded to U+00A0) → regular space ─────────
    md = md.replace(" ", " ")

    # ── MD-FENCE-SPACE — targets fence-opener lines themselves, runs global ──
    md = re.sub(r"^``` (\w)", r"```\1", md, flags=re.M)

    def _prose_fixes(text: str) -> str:
        # MD-UNESCAPE-EMPH: over-escaped bold/italic inside blockquotes
        text = re.sub(r"\\(\*\*)", r"\1", text)
        text = re.sub(r"\\(\*)", r"\1", text)
        # MD-TASKBOX: pandoc escapes "- [ ]" → "- \[ \]" (storage-form backstop)
        text = re.sub(r"(^\s*[-*+] )\\\[( |x)\\\]", r"\1[\2]", text, flags=re.M)
        # MD-TOC-ESCAPED: over-escaped [[_TOC_]] remnants
        text = re.sub(r"\\_Table of contents[^\n]+\\\[\\\[\\?_TOC_\\\]\\\]\\_", "", text)
        # MD-BLANKLINES: collapse 3+ blank lines (prose only — fences keep theirs)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # MD-TRAILWS: trim trailing whitespace per line
        return "\n".join(line.rstrip() for line in text.split("\n"))

    # NOTE: the draft's angle-bracket unescape was deliberately DELETED
    # (conversion-rules §6): un-escaping pandoc's ``\<`` resurrects raw HTML —
    # ``List\<String\>`` becomes ``List<String>``, which GitLab swallows as an
    # unknown tag and which trips the quality lint.
    md = _apply_outside_fences(md, _prose_fixes)

    # ── Ensure single trailing newline ──────────────────────────────────────
    md = md.rstrip("\n") + "\n"

    # ── Build YAML front matter (FM-YAML-SAFE; keys structural reads back) ───
    header_parts: list[str] = []

    if add_frontmatter:
        fm: dict[str, Any] = {"title": title or _infer_title(md, source_path)}
        if author:
            fm["author"] = author  # singular — the key _extract_metadata reads
        if space:
            fm["space"] = space
        if source_url:
            fm["url"] = source_url
        if labels:
            fm["labels"] = list(labels)
        if date:
            fm["date"] = date
        if page_id:
            fm["page_id"] = page_id
        fm["source_file"] = source_path.name
        header_parts.append(_dump_frontmatter(fm, notes))

    if add_toc:
        header_parts.append("[[_TOC_]]\n")

    if header_parts:
        md = "\n".join(header_parts) + "\n" + md.lstrip()

    return md


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
