#!/usr/bin/env python3
"""
gliffy_to_svg.py
================
Resolve Confluence-embedded Gliffy diagrams to standalone, editable SVG.

Why this exists
---------------
A Gliffy diagram is **JSON, not SVG**, and in a *rendered* Confluence HTML export
it appears only as a raster ``<img>`` (a PNG) — the editable vector data lives in
a sibling page **attachment** (``<name>.gliffy``, sometimes ``<name>.svg``), never
in the HTML the flow-B converter (:mod:`html_to_gitlab_md`) consumes. That
converter therefore *drops* diagrams to a caption on purpose (good for the
embedding corpus, wrong for "keep it as editable SVG").

This module is the out-of-band resolver that turns the on-disk attachment into a
real ``.svg`` so a Markdown page can reference an editable, schema-valid file
instead of losing the diagram. It is the "(A) resolver" half; a later, opt-in
branch in the HTML converter consumes the manifest this produces and emits an
``![caption](media/<name>.svg)`` reference.

Resolution order (highest fidelity first)
-----------------------------------------
1. **Existing sibling SVG** — if Gliffy already exported ``<name>.svg`` next to
   ``<name>.gliffy``, copy it verbatim. Exact fidelity, already editable.
2. **Render the ``.gliffy`` JSON** — :func:`render_gliffy` walks ``stage.objects``
   and emits primitives. This is **best-effort, basic-shape coverage**:
   rectangle / rounded-rectangle / ellipse / diamond, poly-lines with arrowheads,
   text labels, embedded raster images and embedded SVG snippets. Any unrecognised
   Gliffy stencil is drawn as a dashed placeholder box (geometry preserved) and
   counted as ``unsupported`` so the report flags low-coverage diagrams.

For complex stencil-heavy diagrams the high-fidelity route is Gliffy's own SVG
export (route 1) or a draw.io import/export — see the module README / CLAUDE.md.

This module is independent of flow A (no pandoc, no embedding model, no vector
store) and of the HTML/​docx engine deps (no BeautifulSoup, no panflute). It lives
in the ``convert`` subpackage and reuses only :class:`ConversionError` from the
engine-agnostic :mod:`sdd_pipeline.convert.base` shared layer.

Public API
----------
- :func:`render_gliffy` — ``.gliffy`` JSON (str | dict) → ``(svg_text, metrics)``.
- :func:`parse_gliffy` — ``.gliffy`` JSON (str | dict) → engine-neutral
  :class:`~sdd_pipeline.convert.diagram_model.DiagramModel` (feeds the draw.io
  emitter and the fidelity harness; does not drive the SVG renderer).
- :func:`resolve_gliffy_file` — one ``.gliffy`` file → ``(out_path, svg, method,
  metrics)`` (mirrors the converters' per-file return so a batch CLI can treat
  them uniformly).
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

try:  # vendored standalone: flat sibling imports (scripts/ on sys.path)
    from errors import ConversionError
    from diagram_model import DiagramModel, Edge, Node
except ImportError:  # package mode (dropped into a package)
    from .errors import ConversionError
    from .diagram_model import DiagramModel, Edge, Node


# Metric keys reported per diagram (and summed by the CLI). ``objects`` is the
# total walked; the rest break it down so a reviewer can spot low-coverage files.
METRIC_FIELDS = ("objects", "shapes", "lines", "texts", "images", "svgs", "unsupported")

_DEFAULT_STROKE = "#000000"
_DEFAULT_FONT_PX = 14.0


def _fmt(value: float) -> str:
    """Compact number formatting for SVG attributes (drops trailing zeros)."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _attr(value: str) -> str:
    """Escape a string for use inside a double-quoted XML attribute."""
    return html.escape(str(value), quote=True)


def _text(value: str) -> str:
    """Escape a string for use as XML text content."""
    return html.escape(str(value), quote=False)


class _BBox:
    """Mutable bounding box accumulated while walking objects."""

    def __init__(self) -> None:
        self.minx = self.miny = float("inf")
        self.maxx = self.maxy = float("-inf")

    def add(self, x: float, y: float) -> None:
        self.minx = min(self.minx, x)
        self.miny = min(self.miny, y)
        self.maxx = max(self.maxx, x)
        self.maxy = max(self.maxy, y)

    def empty(self) -> bool:
        return self.minx == float("inf")


