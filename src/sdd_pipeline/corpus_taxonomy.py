"""
Data-aligned taxonomy: derive the section→field taxonomy by scanning the *corpus*
rather than the template.

The template describes an ideal SAD; real documents diverge and often carry richer
fields. This scans every document's tables (reusing the orientation-aware
extractor from :mod:`template_taxonomy`), aggregates field names by
**document-frequency**, and keeps only fields seen in at least ``min_docs``
documents — so the operational taxonomy reflects what the corpus actually contains.

Outputs:
* ``taxonomy.json`` — ``{section_key: {fields, orientation}}`` (same shape as the
  template extractor, so ``doc_router.load_taxonomy`` consumes it unchanged).
* a **field vocabulary** ``{field: doc_freq}`` — the review artifact a human uses
  to fill ``config/field_directions.yaml`` (which field names mean
  depends_on/exposes).

Model-free; pandoc-only.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .ast_parser import generate_ast
from .models import ContentType
from .structural import build_structural_model
from .template_taxonomy import (
    _section_key,
    fields_and_orientation,
    parse_pipe_table,
)


def build_corpus_taxonomy(
    docs_dir: str | Path,
    *,
    min_docs: int = 2,
    glob: str = "**/*.md",
    from_format: str = "gfm",
) -> tuple[dict[str, dict], dict[str, int]]:
    """Scan *docs_dir* and return ``(taxonomy, field_vocabulary)``.

    ``taxonomy``: ``{section_key: {"fields": [...], "orientation": str}}`` with
    only fields whose document-frequency ≥ ``min_docs``.
    ``field_vocabulary``: ``{field: doc_freq}`` for **every** field seen (ungated),
    so rare fields are still visible for review.
    """
    # section_key → field → set(doc_id);  field → set(doc_id);  section_key → orientation → count
    section_field_docs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    field_docs: dict[str, set[str]] = defaultdict(set)
    section_orient: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for path in sorted(Path(docs_dir).glob(glob), key=lambda p: p.as_posix()):
        doc_id = path.stem
        ast = generate_ast(path, from_format)
        doc = build_structural_model(ast, doc_id=doc_id, source_path=str(path))
        for section in doc.iter_sections():
            key = _section_key(section.title)
            for block in section.blocks:
                if block.content_type != ContentType.TABLE:
                    continue
                header, rows = parse_pipe_table(block.text)
                fields, orientation = fields_and_orientation(header, rows)
                if not fields:
                    continue
                section_orient[key][orientation] += 1
                for field in fields:
                    section_field_docs[key][field].add(doc_id)
                    field_docs[field].add(doc_id)

    taxonomy: dict[str, dict] = {}
    for key, fmap in section_field_docs.items():
        kept = sorted(f for f, docs in fmap.items() if len(docs) >= min_docs)
        if not kept:
            continue
        # Deterministic orientation: highest count, then alphabetical.
        orientation = sorted(section_orient[key].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        taxonomy[key] = {"fields": kept, "orientation": orientation}

    field_vocabulary = {f: len(docs) for f, docs in field_docs.items()}
    return taxonomy, field_vocabulary


def taxonomy_to_json(taxonomy: dict[str, dict]) -> str:
    """Canonical taxonomy JSON (sorted keys + field lists)."""
    canon = {
        k: {"fields": sorted(v["fields"]), "orientation": v["orientation"]}
        for k, v in taxonomy.items()
    }
    return json.dumps(canon, sort_keys=True, ensure_ascii=False, indent=2)


def vocabulary_to_json(vocab: dict[str, int]) -> str:
    """Field vocabulary JSON, sorted by descending doc-frequency then name."""
    ordered = dict(sorted(vocab.items(), key=lambda kv: (-kv[1], kv[0])))
    return json.dumps(ordered, ensure_ascii=False, indent=2)
