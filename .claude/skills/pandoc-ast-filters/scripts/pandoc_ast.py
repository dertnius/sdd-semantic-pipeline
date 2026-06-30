#!/usr/bin/env python3
"""
pandoc_ast.py -- read Markdown/HTML into pandoc's JSON AST, transform it
in-process with a panflute filter, and render it back.

This is the reusable core of the "pandoc-as-a-library" pattern: instead of
shelling out to a one-shot ``pandoc in.md -o out.md`` you split the conversion
into READ -> FILTER -> WRITE and own the middle step. Three helpers:

  to_ast(text, from_format)        -> pandoc JSON AST (str)
  from_ast(ast_json, to_format)    -> rendered text
  apply_filter(ast_json)           -> (filtered AST, notes), using the bundled
                                      Confluence panflute filter as a worked example

UTF-8 is pinned on every pandoc subprocess (pandoc always emits UTF-8; this avoids
the Windows cp1252 decode crash).

CLI
---
  python pandoc_ast.py dump FILE [--from gfm]                 # print the JSON AST
  python pandoc_ast.py roundtrip FILE [--from gfm --to gfm]   # read -> AST -> write
  python pandoc_ast.py filter FILE [--from html --to gfm]     # read -> AST -> filter -> write

Requires: pandoc on PATH. The ``filter`` subcommand also needs ``panflute``
(``pip install panflute``); ``dump`` / ``roundtrip`` need only pandoc.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_MD_WRITERS = {"gfm", "markdown", "commonmark", "commonmark_x", "markdown_strict"}


def _run_pandoc(input_text: str, args: list[str]) -> str:
    """Run one pandoc subprocess (UTF-8 in/out); raise RuntimeError on failure."""
    proc = subprocess.run(["pandoc", *args], input=input_text.encode("utf-8"), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc error:\n{proc.stderr.decode('utf-8', 'replace')}")
    return proc.stdout.decode("utf-8")


def to_ast(text: str, from_format: str = "gfm") -> str:
    """Read *text* into pandoc's JSON AST string."""
    return _run_pandoc(text, ["--from", from_format, "--to", "json"])


def _md_extras(to_format: str) -> list[str]:
    base = to_format.split("+")[0].split("-")[0]
    return ["--wrap=none", "--markdown-headings=atx"] if base in _MD_WRITERS else []


def from_ast(ast_json: str, to_format: str = "gfm") -> str:
    """Render a pandoc JSON AST back to *to_format* text."""
    return _run_pandoc(ast_json, ["--from", "json", "--to", to_format, *_md_extras(to_format)])


class Notes:
    """Minimal notes sink satisfying ``confluence_pf_filter.SupportsNotes``."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.counts: dict[str, int] = {}
        self.langs: list[str] = []

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def add_lang(self, lang: str) -> None:
        if lang and lang not in self.langs:
            self.langs.append(lang)


def apply_filter(ast_json: str) -> tuple[str, Notes]:
    """Apply the bundled Confluence panflute filter to a JSON AST string."""
    try:  # vendored standalone: flat sibling import (scripts/ on sys.path)
        from confluence_pf_filter import apply_confluence_filter
    except ImportError:  # package mode
        from .confluence_pf_filter import apply_confluence_filter
    notes = Notes()
    return apply_confluence_filter(ast_json, notes), notes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Round-trip text through pandoc's JSON AST and run panflute filters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dump", help="print the pandoc JSON AST")
    d.add_argument("file", type=Path)
    d.add_argument("--from", dest="from_format", default="gfm")
    d.add_argument("--indent", type=int, default=2)

    r = sub.add_parser("roundtrip", help="read -> AST -> write (no filter)")
    r.add_argument("file", type=Path)
    r.add_argument("--from", dest="from_format", default="gfm")
    r.add_argument("--to", dest="to_format", default="gfm")

    f = sub.add_parser("filter", help="read -> AST -> Confluence filter -> write")
    f.add_argument("file", type=Path)
    f.add_argument("--from", dest="from_format", default="html")
    f.add_argument("--to", dest="to_format", default="gfm")

    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252-safe stdout
    text = args.file.read_text(encoding="utf-8")

    if args.cmd == "dump":
        ast = to_ast(text, args.from_format)
        print(json.dumps(json.loads(ast), indent=args.indent, ensure_ascii=False))
        return 0
    if args.cmd == "roundtrip":
        sys.stdout.write(from_ast(to_ast(text, args.from_format), args.to_format))
        return 0
    if args.cmd == "filter":
        filtered, notes = apply_filter(to_ast(text, args.from_format))
        sys.stdout.write(from_ast(filtered, args.to_format))
        if notes.counts:
            sys.stderr.write(f"\n[filter] {notes.counts}\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
