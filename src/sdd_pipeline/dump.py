"""Dump the model-free artifacts for one markdown file: AST, enriched
structural model, and chunks.

Runs pandoc -> structural -> enrich -> chunk only. No embedding model is
loaded and nothing is downloaded. Requires pandoc on PATH.

Usage (from the inner project root, with the project venv):

    .\.venv\Scripts\python.exe dump.py path\to\your-file.md [out-dir]

Writes <out-dir>/{ast,enriched,chunks}.json (out-dir defaults to ./out).
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from sdd_pipeline.ast_parser import generate_ast
from sdd_pipeline.enrichment import enrich_document
from sdd_pipeline.pipeline import SemanticPipeline


def _write(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    md = Path(sys.argv[1])
    if not md.is_file():
        print(f"Not a file: {md}")
        return 2
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("out")
    out.mkdir(parents=True, exist_ok=True)

    pipe = SemanticPipeline()  # embedder is lazy; nothing below touches it
    terms = pipe.config.entity_terms

    # 1) AST — raw pandoc JSON
    ast = generate_ast(md, pipe.config.pandoc_from_format)
    _write(out / "ast.json", ast)

    # 2) Enriched structural model (SectionType / entity / tag tagging applied)
    doc = pipe.parse_file(md)  # pandoc -> structural
    enriched = enrich_document(doc, entity_terms=terms)
    _write(out / "enriched.json", asdict(enriched))

    # 3) Chunks (same pass the export command emits)
    chunks = pipe.enrich_and_chunk(doc, terms)
    _write(out / "chunks.json", [c.to_dict() for c in chunks])

    print(
        f"Wrote {out / 'ast.json'}, {out / 'enriched.json'}, "
        f"{out / 'chunks.json'} ({len(chunks)} chunks)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
