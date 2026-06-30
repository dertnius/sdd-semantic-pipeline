#!/usr/bin/env python3
"""
resolve_gliffy.py -- standalone CLI: Confluence Gliffy (.gliffy JSON) -> SVG.

Wraps :func:`gliffy_to_svg.resolve_gliffy_file`. A ``.gliffy`` attachment is JSON,
not SVG; this renders it to an editable, schema-valid ``.svg``. If a sibling
``<name>.svg`` (Gliffy's own export) already exists it is copied verbatim
(exact fidelity) unless ``--always-render`` is given.

Pure standard library -- no pandoc, no third-party dependency.

Usage
-----
  python resolve_gliffy.py INPUT [-o OUTDIR] [--always-render]

INPUT may be a single ``.gliffy`` file or a directory (recurses for ``**/*.gliffy``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # vendored standalone: flat sibling imports (scripts/ on sys.path)
    from errors import ConversionError
    from gliffy_to_svg import resolve_gliffy_file
except ImportError:  # package mode
    from .errors import ConversionError
    from .gliffy_to_svg import resolve_gliffy_file


def _iter_inputs(inp: Path) -> list[Path]:
    if inp.is_dir():
        return sorted(inp.rglob("*.gliffy"))
    return [inp]


def _out_for(src: Path, root: Path, out_dir: Path | None) -> Path | None:
    if out_dir is None:
        return None
    rel = src.relative_to(root) if root.is_dir() else Path(src.name)
    return out_dir / rel.with_suffix(".svg")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render a Confluence Gliffy diagram to editable SVG.")
    p.add_argument("input", type=Path, help="A .gliffy file or a directory of them")
    p.add_argument("-o", "--out-dir", type=Path, default=None, help="Output dir (mirrors the tree)")
    p.add_argument(
        "--always-render",
        action="store_true",
        help="Render the JSON even when a sibling <name>.svg exists",
    )
    args = p.parse_args(argv)

    inputs = _iter_inputs(args.input)
    if not inputs:
        print(f"no .gliffy found at {args.input}", file=sys.stderr)
        return 2

    ok = 0
    for src in inputs:
        out = _out_for(src, args.input, args.out_dir)
        try:
            out_path, _svg, method, metrics = resolve_gliffy_file(
                src, out, prefer_existing_svg=not args.always_render
            )
        except ConversionError as exc:
            print(f"FAIL {src.name}: {exc}", file=sys.stderr)
            continue
        ok += 1
        detail = (
            f"{metrics['objects']} objects, {metrics['unsupported']} unsupported"
            if method == "rendered"
            else "copied existing SVG"
        )
        print(f"OK   {src.name} -> {out_path}  [{method}]  ({detail})")
    print(f"\n{ok}/{len(inputs)} resolved.")
    return 0 if ok == len(inputs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
