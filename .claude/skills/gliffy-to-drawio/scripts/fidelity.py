#!/usr/bin/env python3
"""
fidelity.py
===========
Conversion-fidelity oracles for the Gliffy → draw.io path.

**Primary oracle — semantic-model round-trip (deterministic, no deps).**
:func:`roundtrip_check` runs ``parse_gliffy`` → :func:`model_to_drawio` →
:func:`drawio_to_model` and diffs the two :class:`DiagramModel`s with
:func:`compare_models`. It proves the emitter and parser are **self-consistent** —
every field we write we read back identically — and that the XML is well-formed.

What it does NOT prove (by design): that draw.io *the app* renders the file
correctly (needs a human / headless export), nor that ``parse_gliffy`` captured the
Gliffy source faithfully (covered separately by gliffy→model unit tests). Both are
out of scope for an automatable oracle.

**Secondary oracle — PNG regression (optional, gated).**
:func:`png_regression_check` rasterizes the SVG renderer's output and compares it
to a golden image — a drift tripwire on ``render_gliffy``, *not* cross-tool
Gliffy-vs-draw.io equality. It lazily imports ``cairosvg`` + ``pillow`` (the
``[raster]`` extra), so importing this module never requires them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

try:  # vendored standalone: flat sibling imports (scripts/ on sys.path)
    from diagram_model import DiagramModel
    from drawio import drawio_to_model, model_to_drawio
    from gliffy_to_svg import parse_gliffy
except ImportError:  # package mode (dropped into a package)
    from .diagram_model import DiagramModel
    from .drawio import drawio_to_model, model_to_drawio
    from .gliffy_to_svg import parse_gliffy


# ── primary oracle: semantic-model comparison ────────────────────────────────────


def _field_equal(field: str, va: Any, vb: Any, tol: float) -> bool:
    """Compare one canonical field — numerics within *tol*, points element-wise, else ==."""
    if field == "points":
        if not isinstance(va, list) or not isinstance(vb, list) or len(va) != len(vb):
            return False
        return all(
            abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
            for a, b in zip(va, vb, strict=False)
        )
    # bool is an int subclass — handled here too (True vs False differ by 1 > tol)
    if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
        return abs(va - vb) <= tol
    return bool(va == vb)


def compare_models(a: DiagramModel, b: DiagramModel, *, tol: float = 0.5) -> dict[str, Any]:
    """Diff two diagram models by element id; floats compared within *tol* px.

    Returns ``{"equal": bool, "summary": {...}, "diffs": [...]}`` where each diff is
    ``{"collection", "id", "field", "a", "b"}``. ``<missing>``/``<extra>`` mark ids
    present on only one side. Canvas size/background are intentionally not compared.
    """
    da, db = a.to_dict(), b.to_dict()
    diffs: list[dict[str, Any]] = []

    def cmp_collection(name: str) -> None:
        ma = {x["id"]: x for x in da[name]}
        mb = {x["id"]: x for x in db[name]}
        for cid in sorted(ma.keys() - mb.keys()):
            diffs.append({"collection": name, "id": cid, "field": "<missing>", "a": cid, "b": None})
        for cid in sorted(mb.keys() - ma.keys()):
            diffs.append({"collection": name, "id": cid, "field": "<extra>", "a": None, "b": cid})
        for cid in sorted(ma.keys() & mb.keys()):
            xa, xb = ma[cid], mb[cid]
            for field, va in xa.items():
                vb = xb.get(field)
                if not _field_equal(field, va, vb, tol):
                    diffs.append({"collection": name, "id": cid, "field": field, "a": va, "b": vb})

    cmp_collection("nodes")
    cmp_collection("edges")

    summary = {
        "nodes_a": len(da["nodes"]),
        "nodes_b": len(db["nodes"]),
        "edges_a": len(da["edges"]),
        "edges_b": len(db["edges"]),
        "diffs": len(diffs),
    }
    return {"equal": not diffs, "summary": summary, "diffs": diffs}


def roundtrip_check(gliffy_data: str | dict[str, Any], *, tol: float = 0.5) -> dict[str, Any]:
    """``parse_gliffy`` → emit draw.io → parse back → :func:`compare_models`.

    The authoritative fidelity oracle for the emitter/parser pair. Returns the
    :func:`compare_models` result dict (``equal``/``summary``/``diffs``).
    """
    model_g = parse_gliffy(gliffy_data)
    xml, _metrics = model_to_drawio(model_g)
    model_d = drawio_to_model(xml)
    return compare_models(model_g, model_d, tol=tol)


# ── secondary oracle: PNG regression (optional, gated) ───────────────────────────


def render_svg_to_png(svg_text: str, *, scale: float = 1.0) -> bytes:
    """Rasterize an SVG string to PNG bytes (requires the ``[raster]`` extra)."""
    import cairosvg  # lazy: only when the secondary oracle runs

    return cast(bytes, cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), scale=scale))


def write_golden_png(svg_text: str, path: Path, *, scale: float = 1.0) -> Path:
    """Render *svg_text* and write it as a golden PNG (test/setup helper)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_svg_to_png(svg_text, scale=scale))
    return path


def png_regression_check(
    svg_text: str, golden_png: Path, *, threshold: float = 0.0, scale: float = 1.0
) -> dict[str, Any]:
    """Compare *svg_text*'s rasterization to a committed golden PNG.

    Returns ``{"equal": bool, "diff_ratio": float, ["reason": str]}`` where
    ``diff_ratio`` is the fraction of differing pixels. ``equal`` is true when the
    ratio is ``<= threshold``. A missing golden or a size mismatch is reported as
    not-equal (not raised). Requires the ``[raster]`` extra.
    """
    import io

    from PIL import Image, ImageChops  # lazy: only when the secondary oracle runs

    golden_png = Path(golden_png)
    current = Image.open(io.BytesIO(render_svg_to_png(svg_text, scale=scale))).convert("RGBA")
    if not golden_png.exists():
        return {"equal": False, "diff_ratio": 1.0, "reason": f"golden missing: {golden_png}"}
    golden = Image.open(golden_png).convert("RGBA")
    if current.size != golden.size:
        return {
            "equal": False,
            "diff_ratio": 1.0,
            "reason": f"size {current.size} != golden {golden.size}",
        }
    diff = ImageChops.difference(current, golden)
    if diff.getbbox() is None:
        return {"equal": True, "diff_ratio": 0.0}
    nonzero = sum(diff.convert("L").histogram()[1:])  # pixels with any channel difference
    total = current.size[0] * current.size[1]
    ratio = nonzero / total if total else 0.0
    return {"equal": ratio <= threshold, "diff_ratio": ratio}
