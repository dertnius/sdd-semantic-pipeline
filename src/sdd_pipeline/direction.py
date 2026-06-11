"""
Field-name → dependency-direction resolution.

Loads ``config/field_directions.yaml`` (the reviewed, data-grounded map) and
answers: does this table field name mean ``depends_on``, ``exposes``, or neither?
Both the config entries and the queried field are passed through
:func:`header_norm.normalise_header`, so spelling/plural/spacing variants match.
Direction is decided **only** by name — never by a column's position.
"""

from __future__ import annotations

from pathlib import Path

from .header_norm import normalise_header

DEFAULT_DIRECTIONS_PATH = Path("config/field_directions.yaml")

# Resolved direction is one of these two Section/SemanticChunk fields, or None.
Direction = str  # "depends_on" | "exposes"


def load_field_directions(path: str | Path = DEFAULT_DIRECTIONS_PATH) -> dict[str, Direction]:
    """Return ``{normalised_field_name: "depends_on"|"exposes"}``.

    Missing file → ``{}`` (no field routes to a direction; all go to metadata).
    """
    p = Path(path)
    if not p.exists():
        return {}

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "PyYAML is required to read config/field_directions.yaml; install it with 'pip install pyyaml'."
        ) from e

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, Direction] = {}
    for direction in ("depends_on", "exposes"):
        for name in raw.get(direction, []) or []:
            norm = normalise_header(str(name))
            if norm:
                out[norm] = direction
    return out


def resolve_direction(field: str, directions: dict[str, Direction]) -> Direction | None:
    """Return ``"depends_on"`` / ``"exposes"`` for *field*, or ``None`` if unmapped."""
    return directions.get(normalise_header(field))
