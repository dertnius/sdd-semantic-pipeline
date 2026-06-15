"""
Structural entity extraction from document tables (PATH A).

Tables reach the model as GFM pipe-strings (structural.py flattens them and
leaves ``raw`` unset — see docs/notes/SPIKE_FINDINGS.md), so this re-parses the string and
emits one :class:`EntityRecord` per meaningful cell, tagged with its **field
name** (never its position). Orientation is detected per table:

* **wide** — header cells are field names; each body cell → a record under its
  column's field.
* **key-value** — empty header; each body row is ``(field=col0, value=col1)``.

Matching live-document columns to the taxonomy happens **by name** downstream
(enrichment), so reordered / missing / extra columns are tolerated: extraction
is heading-independent and records carry whatever field label the table itself
provides. ``[instructional]`` placeholders and empty cells are skipped.
"""

from __future__ import annotations

from .header_norm import normalise_header
from .models import ContentType, DocumentModel, EntityInventory, EntityRecord, Section
from .template_taxonomy import _is_placeholder, parse_pipe_table

# A 2-column table whose header is a generic ``Field | Value`` pairing is really a
# key-value table, not a wide one — treating it as wide would emit useless records
# named "field"/"value". The real field names live in column 0 (the body), so such
# a table is routed through the key-value branch despite having a (generic) header.
_KV_FIELD_HEADERS = frozenset(
    {"field", "key", "name", "property", "parameter", "setting", "attribute", "option"}
)
_KV_VALUE_HEADERS = frozenset({"value", "values", "description", "detail", "details"})


def _is_key_value_header(norm_header: list[str]) -> bool:
    return (
        len(norm_header) == 2
        and norm_header[0] in _KV_FIELD_HEADERS
        and norm_header[1] in _KV_VALUE_HEADERS
    )


def _records_from_table(section_id: str, text: str) -> list[EntityRecord]:
    header, rows = parse_pipe_table(text)
    norm_header = [normalise_header(h) for h in header]
    out: list[EntityRecord] = []

    # wide: columns are fields, each body cell is a value — UNLESS the header is a
    # generic Field|Value pairing, in which case it is really key-value.
    if any(norm_header) and not _is_key_value_header(norm_header):
        for row in rows:
            for idx, cell in enumerate(row):
                if idx >= len(norm_header):
                    continue  # extra body column with no header — drop
                field = norm_header[idx]
                value = cell.strip()
                if not field or not value or _is_placeholder(value):
                    continue
                out.append(EntityRecord(value, field, "table_cell", 1.0, section_id))
    else:  # key-value: col 0 is the field label, col 1 the value
        for row in rows:
            if len(row) < 2:
                continue
            field = normalise_header(row[0])
            value = row[1].strip()
            if not field or not value or _is_placeholder(value):
                continue
            out.append(EntityRecord(value, field, "table_cell", 1.0, section_id))
    return out


def extract_structural(section: Section) -> list[EntityRecord]:
    """Emit table-cell entity records for one section (recurses into none)."""
    out: list[EntityRecord] = []
    for block in section.blocks:
        if block.content_type == ContentType.TABLE:
            out.extend(_records_from_table(section.section_id, block.text))
    return out


def build_structural_inventory(doc: DocumentModel) -> EntityInventory:
    """Structural records for every section in *doc*, keyed by section_id."""
    inventory: EntityInventory = {}
    for section in doc.iter_sections():
        records = extract_structural(section)
        if records:
            inventory[section.section_id] = records
    return inventory
