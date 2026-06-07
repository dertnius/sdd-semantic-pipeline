"""
Entity-vocabulary persistence.

Thin JSON I/O helpers kept out of ``enrichment.py`` (which is declared pure — no
I/O, no network). The vocabulary file is grown by the cross-corpus scan
(:func:`sdd_pipeline.enrichment.scan_corpus`) and re-loaded as ``seed_terms`` on
the next run, so coverage accumulates over time. Commit it to source control — it
is project knowledge, not a build artefact.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path


def load_vocabulary(path: Path | str) -> list[str]:
    """Load a vocabulary file previously written by :func:`save_vocabulary`.

    Returns an empty list when the file does not exist — safe for first runs.
    """
    p = Path(path)
    if not p.exists():
        return []
    data: list[str] = json.loads(p.read_text(encoding="utf-8"))
    return data


def save_vocabulary(path: Path | str, terms: Iterable[str]) -> None:
    """Persist *terms* as a sorted, deduplicated, human-readable JSON array.

    Parent directories are created as needed.
    """
    data = sorted({t.strip() for t in terms if t and t.strip()})
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
