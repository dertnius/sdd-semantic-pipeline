r"""Dump the model-free artifacts for one markdown file: AST, enriched
structural model, and chunks.

Runs pandoc -> structural -> enrich -> chunk only. No embedding model is
loaded and nothing is downloaded. Requires pandoc on PATH.

Usage (from the project root, with the project venv):

    .\.venv\Scripts\python.exe -m sdd_pipeline.dump inbox\path\to\your-file.md [out-dir]

The input file must live under the inbox and the out-dir under the outbox (the
workspace contract); out-dir defaults to outbox/dump. Writes
<out-dir>/{ast,enriched,chunks}.json. Set PIPELINE_ENFORCE_WORKSPACE=false to
bypass the contract.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from sdd_pipeline.ast_parser import generate_ast
from sdd_pipeline.enrichment import enrich_document
from sdd_pipeline.pipeline import SemanticPipeline
from sdd_pipeline.workspace import (
    OUTBOX_DUMP,
    WorkspaceError,
    resolve_input,
    resolve_output_dir,
)


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

    pipe = SemanticPipeline()  # embedder is lazy; nothing below touches it
    cfg = pipe.config
    # Enforce the workspace contract: input under the inbox, artifacts under the
    # outbox (default outbox/dump). resolve_output_dir creates the directory.
    try:
        resolve_input(md, inbox_dir=cfg.inbox_dir, enforce=cfg.enforce_workspace)
        out = resolve_output_dir(
            sys.argv[2] if len(sys.argv) > 2 else None,
            outbox_dir=cfg.outbox_dir,
            enforce=cfg.enforce_workspace,
            default_subpath=OUTBOX_DUMP,
        )
    except WorkspaceError as exc:
        print(exc)
        return 2

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
