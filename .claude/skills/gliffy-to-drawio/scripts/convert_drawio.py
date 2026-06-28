#!/usr/bin/env python3
"""
convert_drawio.py -- standalone CLI: Confluence Gliffy (.gliffy) -> draw.io (.drawio).

Wraps :func:`drawio.convert_gliffy_to_drawio_file`. draw.io imports ``.gliffy``
natively but only in the online app (no headless/CLI path); this gives a
reproducible, testable ``.gliffy -> .drawio`` route. With ``--check`` it runs the
round-trip fidelity oracle (parse -> emit -> re-parse -> compare) per file and
exits non-zero on any mismatch.

Pure standard library -- no pandoc, no third-party dependency.

Usage
-----
  python convert_drawio.py INPUT [-o OUTDIR] [--check]

INPUT may be a single ``.gliffy`` file or a directory (recurses for ``**/*.gliffy``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # vendored standalone: flat sibling imports (scripts/ on sys.path)
    from drawio import convert_gliffy_to_drawio_file
    from errors import ConversionError
    from fidelity import roundtrip_check
except ImportError:  # package mode
    from .drawio import convert_gliffy_to_drawio_file
    from .errors import ConversionError
    from .fidelity import roundtrip_check


def _iter_inputs(inp: Path) -> list[Path]:
    if inp.is_dir():
        return sorted(inp.rglob("*.gliffy"))
    return [inp]


def _out_for(src: Path, root: Path, out_dir: Path | None) -> Path | None:
    if out_dir is None:
        return None
    rel = src.relative_to(root) if root.is_dir() else Path(src.name)
    return out_dir / rel.with_suffix(".drawio")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Convert a Confluence Gliffy diagram to draw.io XML.")
    p.add_argument("input", type=Path, help="A .gliffy file or a directory of them")
    p.add_argument("-o", "--out-dir", type=Path, default=None, help="Output dir (mirrors the tree)")
    p.add_argument(
        "--check",
        action="store_true",
        help="Run the round-trip fidelity oracle per file (exit non-zero on mismatch)",
    )
    args = p.parse_args(argv)

    inputs = _iter_inputs(args.input)
    if not inputs:
        print(f"no .gliffy found at {args.input}", file=sys.stderr)
        return 2

    ok = 0
    all_faithful = True
    for src in inputs:
        out = _out_for(src, args.input, args.out_dir)
        try:
            out_path, _xml, metrics = convert_gliffy_to_drawio_file(src, out)
            verdict = ""
            if args.check:
                result = roundtrip_check(src.read_text(encoding="utf-8-sig"))
                faithful = result["equal"]
                all_faithful = all_faithful and faithful
                verdict = "  [check: OK]" if faithful else f"  [check: {len(result['diffs'])} DIFFS]"
        except ConversionError as exc:
            print(f"FAIL {src.name}: {exc}", file=sys.stderr)
            all_faithful = False
            continue
        ok += 1
        print(
            f"OK   {src.name} -> {out_path}  "
            f"({metrics['nodes']} nodes, {metrics['edges']} edges, "
            f"{metrics['placeholders']} placeholders){verdict}"
        )
    print(f"\n{ok}/{len(inputs)} converted.")
    return 0 if ok == len(inputs) and all_faithful else 1


if __name__ == "__main__":
    raise SystemExit(main())
