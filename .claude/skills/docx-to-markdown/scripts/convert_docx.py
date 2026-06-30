#!/usr/bin/env python3
"""
convert_docx.py -- standalone CLI for the Word .docx -> Markdown converter.

Wraps :func:`docx_to_md.convert_docx_file` so a folder of Word documents can be
batch-converted without installing the parent pipeline. Output is ASCII-only so
it is safe on a redirected Windows (cp1252) console.

Usage
-----
  python convert_docx.py INPUT [-o OUTDIR] [options]

INPUT may be a single ``.docx`` file or a directory (recurses for ``**/*.docx``).
With no ``-o`` the ``.md`` is written next to each source; with ``-o`` the output
tree is mirrored under OUTDIR. Embedded images land in a ``media/`` folder next
to the ``.md`` unless ``--no-media`` is given.

Requires: pandoc on PATH (https://pandoc.org/installing.html) and PyYAML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # vendored standalone: flat sibling imports (scripts/ on sys.path)
    from base import ConversionError
    from docx_to_md import convert_docx_file
except ImportError:  # package mode
    from .base import ConversionError
    from .docx_to_md import convert_docx_file


def _iter_inputs(inp: Path) -> list[Path]:
    if inp.is_dir():
        return sorted(inp.rglob("*.docx"))
    return [inp]


def _out_for(src: Path, root: Path, out_dir: Path | None) -> Path | None:
    if out_dir is None:
        return None
    rel = src.relative_to(root) if root.is_dir() else Path(src.name)
    return out_dir / rel.with_suffix(".md")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convert Word .docx to GitLab-flavoured Markdown (pandoc-native).",
    )
    p.add_argument("input", type=Path, help="A .docx file or a directory of them")
    p.add_argument("-o", "--out-dir", type=Path, default=None, help="Output dir (mirrors the tree)")
    p.add_argument("--no-frontmatter", action="store_true", help="Skip YAML frontmatter")
    p.add_argument("--toc", action="store_true", help="Inject [[_TOC_]] (default OFF)")
    p.add_argument("--no-media", action="store_true", help="Drop images instead of extracting them")
    p.add_argument("--title", default="", help="Override the document title")
    p.add_argument("--author", default="", help="Override the author")
    p.add_argument("--pandoc-path", default="", help="Path to pandoc if not on PATH")
    args = p.parse_args(argv)

    inputs = _iter_inputs(args.input)
    if not inputs:
        print(f"no .docx found at {args.input}", file=sys.stderr)
        return 2

    ok = 0
    for src in inputs:
        out = _out_for(src, args.input, args.out_dir)
        try:
            out_path, _md, metrics, _notes = convert_docx_file(
                src,
                out,
                title=args.title,
                author=args.author,
                add_frontmatter=not args.no_frontmatter,
                add_toc=args.toc,
                extract_media=not args.no_media,
                pandoc_path=args.pandoc_path or None,
            )
        except ConversionError as exc:
            print(f"FAIL {src}: {exc}", file=sys.stderr)
            continue
        ok += 1
        print(
            f"OK   {src.name} -> {out_path}  "
            f"({metrics['sections']} sections, {metrics['tables']} tables, "
            f"{metrics['pictures']} images)"
        )
    print(f"\n{ok}/{len(inputs)} converted.")
    return 0 if ok == len(inputs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
