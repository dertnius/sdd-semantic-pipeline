#!/usr/bin/env python3
"""
docx_to_md.py
=============
Convert a Word ``.docx`` document to clean GitLab-flavoured Markdown.

Unlike the HTML path (``html_to_gitlab_md``), docx needs **no** BeautifulSoup
pre-clean and **no** panflute Stage-C filter: pandoc's docx reader handles the
document structure (headings, lists, tables, code, footnotes) natively. The flow
is therefore short and pandoc-native:

  Stage 1 — Harvest  : read ``docProps/core.xml`` for title/author/date
                       (stdlib ``zipfile`` + ``xml`` — no pandoc, deterministic)
  Stage 2 — Read+Write: pandoc ``docx → gfm`` (one process; ``--extract-media``
                       pulls embedded images out so links resolve on disk)
  Stage 3 — Post      : the shared fence-aware GFM cleanup + YAML-safe
                       frontmatter (``base.postprocess``)

It reuses the engine-agnostic shared layer in :mod:`sdd_pipeline.convert.base`
(pandoc wrapper, postprocess/frontmatter/stats, error/notes contracts), so the
bs4-bound HTML code is never imported on this path.

Public API: :func:`convert_docx_file` — mirrors
:func:`sdd_pipeline.convert.html_to_gitlab_md.convert_file`'s
``(out_path, markdown, metrics, notes)`` return so a batch caller (the
``convert-docx`` CLI command) can treat both converters uniformly.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# Shared engine-agnostic layer (flow-B helpers). The fallback branch supports
# script mode (`python src/sdd_pipeline/convert/docx_to_md.py`) under an editable
# install, mirroring html_to_gitlab_md.
try:
    from .base import (
        ConversionError,
        ConversionNotes,
        postprocess,
        resolve_pandoc,
        run_pandoc_file,
        stats,
    )
except ImportError:  # script mode: python …/convert/docx_to_md.py
    from sdd_pipeline.convert.base import (
        ConversionError,
        ConversionNotes,
        postprocess,
        resolve_pandoc,
        run_pandoc_file,
        stats,
    )


# OOXML core-property tag (localname) → notes.metadata key. The XML carries
# namespace prefixes (dc:, cp:, dcterms:) that we strip to the localname, so the
# map stays namespace-agnostic. ``date`` prefers the authored (created) date.
_CORE_PROPS = {
    "title": "title",
    "creator": "author",
    "created": "date",
}


def harvest_docx_metadata(src: Path) -> dict[str, str]:
    """Read title/author/date from a docx's ``docProps/core.xml`` (stdlib only).

    A ``.docx`` is a zip; its core properties live in ``docProps/core.xml`` as
    Dublin-Core elements. This is the docx analogue of the HTML path's
    ``_harvest_page_chrome`` — it feeds the frontmatter so converted files carry
    provenance even when the caller passes no explicit ``title``/``author``.

    Returns an empty dict (never raises) when the part is absent or unparseable —
    metadata is best-effort and must not fail a conversion.
    """
    meta: dict[str, str] = {}
    try:
        with zipfile.ZipFile(src) as zf, zf.open("docProps/core.xml") as fh:
            root = ET.parse(fh).getroot()
    except (KeyError, OSError, zipfile.BadZipFile, ET.ParseError):
        return meta

    for el in root:
        localname = el.tag.rsplit("}", 1)[-1]  # "{ns}title" → "title"
        key = _CORE_PROPS.get(localname)
        if key is None:
            continue
        text = (el.text or "").strip()
        if text:
            meta.setdefault(key, text)
    return meta


def _is_docx(src: Path) -> bool:
    """True if *src* is a real OOXML package (zip containing word/document.xml)."""
    if not zipfile.is_zipfile(src):
        return False
    try:
        with zipfile.ZipFile(src) as zf:
            return "word/document.xml" in zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def convert_docx_file(
    src: Path,
    output: Path | None = None,
    *,
    title: str = "",
    author: str = "",
    add_frontmatter: bool = True,
    add_toc: bool = False,
    extract_media: bool = True,
    pandoc_path: str | None = None,
    space: str = "",
    source_url: str = "",
    labels: list[str] | None = None,
    write: bool = True,
) -> tuple[Path, str, dict[str, int], dict[str, Any]]:
    """Convert a single ``.docx`` file to GitLab-flavoured Markdown.

    Runs harvest → ``pandoc docx→gfm`` → postprocess and, when *write* is true,
    writes the result to *output* (default ``<src>.md``). Embedded images are
    extracted to a ``media/`` folder next to the output (pandoc rewrites the
    links to point there) unless *extract_media* is false, in which case images
    are dropped (their links would be dead anyway — fine for an embedding
    corpus). ``add_toc`` defaults to **False** (a ``[[_TOC_]]`` paragraph is a
    junk chunk downstream — opt in for human-docs output).

    Explicit ``title``/``author``/``space`` arguments win over values harvested
    from the docx core properties.

    Returns ``(output_path, markdown, metrics, notes)`` where ``metrics`` is
    :func:`stats` and ``notes`` is :meth:`ConversionNotes.to_dict`.

    Raises:
        ConversionError: if the source is missing, is not a valid docx, or pandoc
            fails.
    """
    src = Path(src)
    if not src.exists():
        raise ConversionError(f"input file not found: {src}")
    if not _is_docx(src):
        raise ConversionError(
            f"{src} is not a valid .docx (Word/OOXML) file. The docx converter handles "
            "Word .docx packages only; for .doc re-save as .docx, for HTML use `convert`."
        )

    out_path = Path(output) if output is not None else src.with_suffix(".md")
    pandoc = resolve_pandoc(pandoc_path)
    notes = ConversionNotes()

    meta = harvest_docx_metadata(src)
    notes.metadata.update(meta)

    # pandoc docx → gfm in one process. ``-implicit_figures`` keeps a captioned
    # image as a plain ``![alt](src)`` instead of a raw ``<figure>``/``<img>``
    # HTML block — raw HTML is not a valid link, is not stripped by --no-media,
    # and would poison the downstream chunk gate (which blocks <img>/<figure>).
    args = [
        "--from",
        "docx",
        "--to",
        "gfm-implicit_figures",
        "--wrap=none",
        "--markdown-headings=atx",
    ]
    if extract_media:
        # Run pandoc *from* the output directory with a relative extract path so
        # the rewritten links are clean and relative to the .md (``media/<file>``)
        # — not the absolute, backslashed outbox path pandoc embeds otherwise.
        media_parent = out_path.parent
        media_parent.mkdir(parents=True, exist_ok=True)
        args.append("--extract-media=.")
        raw_md = run_pandoc_file(pandoc, src.resolve(), args, cwd=media_parent)
    else:
        # No extraction: the embedded media never lands on disk, so every
        # ``![alt](media/…)`` link is dead — replace each image with its alt text
        # (the only retrievable signal) rather than ship a broken-link junk token.
        raw_md = _strip_images(run_pandoc_file(pandoc, src, args))

    final_md = postprocess(
        md=raw_md,
        title=title or meta.get("title", "") or src.stem.replace("_", " ").replace("-", " "),
        author=author or meta.get("author", ""),
        source_path=src,
        add_frontmatter=add_frontmatter,
        add_toc=add_toc,
        space=space,
        source_url=source_url,
        labels=labels,
        date=meta.get("date", ""),
        notes=notes,
    )

    if write:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final_md, encoding="utf-8")

    return out_path, final_md, stats(final_md), notes.to_dict()


def _strip_images(md: str) -> str:
    """Replace ``![alt](src)`` image links with their alt text.

    Used when media is not extracted: the image file is not on disk, so a kept
    ``![](…)`` link is dead weight (and a base64-free junk token). The alt text,
    when present, is the only retrievable content.
    """
    return re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1).strip(), md)
