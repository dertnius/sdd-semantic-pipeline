"""
Derive a section→field taxonomy from an SAD template.

The template defines, per section, the *fields* a conforming document should
fill in — encoded as tables. Two orientations occur (see SPIKE_FINDINGS.md):

* **wide** — a real header row whose cells are the field names (one entity per
  body row). Body rows are template samples and are **not** read.
* **key-value** — an empty header row; field names live in **body column 0**
  and values in column 1 (the Solution Component tables). Column 1 holds
  ``[Describe …]`` placeholders and is **not** read.

Output (``data/taxonomy.json``): ``normalised_section → {fields, orientation}``.
The pipe-table parser and :func:`fields_and_orientation` are reused by
``extract_structural`` to read live-document tables.

Run standalone:  ``python -m sdd_pipeline.template_taxonomy <template.md>``
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .ast_parser import generate_ast
from .header_norm import normalise_header
from .models import ContentType, DocumentModel, Section
from .structural import build_structural_model

# Split a pipe-table row on '|' that is not escaped as '\|'.
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
# A separator row: each cell is like ---, :--, --:, :-:
_SEP_CELL = re.compile(r"^:?-+:?$")
_LEAD_NUM = re.compile(r"^[\d.]+\s*")  # "5.1.1 Solution Component" → "Solution Component"


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.replace("\\|", "|").strip() for c in _CELL_SPLIT.split(line)]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEP_CELL.match(c) for c in cells if c != "") and any(cells)


def parse_pipe_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Parse a GFM pipe-table string into ``(header_cells, body_rows)``.

    Reverses the escaping done by ``structural._serialize_table``. The separator
    row (``| --- | … |``) is dropped. A table with no separator yields an empty
    header and all rows as body.
    """
    rows = [_split_row(ln) for ln in text.splitlines() if ln.strip()]
    if not rows:
        return [], []
    header: list[str] = []
    body_start = 0
    if len(rows) >= 2 and _is_separator(rows[1]):
        header = rows[0]
        body_start = 2
    elif _is_separator(rows[0]):
        body_start = 1
    body = [r for r in rows[body_start:] if not _is_separator(r)]
    return header, body


def _is_placeholder(cell: str) -> bool:
    """True for an empty cell or a ``[instructional]`` placeholder."""
    c = cell.strip()
    return not c or (c.startswith("[") and c.endswith("]"))


def fields_and_orientation(header: list[str], rows: list[list[str]]) -> tuple[list[str], str]:
    """Return ``(normalised_field_names, "wide" | "key_value")`` for one table.

    Wide ⇒ at least one non-empty header cell; fields are the header cells.
    Key-value ⇒ all header cells blank; fields are body column 0 (placeholders
    skipped). Field order is preserved; duplicates removed.
    """
    norm_header = [normalise_header(h) for h in header]
    if any(norm_header):
        fields = [h for h in norm_header if h]
        return _dedupe(fields), "wide"

    fields = []
    for r in rows:
        if r and not _is_placeholder(r[0]):
            f = normalise_header(r[0])
            if f:
                fields.append(f)
    return _dedupe(fields), "key_value"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _walk(sections: list[Section]):
    for s in sections:
        yield s
        yield from _walk(s.subsections)


def _section_key(title: str) -> str:
    return normalise_header(_LEAD_NUM.sub("", title))


def extract_taxonomy(template_md_path: str | Path) -> dict[str, dict]:
    """Walk the template and return ``{section_key: {fields, orientation}}``."""
    path = Path(template_md_path)
    ast = generate_ast(path, "gfm")
    doc: DocumentModel = build_structural_model(ast, doc_id="template", source_path=str(path))

    taxonomy: dict[str, dict] = {}
    for section in _walk(doc.root_sections):
        tables = [b for b in section.blocks if b.content_type == ContentType.TABLE]
        if not tables:
            continue
        fields: list[str] = []
        orientation = ""
        for tbl in tables:
            header, rows = parse_pipe_table(tbl.text)
            f, orient = fields_and_orientation(header, rows)
            fields.extend(f)
            orientation = orient  # last table's orientation; sections rarely mix
        fields = _dedupe(fields)
        if not fields:
            continue
        key = _section_key(section.title)
        if key in taxonomy:
            taxonomy[key]["fields"] = _dedupe(taxonomy[key]["fields"] + fields)
        else:
            taxonomy[key] = {"fields": fields, "orientation": orientation}
    return taxonomy


def to_canonical_json(taxonomy: dict[str, dict]) -> str:
    """Deterministic serialization (sorted keys, sorted field lists)."""
    canon = {
        k: {"fields": sorted(v["fields"]), "orientation": v["orientation"]}
        for k, v in taxonomy.items()
    }
    return json.dumps(canon, sort_keys=True, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m sdd_pipeline.template_taxonomy <template.md> [out.json]")
        return 2
    template = Path(argv[0])
    out = Path(argv[1]) if len(argv) > 1 else Path("data/taxonomy.json")
    taxonomy = extract_taxonomy(template)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_canonical_json(taxonomy) + "\n", encoding="utf-8")
    print(f"Wrote {len(taxonomy)} section taxonomy entries → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
