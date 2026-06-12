"""
Prose entity extraction (both PATH A and PATH B).

Mines candidate entities from section prose with confidence below the 1.0 that
structural table cells get. Pure-regex families always run; a spaCy noun-chunk
layer is optional and inert when no model is installed (the import is guarded),
so the pipeline never requires a model.

Sources / confidence:
* ``allcaps_regex`` 0.9 — ``ACME_SERVICE``, ``KPO`` (ALLCAPS / SNAKE_CASE tokens)
* ``backtick_regex`` 0.8 — backtick-fenced ``code`` tokens
* ``prose`` 0.6 — PascalCase, kebab-case, slash/paths (multi-token only)
* ``noun_chunk`` 0.5 — multi-word spaCy noun chunks (optional)

Records carry ``field=""`` (no column); enrichment routes unbucketed prose to the
general entity list / ``metadata.raw_entities``. A short stoplist drops common
non-entity ALLCAPS markers (TODO, NOTE, …).
"""

from __future__ import annotations

import re

from .models import DocumentModel, EntityInventory, EntityRecord, EntitySource, Section

_ALLCAPS = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*\b")
_BACKTICK = re.compile(r"`([^`]+)`")
_PASCAL = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")  # multi-word PascalCase
_KEBAB = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")  # multi-word kebab-case
_PATH = re.compile(r"\b\w+(?:/\w+){2,}\b")  # a/b/c style paths

# ALLCAPS tokens that are markers, not entities.
_ALLCAPS_STOP = frozenset(
    {"TODO", "NOTE", "FIXME", "WARNING", "INFO", "TIP", "OK", "ID", "URL", "API", "N/A"}
)
_MIN_ALLCAPS_LEN = 3


def _noun_chunks(text: str) -> list[str]:
    """Multi-word noun chunks via spaCy, or [] when spaCy/model is unavailable."""
    try:  # optional; never required
        import spacy  # type: ignore[import-not-found]
    except ImportError:
        return []

    try:
        # Use an installed English pipeline if present; otherwise treat as unavailable.
        nlp = spacy.load("en_core_web_sm")
        doc = nlp(text)
        return [c.text for c in doc.noun_chunks if len(c.text.split()) > 1]
    except Exception:
        return []


def extract_prose(section_id: str, text: str) -> list[EntityRecord]:
    """Mine entity records from one block of prose text."""
    out: list[EntityRecord] = []
    seen: set[str] = set()

    def add(value: str, source: EntitySource, confidence: float) -> None:
        value = value.strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(EntityRecord(value, "", source, confidence, section_id))

    for tok in _ALLCAPS.findall(text):
        if len(tok) >= _MIN_ALLCAPS_LEN and tok not in _ALLCAPS_STOP:
            add(tok, "allcaps_regex", 0.9)
    for tok in _BACKTICK.findall(text):
        add(tok, "backtick_regex", 0.8)
    for tok in _PASCAL.findall(text):
        add(tok, "prose", 0.6)
    for tok in _KEBAB.findall(text):
        add(tok, "prose", 0.6)
    for tok in _PATH.findall(text):
        add(tok, "prose", 0.6)
    for tok in _noun_chunks(text):
        add(tok, "noun_chunk", 0.5)
    return out


def _section_text(section: Section) -> str:
    return "\n".join(b.text for b in section.blocks)


def build_prose_inventory(doc: DocumentModel) -> EntityInventory:
    """Prose entity records for every section in *doc*, keyed by section_id."""
    inventory: EntityInventory = {}
    for section in doc.iter_sections():
        records = extract_prose(section.section_id, _section_text(section))
        if records:
            inventory[section.section_id] = records
    return inventory