def render_gliffy(
    data: str | dict[str, Any], *, padding: float = 10.0
) -> tuple[str, dict[str, int]]:
    """Render a Gliffy diagram (``.gliffy`` JSON) to a standalone SVG string.

    *data* is the raw JSON text or an already-parsed ``dict``. Returns
    ``(svg_text, metrics)`` where ``metrics`` keys are :data:`METRIC_FIELDS`.

    Coverage is best-effort (see the module docstring): unrecognised stencils
    become dashed placeholder boxes and bump the ``unsupported`` count. The SVG is
    well-formed (XML-escaped, single root) and editable in any vector tool.

    Raises:
        ConversionError: if the JSON is unparseable or has no ``stage.objects``.
    """
    doc, stage = _load_stage(data)
    resources = _index_resources(doc)
    metrics = dict.fromkeys(METRIC_FIELDS, 0)
    bbox = _BBox()
    body: list[str] = []
    needs_arrow = _walk(stage["objects"], 0.0, 0.0, body, bbox, metrics, resources)

    return _assemble(body, bbox, stage, padding, needs_arrow), metrics


def _load_stage(data: str | dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse/validate Gliffy input → ``(doc, stage)``; shared by render + parse paths.

    Raises:
        ConversionError: if the JSON is unparseable or has no ``stage.objects``.
    """
    if isinstance(data, str):
        try:
            doc = json.loads(data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConversionError(f"invalid Gliffy JSON: {exc}") from exc
    else:
        doc = data

    stage = doc.get("stage") if isinstance(doc, dict) else None
    if not isinstance(stage, dict) or not isinstance(stage.get("objects"), list):
        raise ConversionError("not a Gliffy diagram: missing stage.objects")
    return doc, stage


def parse_gliffy(data: str | dict[str, Any]) -> DiagramModel:
    """Parse a Gliffy diagram into the engine-neutral :class:`DiagramModel`.

    This is the structural counterpart to :func:`render_gliffy`: it walks the same
    ``stage.objects`` (same ``order`` sort, same parent-origin offsetting) but emits
    normalized :class:`Node`/:class:`Edge` records instead of SVG strings. An element
    is created exactly when :func:`render_gliffy` would emit a fragment (empty text /
    <2-point lines / url-less images / unresolved svg produce nothing), so the model
    mirrors what is visually rendered. Unknown stencils become ``kind="placeholder"``.

    The model feeds the draw.io emitter and the fidelity harness; it does **not**
    drive the SVG renderer (that path is unchanged).

    Raises:
        ConversionError: if the JSON is unparseable or has no ``stage.objects``.
    """
    doc, stage = _load_stage(data)
    resources = _index_resources(doc)
    background = stage.get("background")
    model = DiagramModel(
        width=_number(stage.get("width"), 0.0),
        height=_number(stage.get("height"), 0.0),
        background=background.strip() if isinstance(background, str) else "",
    )
    _walk_model(stage["objects"], 0.0, 0.0, None, model, resources, [0])
    return model


def _index_resources(doc: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Map ``embeddedResources.resources[].id`` → resource dict (Svg/Image data)."""
    container = doc.get("embeddedResources")
    resources: dict[int, dict[str, Any]] = {}
    if isinstance(container, dict) and isinstance(container.get("resources"), list):
        for res in container["resources"]:
            if isinstance(res, dict) and "id" in res:
                resources[int(res["id"])] = res
    return resources


def _walk(
    objects: list[Any],
    ox: float,
    oy: float,
    body: list[str],
    bbox: _BBox,
    metrics: dict[str, int],
    resources: dict[int, dict[str, Any]],
) -> bool:
    """Append SVG fragments for *objects*, offset by (*ox*, *oy*) (parent origin).

    Gliffy child coordinates and line control paths are relative to the parent
    object's origin, so the accumulated offset is threaded through recursion.
    Returns True if any arrowhead marker is needed (so ``<defs>`` is emitted).
    """
    needs_arrow = False
    for obj in sorted(_valid(objects), key=lambda o: _number(o.get("order"), 0)):
        ax, ay, w, h, rotate = _object_geometry(obj, ox, oy)
        graphic = _as_dict(obj.get("graphic"))
        gtype = str(graphic.get("type", ""))

        metrics["objects"] += 1
        fragment = ""

        if gtype == "Shape":
            fragment = _render_shape(_as_dict(graphic.get("Shape")), obj, ax, ay, w, h, metrics)
            bbox.add(ax, ay)
            bbox.add(ax + w, ay + h)
        elif gtype == "Line":
            fragment, used_arrow = _render_line(_as_dict(graphic.get("Line")), ax, ay, bbox)
            needs_arrow = needs_arrow or used_arrow
            metrics["lines"] += 1
            rotate = 0.0  # control path already carries the geometry
        elif gtype == "Text":
            fragment = _render_text(_as_dict(graphic.get("Text")), ax, ay, w, h)
            metrics["texts"] += 1
            bbox.add(ax, ay)
            bbox.add(ax + w, ay + h)
        elif gtype == "Image":
            fragment = _render_image(_as_dict(graphic.get("Image")), ax, ay, w, h)
            metrics["images"] += 1
            bbox.add(ax, ay)
            bbox.add(ax + w, ay + h)
        elif gtype == "Svg":
            fragment = _render_svg(_as_dict(graphic.get("Svg")), ax, ay, resources)
            metrics["svgs"] += 1
            bbox.add(ax, ay)
            bbox.add(ax + w, ay + h)
        elif w > 0 and h > 0:
            # Unknown graphic with geometry — preserve its footprint as a marker.
            fragment = _placeholder(ax, ay, w, h)
            metrics["unsupported"] += 1
            bbox.add(ax, ay)
            bbox.add(ax + w, ay + h)

        if fragment:
            if rotate:
                cx, cy = ax + w / 2, ay + h / 2
                body.append(f'<g transform="rotate({_fmt(rotate)} {_fmt(cx)} {_fmt(cy)})">')
                body.append(fragment)
                body.append("</g>")
            else:
                body.append(fragment)

        children = obj.get("children")
        if isinstance(children, list) and children:
            # Children are positioned relative to this object's origin.
            if _walk(children, ax, ay, body, bbox, metrics, resources):
                needs_arrow = True

    return needs_arrow


def _valid(objects: list[Any]) -> list[dict[str, Any]]:
    return [o for o in objects if isinstance(o, dict)]


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce a possibly-missing JSON value to a dict (so ``.get`` is always safe)."""
    return value if isinstance(value, dict) else {}


def _object_geometry(
    obj: dict[str, Any], ox: float, oy: float
) -> tuple[float, float, float, float, float]:
    """Absolute origin + size + rotation for *obj* offset by parent origin (*ox*, *oy*).

    Shared by the SVG walk (:func:`_walk`) and the model walk (:func:`_walk_model`)
    so both read geometry identically.
    """
    ax = ox + _number(obj.get("x"), 0.0)
    ay = oy + _number(obj.get("y"), 0.0)
    w = _number(obj.get("width"), 0.0)
    h = _number(obj.get("height"), 0.0)
    rotate = _number(obj.get("rotation"), 0.0)
    return ax, ay, w, h, rotate


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _shape_kind(shape: dict[str, Any], obj: dict[str, Any]) -> str:
    """Classify a Shape by its ``tid``/``uid`` (substring match, order matters)."""
    token = f"{shape.get('tid', '')} {obj.get('uid', '')}".lower()
    if "round_rectangle" in token or "rounded_rectangle" in token:
        return "round_rectangle"
    if "rectangle" in token:
        return "rectangle"
    if "ellipse" in token or "circle" in token:
        return "ellipse"
    if "diamond" in token or "decision" in token:
        return "diamond"
    return "unknown"


def _style(shape: dict[str, Any]) -> str:
    """Build the fill/stroke/dash/opacity attribute string for a shape."""
    fill = str(shape.get("fillColor") or "none")
    if fill in ("transparent", ""):
        fill = "none"
    stroke = str(shape.get("strokeColor") or _DEFAULT_STROKE)
    stroke_width = _number(shape.get("strokeWidth"), 1.0)
    parts = [
        f'fill="{_attr(fill)}"',
        f'stroke="{_attr(stroke)}"',
        f'stroke-width="{_fmt(stroke_width)}"',
    ]
    dash = shape.get("dashStyle")
    if isinstance(dash, str) and dash.strip():
        parts.append(f'stroke-dasharray="{_attr(dash.strip())}"')
    opacity = shape.get("opacity")
    if isinstance(opacity, (int, float)) and 0 <= float(opacity) < 1:
        parts.append(f'opacity="{_fmt(opacity)}"')
    return " ".join(parts)


def _render_shape(
    shape: dict[str, Any],
    obj: dict[str, Any],
    x: float,
    y: float,
    w: float,
    h: float,
    metrics: dict[str, int],
) -> str:
    kind = _shape_kind(shape, obj)
    style = _style(shape)
    if kind == "rectangle":
        metrics["shapes"] += 1
        return f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}" {style}/>'
    if kind == "round_rectangle":
        metrics["shapes"] += 1
        r = _fmt(min(w, h) * 0.15)
        return (
            f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}" '
            f'rx="{r}" ry="{r}" {style}/>'
        )
    if kind == "ellipse":
        metrics["shapes"] += 1
        return (
            f'<ellipse cx="{_fmt(x + w / 2)}" cy="{_fmt(y + h / 2)}" '
            f'rx="{_fmt(w / 2)}" ry="{_fmt(h / 2)}" {style}/>'
        )
    if kind == "diamond":
        metrics["shapes"] += 1
        cx, cy = x + w / 2, y + h / 2
        pts = f"{_fmt(cx)},{_fmt(y)} {_fmt(x + w)},{_fmt(cy)} {_fmt(cx)},{_fmt(y + h)} {_fmt(x)},{_fmt(cy)}"
        return f'<polygon points="{pts}" {style}/>'
    metrics["unsupported"] += 1
    return _placeholder(x, y, w, h)


def _render_line(line: dict[str, Any], x: float, y: float, bbox: _BBox) -> tuple[str, bool]:
    path = line.get("controlPath")
    pts: list[tuple[float, float]] = []
    if isinstance(path, list):
        for p in path:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                px, py = x + _number(p[0], 0.0), y + _number(p[1], 0.0)
                pts.append((px, py))
                bbox.add(px, py)
    if len(pts) < 2:
        return "", False
    stroke = str(line.get("strokeColor") or _DEFAULT_STROKE)
    stroke_width = _number(line.get("strokeWidth"), 1.0)
    coords = " ".join(f"{_fmt(px)},{_fmt(py)}" for px, py in pts)
    attrs = [
        f'points="{coords}"',
        'fill="none"',
        f'stroke="{_attr(stroke)}"',
        f'stroke-width="{_fmt(stroke_width)}"',
        'stroke-linecap="round"',
        'stroke-linejoin="round"',
    ]
    dash = line.get("dashStyle")
    if isinstance(dash, str) and dash.strip():
        attrs.append(f'stroke-dasharray="{_attr(dash.strip())}"')
    used_arrow = False
    if _number(line.get("startArrow"), 0) > 0:
        attrs.append('marker-start="url(#arrow-start)"')
        used_arrow = True
    if _number(line.get("endArrow"), 0) > 0:
        attrs.append('marker-end="url(#arrow-end)"')
        used_arrow = True
    return f"<polyline {' '.join(attrs)}/>", used_arrow


def _render_text(text: dict[str, Any], x: float, y: float, w: float, h: float) -> str:
    raw = str(text.get("html") or "")
    lines = _html_to_lines(raw)
    if not lines:
        return ""
    font_px = _number(_search(r"font-size:\s*(\d+(?:\.\d+)?)px", raw), _DEFAULT_FONT_PX)
    color = _search(r"color:\s*(#[0-9a-fA-F]{3,8})", raw) or _DEFAULT_STROKE
    line_h = font_px * 1.2
    cx = x + w / 2
    valign = str(text.get("valign") or "middle")
    block = line_h * len(lines)
    if valign == "top":
        first = y + font_px
    elif valign == "bottom":
        first = y + h - block + font_px
    else:  # middle
        first = y + h / 2 - block / 2 + font_px
    spans: list[str] = []
    for i, ln in enumerate(lines):
        if i == 0:
            spans.append(f'<tspan x="{_fmt(cx)}" y="{_fmt(first)}">{_text(ln)}</tspan>')
        else:
            spans.append(f'<tspan x="{_fmt(cx)}" dy="{_fmt(line_h)}">{_text(ln)}</tspan>')
    return (
        f'<text text-anchor="middle" font-family="sans-serif" '
        f'font-size="{_fmt(font_px)}" fill="{_attr(color)}">{"".join(spans)}</text>'
    )


def _render_image(image: dict[str, Any], x: float, y: float, w: float, h: float) -> str:
    url = str(image.get("url") or "").strip()
    if not url:
        return ""
    return (
        f'<image x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}" '
        f'href="{_attr(url)}" preserveAspectRatio="xMidYMid meet"/>'
    )


def _render_svg(
    svg: dict[str, Any], x: float, y: float, resources: dict[int, dict[str, Any]]
) -> str:
    inner = svg.get("svg")
    if not inner:
        rid = svg.get("embeddedResourceId")
        if rid is not None and int(rid) in resources:
            inner = resources[int(rid)].get("data")
    if not isinstance(inner, str) or "<svg" not in inner:
        return ""
    # Inline the embedded <svg> (it carries its own sizing/viewBox) and position
    # it with a group translate. Nested <svg> elements are valid SVG.
    return f'<g transform="translate({_fmt(x)} {_fmt(y)})">{inner}</g>'


def _placeholder(x: float, y: float, w: float, h: float) -> str:
    """A faint dashed box marking an unrenderable stencil (footprint preserved)."""
    return (
        f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}" '
        f'fill="none" stroke="#cccccc" stroke-width="1" stroke-dasharray="4,4"/>'
    )


def _html_to_lines(value: str) -> list[str]:
    """Flatten a Gliffy rich-text HTML blob to plain, non-empty text lines."""
    s = re.sub(r"(?i)<br\s*/?>", "\n", value)
    s = re.sub(r"(?i)</(p|div|li)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = html.unescape(s)
    return [ln.strip() for ln in s.split("\n") if ln.strip()]


def _search(pattern: str, value: str) -> str:
    m = re.search(pattern, value)
    return m.group(1) if m else ""


# ── Semantic-model walk (structural counterpart of the SVG walk above) ──────────


def _shape_style(shape: dict[str, Any]) -> tuple[str, str, float, str, float]:
    """Extract ``(fill, stroke, stroke_width, dash, opacity)`` — mirrors :func:`_style`.

    ``transparent``/empty fill → ``"none"``; missing stroke → black; opacity is kept
    only when in ``[0, 1)`` (matching the SVG path), else ``1.0``.
    """
    fill = str(shape.get("fillColor") or "none")
    if fill in ("transparent", ""):
        fill = "none"
    stroke = str(shape.get("strokeColor") or _DEFAULT_STROKE)
    stroke_width = _number(shape.get("strokeWidth"), 1.0)
    dash_raw = shape.get("dashStyle")
    dash = dash_raw.strip() if isinstance(dash_raw, str) else ""
    op = shape.get("opacity")
    opacity = float(op) if isinstance(op, (int, float)) and 0 <= float(op) < 1 else 1.0
    return fill, stroke, stroke_width, dash, opacity


def _line_points(line: dict[str, Any], x: float, y: float) -> list[tuple[float, float]]:
    """Absolute control-path points for a Line (offset by object origin)."""
    path = line.get("controlPath")
    pts: list[tuple[float, float]] = []
    if isinstance(path, list):
        for p in path:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pts.append((x + _number(p[0], 0.0), y + _number(p[1], 0.0)))
    return pts


def _resolve_svg_inner(svg: dict[str, Any], resources: dict[int, dict[str, Any]]) -> str:
    """Resolve an embedded-svg graphic to its inner ``<svg>`` string (or ``""``)."""
    inner = svg.get("svg")
    if not inner:
        rid = svg.get("embeddedResourceId")
        if rid is not None and int(rid) in resources:
            inner = resources[int(rid)].get("data")
    return inner if isinstance(inner, str) and "<svg" in inner else ""


def _walk_model(
    objects: list[Any],
    ox: float,
    oy: float,
    parent_id: str | None,
    model: DiagramModel,
    resources: dict[int, dict[str, Any]],
    counter: list[int],
) -> None:
    """Append :class:`Node`/:class:`Edge` records for *objects* (parent origin *ox*,*oy*).

    Creates an element only when the SVG walk would emit a fragment, so the model
    stays in lock-step with what is rendered. ``counter`` is a single-element mutable
    list giving stable, zero-padded, sortable ids (``n0000``/``e0001``).
    """

    def next_id(prefix: str) -> str:
        nid = f"{prefix}{counter[0]:04d}"
        counter[0] += 1
        return nid

    for obj in sorted(_valid(objects), key=lambda o: _number(o.get("order"), 0)):
        ax, ay, w, h, rotate = _object_geometry(obj, ox, oy)
        graphic = _as_dict(obj.get("graphic"))
        gtype = str(graphic.get("type", ""))
        this_id: str | None = None

        if gtype == "Shape":
            shape = _as_dict(graphic.get("Shape"))
            kind = _shape_kind(shape, obj)
            this_id = next_id("n")
            if kind == "unknown":
                model.nodes.append(_placeholder_node(this_id, ax, ay, w, h, rotate, parent_id))
            else:
                fill, stroke, sw, dash, opacity = _shape_style(shape)
                model.nodes.append(
                    Node(
                        id=this_id,
                        kind=kind,
                        x=ax,
                        y=ay,
                        w=w,
                        h=h,
                        rotation=rotate,
                        fill=fill,
                        stroke=stroke,
                        stroke_width=sw,
                        dash=dash,
                        opacity=opacity,
                        parent_id=parent_id,
                    )
                )
        elif gtype == "Line":
            line = _as_dict(graphic.get("Line"))
            pts = _line_points(line, ax, ay)
            if len(pts) >= 2:
                this_id = next_id("e")
                dash_raw = line.get("dashStyle")
                model.edges.append(
                    Edge(
                        id=this_id,
                        points=pts,
                        stroke=str(line.get("strokeColor") or _DEFAULT_STROKE),
                        stroke_width=_number(line.get("strokeWidth"), 1.0),
                        dash=dash_raw.strip() if isinstance(dash_raw, str) else "",
                        start_arrow=_number(line.get("startArrow"), 0) > 0,
                        end_arrow=_number(line.get("endArrow"), 0) > 0,
                    )
                )
        elif gtype == "Text":
            t = _as_dict(graphic.get("Text"))
            raw = str(t.get("html") or "")
            lines = _html_to_lines(raw)
            if lines:
                this_id = next_id("n")
                model.nodes.append(
                    Node(
                        id=this_id,
                        kind="text",
                        x=ax,
                        y=ay,
                        w=w,
                        h=h,
                        rotation=rotate,
                        text=" ".join(lines),
                        font_px=_number(
                            _search(r"font-size:\s*(\d+(?:\.\d+)?)px", raw), _DEFAULT_FONT_PX
                        ),
                        text_color=_search(r"color:\s*(#[0-9a-fA-F]{3,8})", raw) or _DEFAULT_STROKE,
                        valign=str(t.get("valign") or "middle"),
                        parent_id=parent_id,
                    )
                )
        elif gtype == "Image":
            url = str(_as_dict(graphic.get("Image")).get("url") or "").strip()
            if url:
                this_id = next_id("n")
                model.nodes.append(
                    Node(
                        id=this_id,
                        kind="image",
                        x=ax,
                        y=ay,
                        w=w,
                        h=h,
                        rotation=rotate,
                        image_url=url,
                        parent_id=parent_id,
                    )
                )
        elif gtype == "Svg":
            inner = _resolve_svg_inner(_as_dict(graphic.get("Svg")), resources)
            if inner:
                this_id = next_id("n")
                model.nodes.append(
                    Node(
                        id=this_id,
                        kind="svg",
                        x=ax,
                        y=ay,
                        w=w,
                        h=h,
                        rotation=rotate,
                        svg_inner=inner,
                        parent_id=parent_id,
                    )
                )
        elif w > 0 and h > 0:
            this_id = next_id("n")
            model.nodes.append(_placeholder_node(this_id, ax, ay, w, h, rotate, parent_id))

        children = obj.get("children")
        if isinstance(children, list) and children:
            _walk_model(children, ax, ay, this_id or parent_id, model, resources, counter)


def _placeholder_node(
    node_id: str, x: float, y: float, w: float, h: float, rotation: float, parent_id: str | None
) -> Node:
    """A dashed placeholder Node — fixed style mirroring the SVG :func:`_placeholder`."""
    return Node(
        id=node_id,
        kind="placeholder",
        x=x,
        y=y,
        w=w,
        h=h,
        rotation=rotation,
        fill="none",
        stroke="#cccccc",
        stroke_width=1.0,
        dash="4,4",
        parent_id=parent_id,
    )


_ARROW_DEFS = (
    "<defs>"
    '<marker id="arrow-end" markerWidth="10" markerHeight="10" refX="8" refY="3" '
    'orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,3 L0,6 z" fill="context-stroke"/>'
    "</marker>"
    '<marker id="arrow-start" markerWidth="10" markerHeight="10" refX="0" refY="3" '
    'orient="auto" markerUnits="strokeWidth"><path d="M8,0 L0,3 L8,6 z" fill="context-stroke"/>'
    "</marker>"
    "</defs>"
)


def _assemble(
    body: list[str],
    bbox: _BBox,
    stage: dict[str, Any],
    padding: float,
    needs_arrow: bool,
) -> str:
    if bbox.empty():
        minx = miny = 0.0
        width = max(_number(stage.get("width"), 100.0), 1.0)
        height = max(_number(stage.get("height"), 100.0), 1.0)
    else:
        minx = bbox.minx - padding
        miny = bbox.miny - padding
        width = (bbox.maxx - bbox.minx) + 2 * padding
        height = (bbox.maxy - bbox.miny) + 2 * padding
    width = max(width, 1.0)
    height = max(height, 1.0)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_fmt(minx)} {_fmt(miny)} {_fmt(width)} {_fmt(height)}" '
        f'width="{_fmt(width)}" height="{_fmt(height)}">'
    ]
    if needs_arrow:
        parts.append(_ARROW_DEFS)
    background = stage.get("background")
    if isinstance(background, str) and re.fullmatch(r"#[0-9a-fA-F]{3,8}", background.strip()):
        parts.append(
            f'<rect x="{_fmt(minx)}" y="{_fmt(miny)}" width="{_fmt(width)}" '
            f'height="{_fmt(height)}" fill="{_attr(background.strip())}"/>'
        )
    parts.extend(body)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def resolve_gliffy_file(
    src: Path,
    output: Path | None = None,
    *,
    prefer_existing_svg: bool = True,
    write: bool = True,
) -> tuple[Path, str, str, dict[str, int]]:
    """Resolve one ``.gliffy`` file to an editable SVG.

    Tries the high-fidelity route first: if *prefer_existing_svg* and a sibling
    ``<stem>.svg`` exists, copy it (``method="existing_svg"``); otherwise render
    the JSON (``method="rendered"``). When *write*, the SVG is written to *output*
    (default ``<src>.svg``).

    Returns ``(out_path, svg_text, method, metrics)``. ``metrics`` keys are
    :data:`METRIC_FIELDS` (all zero for the ``existing_svg`` route — no objects
    were walked).

    Raises:
        ConversionError: if *src* is missing, or rendering fails.
    """
    src = Path(src)
    if not src.exists():
        raise ConversionError(f"input file not found: {src}")

    out_path = Path(output) if output is not None else src.with_suffix(".svg")
    metrics = dict.fromkeys(METRIC_FIELDS, 0)

    sibling = src.with_suffix(".svg")
    if prefer_existing_svg and sibling.exists() and sibling.resolve() != out_path.resolve():
        svg_text = sibling.read_text(encoding="utf-8-sig")
        method = "existing_svg"
    else:
        try:
            raw = src.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ConversionError(f"cannot read {src}: {exc}") from exc
        svg_text, metrics = render_gliffy(raw)
        method = "rendered"

    if write:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(svg_text, encoding="utf-8")

    return out_path, svg_text, method, metrics
