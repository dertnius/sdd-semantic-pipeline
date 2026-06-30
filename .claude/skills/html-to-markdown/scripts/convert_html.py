#!/usr/bin/env python3
"""
convert_html.py -- batch Confluence / generic HTML -> GitLab Markdown.

Wraps :func:`html_to_gitlab_md.convert_file` (the 4-stage pipeline: BeautifulSoup
pre-clean -> pandoc html->json -> in-process panflute filter -> pandoc json->gfm
-> fence-aware post-process) so a folder of exported HTML can be converted without
installing the parent pipeline. Output is ASCII-only (Windows cp1252-safe).

Usage
-----
  python convert_html.py INPUT [-o OUTDIR] [options]

INPUT may be a single ``.html`` file or a directory (recurses for ``**/*.html``).
For a single file the lower-level script also runs directly:
  python html_to_gitlab_md.py page.html -o page.md

Requires: pandoc on PATH, plus ``beautifulsoup4``, ``lxml``, ``panflute``, ``PyYAML``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # vendored standalone: flat sibling imports (scripts/ on sys.path)
    from base import ConversionError
    from html_to_gitlab_md import convert_file
except ImportError:  # package mode
    from .base import ConversionError
    from .html_to_gitlab_md import convert_file


def _iter_inputs(inp: Path) -> list[Path]:
    if inp.is_dir():
        return sorted(p for p in inp.rglob("*.htm*") if p.suffix.lower() in (".html", ".htm"))
    return [inp]


def _out_for(src: Path, root: Path, out_dir: Path | None) -> Path | None:
    if out_dir is None:
        return None
    rel = src.relative_to(root) if root.is_dir() else Path(src.name)
    return out_dir / rel.with_suffix(".md")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convert Confluence / generic HTML to GitLab-flavoured Markdown.",
    )
    p.add_argument("input", type=Path, help="An .html file or a directory of them")
    p.add_argument("-o", "--out-dir", type=Path, default=None, help="Output dir (mirrors the tree)")
    p.add_argument("--selector", default=None, help="CSS selector for the main content root")
    p.add_argument("--no-frontmatter", action="store_true", help="Skip YAML frontmatter")
    p.add_argument("--toc", action="store_true", help="Inject [[_TOC_]] (default OFF)")
    p.add_argument("--keep-diagrams", action="store_true", help="Keep SVG diagrams instead of captioning")
    p.add_argument("--space", default="", help="Confluence space key for frontmatter")
    p.add_argument("--source-url", default="", help="Canonical source URL for frontmatter")
    p.add_argument("--pandoc-path", default="", help="Path to pandoc if not on PATH")
    args = p.parse_args(argv)

    inputs = _iter_inputs(args.input)
    if not inputs:
        print(f"no .html found at {args.input}", file=sys.stderr)
        return 2

    ok = 0
    for src in inputs:
        out = _out_for(src, args.input, args.out_dir)
        try:
            out_path, _md, metrics, notes = convert_file(
                src,
                out,
                selector=args.selector,
                add_frontmatter=not args.no_frontmatter,
                add_toc=args.toc,
                keep_diagrams=args.keep_diagrams,
                space=args.space,
                source_url=args.source_url,
                pandoc_path=args.pandoc_path or None,
            )
        except ConversionError as exc:
            print(f"FAIL {src.name}: {exc}", file=sys.stderr)
            continue
        ok += 1
        warn = len(notes.get("warnings", []))
        print(
            f"OK   {src.name} -> {out_path}  "
            f"({metrics['sections']} sections, {metrics['tables']} tables, "
            f"{metrics['code_snippets']} code, {warn} warning(s))"
        )
    print(f"\n{ok}/{len(inputs)} converted.")
    return 0 if ok == len(inputs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
