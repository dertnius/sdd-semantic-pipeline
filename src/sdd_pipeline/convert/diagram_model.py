#!/usr/bin/env python3
"""
diagram_model.py
================
A small, engine-neutral **semantic model** of a diagram — the shared currency
between the Gliffy parser (:func:`sdd_pipeline.convert.gliffy_to_svg.parse_gliffy`),
the draw.io emitter/parser (:mod:`sdd_pipeline.convert.drawio`), and the
fidelity comparator (:mod:`sdd_pipeline.convert.fidelity`).

It captures only what our basic-shape coverage models — `Node`s (boxes / text /
image / embedded-svg / dashed placeholder) and `Edge`s (poly-lines with optional
arrowheads) — normalized to absolute, top-left/y-down coordinates (the same system
Gliffy *and* draw.io use, so no axis flip is ever needed).

``to_dict()`` is the **canonical, byte-stable** form used for diffing two models:
floats rounded to 2 d.p. (matching the SVG renderer's ``_fmt``), colors lowercased,
nodes/edges sorted by id, and an embedded-svg blob reduced to a content hash so a
diff stays readable while still detecting svg loss. Only the visual contract is
canonicalized — ``parent_id`` / ``source_id`` / canvas ``width``/``height``/
``background`` are provenance fields, kept on the dataclasses but **excluded** from
``to_dict()`` (v1 emits draw.io cells flat with absolute geometry, so nesting and
canvas size do not round-trip and are not part of the fidelity check).

Pure stdlib + dataclasses — no external deps, no service logic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

# Shape kinds the model understands (mirrors gliffy_to_svg._shape_kind + the
# text/image/svg/placeholder graphic types).
NODE_KINDS = (
    "rectangle",
    "round_rectangle",
    "ellipse",
    "diamond",
    "text",
    "image",
    "svg",
    "placeholder",
)


def _round(value: float) -> float:
    """Round to 2 d.p. — matches the SVG renderer's ``_fmt`` so model and SVG agree."""
    return round(float(value), 2)


def _norm_color(color: str) -> str:
    """Lowercase a color; pass ``""``/``none``/named/hex through unchanged otherwise."""
    return str(color or "").strip().lower()


def _norm_dash(dash: str) -> str:
    """Canonicalize a dash pattern to comma-joined tokens (``"8 8"`` → ``"8,8"``)."""
    text = str(dash or "").strip()
    if not text:
        return ""
    return ",".join(text.replace(",", " ").split())


def _svg_hash(inner: str) -> str:
    """Content hash of an embedded-svg blob (keeps a diff readable, still detects loss)."""
    if not inner:
        return ""
    return hashlib.sha1(inner.encode("utf-8")).hexdigest()  # non-crypto: content fingerprint


@dataclass
class Node:
    """A box-like diagram element (shape, text label, image, embedded svg, placeholder)."""

    id: str
    kind: str
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    rotation: float = 0.0
    text: str = ""
    fill: str = "none"
    stroke: str = "#000000"
    stroke_width: float = 1.0
    dash: str = ""
    opacity: float = 1.0
    font_px: float = 14.0
    text_color: str = "#000000"
    valign: str = "middle"
    image_url: str = ""
    svg_inner: str = ""
    parent_id: str | None = None  # provenance only — not part of to_dict()/comparison

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "x": _round(self.x),
            "y": _round(self.y),
            "w": _round(self.w),
            "h": _round(self.h),
            "rotation": _round(self.rotation),
            "text": self.text,
            "fill": _norm_color(self.fill),
            "stroke": _norm_color(self.stroke),
            "stroke_width": _round(self.stroke_width),
            "dash": _norm_dash(self.dash),
            "opacity": _round(self.opacity),
            "font_px": _round(self.font_px),
            "text_color": _norm_color(self.text_color),
            "valign": self.valign,
            "image_url": self.image_url,
            "svg_hash": _svg_hash(self.svg_inner),
        }


@dataclass
class Edge:
    """A connector — an ordered poly-line of absolute points with optional arrowheads."""

    id: str
    points: list[tuple[float, float]] = field(default_factory=list)
    stroke: str = "#000000"
    stroke_width: float = 1.0
    dash: str = ""
    start_arrow: bool = False
    end_arrow: bool = False
    source_id: str | None = None  # reserved (Gliffy free paths) — not compared
    target_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "points": [[_round(px), _round(py)] for px, py in self.points],
            "stroke": _norm_color(self.stroke),
            "stroke_width": _round(self.stroke_width),
            "dash": _norm_dash(self.dash),
            "start_arrow": bool(self.start_arrow),
            "end_arrow": bool(self.end_arrow),
        }


@dataclass
class DiagramModel:
    """A whole diagram: ordered nodes + edges, plus canvas provenance."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    width: float = 0.0  # canvas provenance — not part of the fidelity contract
    height: float = 0.0
    background: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Canonical, comparison-ready form: nodes + edges, each sorted by id.

        Canvas ``width``/``height``/``background`` are intentionally omitted — v1
        emits draw.io cells flat, so they do not round-trip and are not compared.
        """
        return {
            "nodes": [n.to_dict() for n in sorted(self.nodes, key=lambda n: n.id)],
            "edges": [e.to_dict() for e in sorted(self.edges, key=lambda e: e.id)],
        }
