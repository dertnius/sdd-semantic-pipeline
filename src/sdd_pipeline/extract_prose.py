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

from .models import ContentType, DocumentModel, EntityInventory, EntityRecord, EntitySource, Section

_ALLCAPS = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*\b")
# Inline code, single-line only: forbidding a newline keeps one match from
# swallowing a multi-line fenced block (and copes with an unclosed fence).
_BACKTICK = re.compile(r"`([^`\n]+)`")
_PASCAL = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")  # multi-word PascalCase
_KEBAB = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")  # multi-word kebab-case
_PATH = re.compile(r"\b\w+(?:/\w+){2,}\b")  # a/b/c style paths

# Block types that are never prose-mined. Tables are already covered by the
# structural inventory (one record per cell); code must not be mined as prose.
_NON_PROSE = frozenset({ContentType.CODE, ContentType.TABLE})
# Fenced code blocks (``` or ~~~). Blanked before mining so code nested inside a
# list/blockquote block — which structural.py folds into the prose text — is not
# harvested. Inline `code` is deliberately left intact (the backtick signal).
_FENCED = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")

# ALLCAPS tokens that are markers, not entities.
_ALLCAPS_STOP = frozenset(
    {"TODO", "NOTE", "FIXME", "WARNING", "INFO", "TIP", "OK", "ID", "URL", "API", "N/A"}
)
_MIN_ALLCAPS_LEN = 3


# spaCy NER labels we surface, mapped to a compact metadata field kind. These land
# in ``metadata["ner:<kind>"]`` (a filterable/display facet) and are deliberately
# EXCLUDED from the embed vector (see SemanticChunk.to_embed_text), because a
# model-derived signal in the vector would make embeddings depend on whether spaCy
# is installed — breaking reproducibility (the provenance check cannot detect that).
_NER_LABELS = {"PERSON": "person", "ORG": "org", "GPE": "place", "LOC": "place", "DATE": "date"}
# Confidence for NER records: above the 0.6 enrichment threshold so they route to a
# named ``ner:<kind>`` metadata field, but below table cells (1.0) and ALLCAPS (0.9).
_NER_CONFIDENCE = 0.7


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


def _named_entities(text: str) -> list[tuple[str, str]]:
    """``(entity_text, kind)`` pairs via spaCy NER, or [] when spaCy is unavailable.

    Guarded exactly like :func:`_noun_chunks`: never required, inert when spaCy or
    the model is absent, so the pipeline stays model-free by default.
    """
    try:  # optional; never required
        import spacy  # type: ignore[import-not-found]
    except ImportError:
        return []

    try:
        nlp = spacy.load("en_core_web_sm")
        out: list[tuple[str, str]] = []
        for ent in nlp(text).ents:
            kind = _NER_LABELS.get(ent.label_)
            if kind:
                out.append((ent.text, kind))
        return out
    except Exception:
        return []


def extract_prose(section_id: str, text: str, *, enable_ner: bool = True) -> list[EntityRecord]:
    """Mine entity records from one block of prose text.

    When *enable_ner* is set and spaCy is installed, named entities
    (person/org/place/date) are emitted under a ``ner:<kind>`` field; they reach
    metadata/display but never the embed vector.
    """
    out: list[EntityRecord] = []
    seen: set[str] = set()

    def add(value: str, source: EntitySource, confidence: float, field: str = "") -> None:
        value = value.strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(EntityRecord(value, field, source, confidence, section_id))

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
    if enable_ner:
        for value, kind in _named_entities(text):
            add(value, "noun_chunk", _NER_CONFIDENCE, field=f"ner:{kind}")
    return out


def _section_text(section: Section) -> str:
    """Prose-only text for one section: code/table blocks dropped, fenced code
    (incl. code nested in list/blockquote blocks) blanked. Inline ``code`` stays."""
    text = "\n".join(b.text for b in section.blocks if b.content_type not in _NON_PROSE)
    return _FENCED.sub(" ", text)


def build_prose_inventory(doc: DocumentModel, *, enable_ner: bool = True) -> EntityInventory:
    """Prose entity records for every section in *doc*, keyed by section_id."""
    inventory: EntityInventory = {}
    for section in doc.iter_sections():
        records = extract_prose(section.section_id, _section_text(section), enable_ner=enable_ner)
        if records:
            inventory[section.section_id] = records
    return inventory
