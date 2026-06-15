"""
Document-type router.

Selects which taxonomy applies to a document. With a single SAD template this is
deliberately light: a document that looks like an SAD (its top-level headings
match the template's section fingerprint) is routed to the SAD taxonomy; anything
else gets an empty taxonomy and falls back to heading-only / prose enrichment.

Kept minimal on purpose — multi-template routing is not built until more than one
template exists to exercise it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .header_norm import normalise_header
from .models import DocumentModel
from .template_taxonomy import _LEAD_NUM

logger = logging.getLogger(__name__)

# Top-level section headings that characterise a SAD (normalised by
# ``normalise_header`` — lowercased + naive-singularised). The first group is the
# formal template; the second covers *pragmatic* SADs that use numbered, topical
# headings (Architecture / Components / Data Model / Decision Record) instead. A
# doc still needs ``threshold`` (default 3) matches, so a lone "Architecture"
# heading in a generic doc does not trip the SAD route.
SAD_FINGERPRINT = frozenset(
    {
        "introduction",
        "requirement",
        "quality attribute",
        "baseline solution architecture",
        "target solution architecture",
        "architecture",
        "component",
        "data model",
        "decision record",
    }
)

DEFAULT_TAXONOMY_PATH = Path("config/taxonomy.json")


def _heading_keys(doc: DocumentModel) -> set[str]:
    """Normalised, number-stripped headings across all sections."""
    return {normalise_header(_LEAD_NUM.sub("", s.title)) for s in doc.iter_sections()}


def detect_doc_type(doc: DocumentModel, threshold: int = 3) -> str:
    """Return ``"sad"`` if the document matches the SAD fingerprint, else ``"unknown"``."""
    overlap = _heading_keys(doc) & SAD_FINGERPRINT
    doc_type = "sad" if len(overlap) >= threshold else "unknown"
    logger.info("doc_type=%s (fingerprint overlap=%d: %s)", doc_type, len(overlap), sorted(overlap))
    return doc_type


def load_taxonomy(path: str | Path = DEFAULT_TAXONOMY_PATH) -> dict[str, dict]:
    """Load a taxonomy JSON; missing file → ``{}`` (heading-only fallback)."""
    p = Path(path)
    if not p.exists():
        logger.warning("taxonomy file %s not found; using empty taxonomy", p)
        return {}
    data: dict[str, dict] = json.loads(p.read_text(encoding="utf-8"))
    return data


def taxonomy_for(doc: DocumentModel, sad_taxonomy: dict[str, dict]) -> dict[str, dict]:
    """Route a document to its taxonomy. SAD → the SAD taxonomy; else ``{}``."""
    if detect_doc_type(doc) == "sad":
        return sad_taxonomy
    logger.info("non-SAD document routed to empty taxonomy (heading-only enrichment)")
    return {}
