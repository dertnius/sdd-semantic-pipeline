#!/usr/bin/env python3
"""
drawio.py
=========
Emit a :class:`~sdd_pipeline.convert.diagram_model.DiagramModel` as a draw.io
(``.drawio`` / mxGraph XML) document, and parse one back.

Why an in-repo emitter? draw.io imports ``.gliffy`` natively, but **only in the
online app** — there is no headless/CLI path — so it cannot run in this pipeline
or in CI. This module gives a reproducible, testable ``.gliffy → .drawio`` route
(via :func:`sdd_pipeline.convert.gliffy_to_svg.parse_gliffy` → the shared model →
:func:`model_to_drawio`), with the same best-effort basic-shape coverage as the
SVG renderer (icon stencils collapse to dashed placeholders).

Coordinate system: Gliffy and draw.io are **both** y-down / top-left, so geometry
is copied straight through — no axis flip.

The emitter and parser are exact inverses for everything the model captures, which
is what makes the fidelity round-trip (:func:`sdd_pipeline.convert.fidelity.
roundtrip_check`) a meaningful oracle. The parser also reads genuine draw.io files
on a best-effort basis (classifying common shapes), but the ``placeholder`` kind —
our own concept — round-trips via a private ``sddType=placeholder`` style marker
(draw.io ignores unknown style keys).

Stdlib only (``xml.etree.ElementTree`` + ``base64``); reuses ``ConversionError``
and the shared model. No flow-A or HTML/docx engine deps.

Public API
----------
- :func:`model_to_drawio` — :class:`DiagramModel` → ``(xml, metrics)``.
- :func:`drawio_to_model` — mxGraph XML → :class:`DiagramModel` (inverse).
- :func:`convert_gliffy_to_drawio_file` — one ``.gliffy`` file → ``(out_path, xml,
  metrics)`` (mirrors the other converters' per-file return).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:  # vendored standalone: flat sibling imports (scripts/ on sys.path)
    from errors import ConversionError
    from diagram_model import DiagramModel, Edge, Node
    from gliffy_to_svg import parse_gliffy
except ImportError:  # package mode (dropped into a package)
    from .errors import ConversionError
    from .diagram_model import DiagramModel, Edge, Node
    from .gliffy_to_svg import parse_gliffy

# Metric keys reported per converted file (summed by the CLI).
METRIC_FIELDS = ("nodes", "edges", "placeholders", "svgs", "images")

_GEOMETRIC = ("rectangle", "round_rectangle", "ellipse", "diamond")
_SVG_DATA_PREFIX = "data:image/svg+xml,"


# ── number / string helpers ─────────────────────────────────────────────────────


def _num(value: float) -> str:
    """Compact 2 d.p. number (matches the SVG renderer's ``_fmt``)."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dash_to_pattern(dash: str) -> str:
    """``"8,8"`` → ``"8 8"`` (draw.io dashPattern is space-separated)."""
    return " ".join(dash.replace(",", " ").split())


def _pattern_to_dash(pattern: str) -> str:
    """``"8 8"`` → ``"8,8"`` (model/SVG dash is comma-separated)."""
    return ",".join(pattern.replace(",", " ").split())


def _style_safe(value: str) -> str:
    """Make a value safe inside a ``;``-separated style token (reversible)."""
    return value.replace("%", "%25").replace(";", "%3B")


def _style_unsafe(value: str) -> str:
    return value.replace("%3B", ";").replace("%25", "%")


def _encode_svg(inner: str) -> str:
    b64 = base64.b64encode(inner.encode("utf-8")).decode("ascii")
    return _SVG_DATA_PREFIX + b64


def _decode_svg(value: str) -> str:
    if not value.startswith(_SVG_DATA_PREFIX):
        return ""
    try:
        return base64.b64decode(value[len(_SVG_DATA_PREFIX) :]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


# ── emit: model → draw.io XML ────────────────────────────────────────────────────


def _node_style(node: Node) -> str:
    """Build the mxCell ``style`` string for a node (kind → draw.io shape + props)."""
    kind = node.kind
    if kind == "rectangle":
        toks = ["rounded=0", "whiteSpace=wrap", "html=1"]
    elif kind == "round_rectangle":
        toks = ["rounded=1", "whiteSpace=wrap", "html=1"]
    elif kind == "ellipse":
        toks = ["ellipse", "whiteSpace=wrap", "html=1"]
    elif kind == "diamond":
        toks = ["rhombus", "whiteSpace=wrap", "html=1"]
    elif kind == "text":
        toks = [
            "text",
            "html=1",
            "align=center",
            f"verticalAlign={node.valign}",
            f"fontSize={_num(node.font_px)}",
            f"fontColor={node.text_color}",
        ]
    elif kind == "image":
        toks = ["shape=image", "imageAspect=1", f"image={_style_safe(node.image_url)}"]
    elif kind == "svg":
        toks = ["shape=image", "imageAspect=0", f"image={_encode_svg(node.svg_inner)}"]
    elif kind == "placeholder":
        toks = [
            "sddType=placeholder",
            "rounded=0",
            "dashed=1",
            "html=1",
            "fillColor=none",
            "strokeColor=#cccccc",
            "strokeWidth=1",
            "dashPattern=4 4",
        ]
    else:  # defensive: unknown kind → plain box
        toks = ["rounded=0", "html=1"]

    if kind in _GEOMETRIC:
        toks.append(f"fillColor={node.fill}")
        toks.append(f"strokeColor={node.stroke}")
        toks.append(f"strokeWidth={_num(node.stroke_width)}")
        if node.dash:
            toks.append("dashed=1")
            toks.append(f"dashPattern={_dash_to_pattern(node.dash)}")
        if node.opacity < 1:
            toks.append(f"opacity={round(node.opacity * 100)}")
    if node.rotation:
        toks.append(f"rotation={_num(node.rotation)}")
    return ";".join(toks) + ";"


def _edge_style(edge: Edge) -> str:
    toks = [
        f"endArrow={'classic' if edge.end_arrow else 'none'}",
        f"startArrow={'classic' if edge.start_arrow else 'none'}",
        "html=1",
        "rounded=0",
        f"strokeColor={edge.stroke}",
        f"strokeWidth={_num(edge.stroke_width)}",
    ]
    if edge.dash:
        toks.append("dashed=1")
        toks.append(f"dashPattern={_dash_to_pattern(edge.dash)}")
    return ";".join(toks) + ";"


def model_to_drawio(model: DiagramModel) -> tuple[str, dict[str, int]]:
    """Serialize *model* to a draw.io ``mxfile`` XML string + per-diagram metrics.

    Cells are emitted flat (every vertex/edge ``parent="1"``) with absolute
    geometry — nesting is not reconstructed as container cells in v1 (the
    ``parent_id`` is provenance only). Returns ``(xml, metrics)`` with
    :data:`METRIC_FIELDS` keys.
    """
    # Attributes are passed as explicit attrib dicts (3rd positional arg) rather
    # than kwargs: keys like ``parent``/``id`` would otherwise collide with
    # ``ET.SubElement``'s own ``parent`` parameter under the pure-Python tree.
    mxfile = ET.Element("mxfile", {"host": "sdd-pipeline"})
    diagram = ET.SubElement(mxfile, "diagram", {"name": "Page-1"})
    gm = ET.SubElement(diagram, "mxGraphModel", {"grid": "1", "gridSize": "10"})
    root = ET.SubElement(gm, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    for node in model.nodes:
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": node.id,
                "value": node.text,
                "style": _node_style(node),
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": _num(node.x),
                "y": _num(node.y),
                "width": _num(node.w),
                "height": _num(node.h),
                "as": "geometry",
            },
        )

    for edge in model.edges:
        cell = ET.SubElement(
            root,
            "mxCell",
            {"id": edge.id, "value": "", "style": _edge_style(edge), "edge": "1", "parent": "1"},
        )
        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        if edge.points:
            ET.SubElement(
                geo,
                "mxPoint",
                {"x": _num(edge.points[0][0]), "y": _num(edge.points[0][1]), "as": "sourcePoint"},
            )
            ET.SubElement(
                geo,
                "mxPoint",
                {"x": _num(edge.points[-1][0]), "y": _num(edge.points[-1][1]), "as": "targetPoint"},
            )
            mids = edge.points[1:-1]
            if mids:
                arr = ET.SubElement(geo, "Array", {"as": "points"})
                for px, py in mids:
                    ET.SubElement(arr, "mxPoint", {"x": _num(px), "y": _num(py)})

    metrics = {
        "nodes": len(model.nodes),
        "edges": len(model.edges),
        "placeholders": sum(1 for n in model.nodes if n.kind == "placeholder"),
        "svgs": sum(1 for n in model.nodes if n.kind == "svg"),
        "images": sum(1 for n in model.nodes if n.kind == "image"),
    }
    return ET.tostring(mxfile, encoding="unicode"), metrics


# ── parse: draw.io XML → model (inverse) ─────────────────────────────────────────


def _parse_style(style: str) -> tuple[set[str], dict[str, str]]:
    """Split a draw.io style string into (bare tokens, key=value map)."""
    bare: set[str] = set()
    kv: dict[str, str] = {}
    for tok in style.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        if "=" in tok:
            key, _, val = tok.partition("=")
            kv[key] = val
        else:
            bare.add(tok)
    return bare, kv


def _classify(bare: set[str], kv: dict[str, str]) -> str:
    if kv.get("sddType") == "placeholder":
        return "placeholder"
    if kv.get("shape") == "image":
        return "svg" if kv.get("image", "").startswith(_SVG_DATA_PREFIX) else "image"
    if "text" in bare:
        return "text"
    if "ellipse" in bare:
        return "ellipse"
    if "rhombus" in bare:
        return "diamond"
    if kv.get("rounded") == "1":
        return "round_rectangle"
    return "rectangle"


def _cell_to_node(cid: str, cell: ET.Element, geo: ET.Element | None) -> Node:
    bare, kv = _parse_style(cell.get("style") or "")
    kind = _classify(bare, kv)
    gx = _f(geo.get("x")) if geo is not None else 0.0
    gy = _f(geo.get("y")) if geo is not None else 0.0
    gw = _f(geo.get("width")) if geo is not None else 0.0
    gh = _f(geo.get("height")) if geo is not None else 0.0
    node = Node(
        id=cid,
        kind=kind,
        x=gx,
        y=gy,
        w=gw,
        h=gh,
        rotation=_f(kv.get("rotation"), 0.0),
        text=cell.get("value", "") or "",
    )
    if kind == "text":
        node.font_px = _f(kv.get("fontSize"), 14.0)
        node.text_color = kv.get("fontColor", "#000000")
        node.valign = kv.get("verticalAlign", "middle")
    elif kind == "image":
        node.image_url = _style_unsafe(kv.get("image", ""))
    elif kind == "svg":
        node.svg_inner = _decode_svg(kv.get("image", ""))
    elif kind == "placeholder":
        node.fill = "none"
        node.stroke = "#cccccc"
        node.stroke_width = _f(kv.get("strokeWidth"), 1.0)
        node.dash = "4,4"
    else:  # geometric
        node.fill = kv.get("fillColor", "none")
        node.stroke = kv.get("strokeColor", "#000000")
        node.stroke_width = _f(kv.get("strokeWidth"), 1.0)
        if kv.get("dashed") == "1":
            node.dash = _pattern_to_dash(kv.get("dashPattern", "3,3"))
        if "opacity" in kv:
            node.opacity = _f(kv.get("opacity"), 100.0) / 100.0
    return node


def _cell_to_edge(cid: str, cell: ET.Element, geo: ET.Element | None) -> Edge:
    _bare, kv = _parse_style(cell.get("style") or "")
    src: tuple[float, float] | None = None
    tgt: tuple[float, float] | None = None
    mids: list[tuple[float, float]] = []
    if geo is not None:
        for pt in geo.findall("mxPoint"):
            role = pt.get("as")
            xy = (_f(pt.get("x")), _f(pt.get("y")))
            if role == "sourcePoint":
                src = xy
            elif role == "targetPoint":
                tgt = xy
        arr = geo.find("Array")
        if arr is not None:
            mids = [(_f(pt.get("x")), _f(pt.get("y"))) for pt in arr.findall("mxPoint")]
    points: list[tuple[float, float]] = []
    if src is not None:
        points.append(src)
    points.extend(mids)
    if tgt is not None:
        points.append(tgt)
    return Edge(
        id=cid,
        points=points,
        stroke=kv.get("strokeColor", "#000000"),
        stroke_width=_f(kv.get("strokeWidth"), 1.0),
        dash=_pattern_to_dash(kv.get("dashPattern", "3,3")) if kv.get("dashed") == "1" else "",
        start_arrow=kv.get("startArrow", "none") not in ("none", ""),
        end_arrow=kv.get("endArrow", "none") not in ("none", ""),
    )


def drawio_to_model(xml: str) -> DiagramModel:
    """Parse a draw.io ``mxGraphModel``/``mxfile`` XML string into a :class:`DiagramModel`.

    Raises:
        ConversionError: if the XML is malformed or has no ``<mxGraphModel>``.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ConversionError(f"invalid draw.io XML: {exc}") from exc
    gm = root if root.tag == "mxGraphModel" else root.find(".//mxGraphModel")
    if gm is None:
        raise ConversionError("not a draw.io model: no <mxGraphModel>")

    model = DiagramModel()
    for cell in gm.iter("mxCell"):
        cid = cell.get("id")
        if cid is None or cid in ("0", "1"):
            continue
        geo = cell.find("mxGeometry")
        if cell.get("vertex") == "1":
            model.nodes.append(_cell_to_node(cid, cell, geo))
        elif cell.get("edge") == "1":
            model.edges.append(_cell_to_edge(cid, cell, geo))
    return model


# ── file-level convenience (mirrors the other converters) ────────────────────────


def convert_gliffy_to_drawio_file(
    src: Path,
    output: Path | None = None,
    *,
    write: bool = True,
) -> tuple[Path, str, dict[str, int]]:
    """Convert one ``.gliffy`` file to a ``.drawio`` document.

    Runs ``parse_gliffy`` → :func:`model_to_drawio`; when *write*, the XML is
    written to *output* (default ``<src>.drawio``). Returns ``(out_path, xml,
    metrics)`` with :data:`METRIC_FIELDS` keys.

    Raises:
        ConversionError: if *src* is missing/unreadable or the Gliffy JSON is invalid.
    """
    src = Path(src)
    if not src.exists():
        raise ConversionError(f"input file not found: {src}")
    out_path = Path(output) if output is not None else src.with_suffix(".drawio")
    try:
        raw = src.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConversionError(f"cannot read {src}: {exc}") from exc

    model = parse_gliffy(raw)
    xml, metrics = model_to_drawio(model)

    if write:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(xml, encoding="utf-8")
    return out_path, xml, metrics
