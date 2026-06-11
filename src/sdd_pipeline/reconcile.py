"""
Mixed-section reconciliation (T7).

A real section is often intro prose + a table + notes, so the same entity can be
found by both structural and prose extraction. Reconciliation unions the records
for a section and dedupes on canonical form: **highest confidence wins**, which
makes the table (confidence 1.0) authoritative over prose — a prose mention never
overrides a table cell's field/direction.
"""

from __future__ import annotations

from .models import EntityRecord


def reconcile(records: list[EntityRecord]) -> list[EntityRecord]:
    """Dedupe records on ``(section_id, canonical)``, keeping the highest-confidence
    one (ties broken deterministically by field then source). Output is sorted by
    ``(section_id, canonical)`` for deterministic downstream writes."""
    best: dict[tuple[str, str], EntityRecord] = {}
    for r in records:
        key = (r.section_id, r.canonical.casefold())
        cur = best.get(key)
        if cur is None or _supersedes(r, cur):
            best[key] = r
    return sorted(best.values(), key=lambda r: (r.section_id, r.canonical.casefold()))


def _supersedes(candidate: EntityRecord, incumbent: EntityRecord) -> bool:
    """True if *candidate* should replace *incumbent* for the same canonical.

    Higher confidence wins; on a tie, lower-noise wins by a stable key so the
    result never depends on input ordering.
    """
    if candidate.confidence != incumbent.confidence:
        return candidate.confidence > incumbent.confidence
    return (candidate.field, candidate.source, candidate.text) < (
        incumbent.field,
        incumbent.source,
        incumbent.text,
    )
