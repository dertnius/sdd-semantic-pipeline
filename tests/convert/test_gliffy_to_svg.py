"""Tests for the Gliffy → SVG resolver (flow-B, model-free, deterministic)."""

from __future__ import annotations

import json
from xml.etree import ElementTree as ET

import pytest

from sdd_pipeline.convert import ConversionError, render_gliffy, resolve_gliffy_file

SVG_NS = "{http://www.w3.org/2000/svg}"


def _obj(gtype: str, sub: dict, **kw) -> dict:
    """Build one Gliffy stage object with a single graphic."""
    return {
        "x": kw.get("x", 0),
        "y": kw.get("y", 0),
        "width": kw.get("w", 100),
        "height": kw.get("h", 50),
        "rotation": kw.get("rotation", 0),
        "order": kw.get("order", 0),
        "uid": kw.get("uid", ""),
        "graphic": {"type": gtype, gtype: sub},
        "children": kw.get("children", []),
    }


def _scene(objects: list[dict], **stage) -> str:
    s: dict = {"objects": objects}
    s.update(stage)
    return json.dumps({"stage": s})


def _root(svg: str) -> ET.Element:
    """Parse the SVG — also asserts it is well-formed XML (validatable)."""
    return ET.fromstring(svg)


# ── shapes ────────────────────────────────────────────────────────────────────


def test_rectangle_renders_rect_with_style():
    shape = {
        "tid": "com.gliffy.stencil.rectangle.basic_v1",
        "fillColor": "#ffffff",
        "strokeColor": "#112233",
        "strokeWidth": 2,
    }
    svg, metrics = render_gliffy(_scene([_obj("Shape", shape)]))
    root = _root(svg)
    rects = root.findall(f".//{SVG_NS}rect")
    assert len(rects) == 1
    assert rects[0].get("fill") == "#ffffff"
    assert rects[0].get("stroke") == "#112233"
    assert metrics["shapes"] == 1
    assert metrics["objects"] == 1


def test_round_rectangle_has_corner_radius():
    shape = {"tid": "com.gliffy.stencil.round_rectangle.basic_v1"}
    svg, _ = render_gliffy(_scene([_obj("Shape", shape)]))
    rect = _root(svg).find(f".//{SVG_NS}rect")
    assert rect is not None
    assert rect.get("rx") is not None and float(rect.get("rx")) > 0


def test_ellipse_renders_ellipse():
    shape = {"uid": "...ellipse...", "tid": "com.gliffy.stencil.ellipse.basic_v1"}
    svg, m = render_gliffy(_scene([_obj("Shape", shape, w=80, h=40)]))
    ell = _root(svg).find(f".//{SVG_NS}ellipse")
    assert ell is not None
    assert ell.get("rx") == "40" and ell.get("ry") == "20"
    assert m["shapes"] == 1


def test_diamond_renders_polygon_with_four_points():
    shape = {"tid": "com.gliffy.shape.flowchart.flowchart_v1.default.decision"}
    svg, _ = render_gliffy(_scene([_obj("Shape", shape, w=100, h=60)]))
    poly = _root(svg).find(f".//{SVG_NS}polygon")
    assert poly is not None
    assert len(poly.get("points").split()) == 4


def test_transparent_fill_becomes_none():
    shape = {"tid": "rectangle", "fillColor": "transparent"}
    svg, _ = render_gliffy(_scene([_obj("Shape", shape)]))
    assert _root(svg).find(f".//{SVG_NS}rect").get("fill") == "none"


# ── lines ─────────────────────────────────────────────────────────────────────


def test_line_renders_polyline_with_arrow_markers_and_defs():
    line = {
        "controlPath": [[0, 0], [100, 0], [100, 50]],
        "strokeColor": "#000000",
        "strokeWidth": 2,
        "startArrow": 0,
        "endArrow": 1,
    }
    svg, m = render_gliffy(_scene([_obj("Line", line)]))
    root = _root(svg)
    poly = root.find(f".//{SVG_NS}polyline")
    assert poly is not None
    assert poly.get("marker-end") == "url(#arrow-end)"
    assert poly.get("marker-start") is None
    assert root.find(f".//{SVG_NS}defs") is not None  # defs emitted only when needed
    assert m["lines"] == 1


def test_line_control_path_is_offset_by_object_origin():
    line = {"controlPath": [[0, 0], [10, 0]]}
    svg, _ = render_gliffy(_scene([_obj("Line", line, x=200, y=300)]))
    poly = _root(svg).find(f".//{SVG_NS}polyline")
    assert poly.get("points").split()[0] == "200,300"


def test_no_defs_when_no_arrows():
    line = {"controlPath": [[0, 0], [10, 0]], "endArrow": 0}
    svg, _ = render_gliffy(_scene([_obj("Line", line)]))
    assert _root(svg).find(f".//{SVG_NS}defs") is None


# ── text ──────────────────────────────────────────────────────────────────────


def test_text_extracts_lines_into_tspans():
    text = {"html": '<p style="text-align:center;">Hello<br>World</p>', "valign": "middle"}
    svg, m = render_gliffy(_scene([_obj("Text", text)]))
    tspans = _root(svg).findall(f".//{SVG_NS}tspan")
    assert [t.text for t in tspans] == ["Hello", "World"]
    # second line uses a relative dy, not an absolute y
    assert tspans[1].get("y") is None and tspans[1].get("dy") is not None
    assert m["texts"] == 1


def test_text_html_entities_are_unescaped_and_reescaped_safely():
    text = {"html": "<p>a &amp; b &lt;x&gt;</p>"}
    svg, _ = render_gliffy(_scene([_obj("Text", text)]))
    tspan = _root(svg).find(f".//{SVG_NS}tspan")  # ET un-escapes on parse
    assert tspan.text == "a & b <x>"


# ── unsupported / placeholders ──────────────────────────────────────────────────


def test_unknown_stencil_becomes_dashed_placeholder():
    shape = {"tid": "com.gliffy.stencil.cloud.network_v1"}
    svg, m = render_gliffy(_scene([_obj("Shape", shape)]))
    rect = _root(svg).find(f".//{SVG_NS}rect")
    assert rect is not None
    assert rect.get("stroke-dasharray") == "4,4"
    assert m["unsupported"] == 1
    assert m["shapes"] == 0


# ── children / nesting ──────────────────────────────────────────────────────────


def test_children_are_offset_by_parent_origin():
    child = _obj("Shape", {"tid": "rectangle"}, x=10, y=10, w=20, h=20)
    parent = _obj("Shape", {"tid": "rectangle"}, x=50, y=50, children=[child])
    svg, m = render_gliffy(_scene([parent]))
    xs = sorted(r.get("x") for r in _root(svg).findall(f".//{SVG_NS}rect"))
    assert "60" in xs  # 50 (parent) + 10 (child)
    assert m["objects"] == 2


def test_objects_are_emitted_in_order():
    a = _obj("Shape", {"tid": "rectangle", "fillColor": "#aaaaaa"}, order=5)
    b = _obj("Shape", {"tid": "rectangle", "fillColor": "#bbbbbb"}, order=1)
    svg, _ = render_gliffy(_scene([a, b]))
    fills = [r.get("fill") for r in _root(svg).findall(f".//{SVG_NS}rect")]
    assert fills == ["#bbbbbb", "#aaaaaa"]  # order=1 drawn first


# ── embedded svg / image ────────────────────────────────────────────────────────


def test_embedded_svg_is_inlined():
    svg_blob = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L5 5"/></svg>'
    obj = _obj("Svg", {"svg": svg_blob})
    out, m = render_gliffy(_scene([obj]))
    assert "<path" in out and "translate" in out
    assert m["svgs"] == 1


def test_embedded_svg_via_resource_id():
    blob = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="3"/></svg>'
    obj = _obj("Svg", {"embeddedResourceId": 7})
    scene = {
        "stage": {"objects": [obj]},
        "embeddedResources": {"resources": [{"id": 7, "data": blob}]},
    }
    out, _ = render_gliffy(json.dumps(scene))
    assert "<circle" in out


def test_image_renders_image_with_href():
    obj = _obj("Image", {"url": "data:image/png;base64,AAAA"})
    out, m = render_gliffy(_scene([obj]))
    img = _root(out).find(f".//{SVG_NS}image")
    assert img is not None
    assert img.get("href") == "data:image/png;base64,AAAA"
    assert m["images"] == 1


# ── viewBox / background ────────────────────────────────────────────────────────


def test_viewbox_is_content_bbox_plus_padding():
    shape = {"tid": "rectangle"}
    svg, _ = render_gliffy(_scene([_obj("Shape", shape, x=0, y=0, w=100, h=50)]), padding=10)
    vb = _root(svg).get("viewBox")
    assert vb == "-10 -10 120 70"


def test_background_color_emits_backing_rect():
    shape = {"tid": "rectangle"}
    svg, _ = render_gliffy(_scene([_obj("Shape", shape)], background="#f0f0f0"))
    fills = [r.get("fill") for r in _root(svg).findall(f".//{SVG_NS}rect")]
    assert "#f0f0f0" in fills


def test_empty_diagram_still_valid_svg():
    svg, m = render_gliffy(_scene([], width=200, height=100))
    root = _root(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert m["objects"] == 0


# ── error handling ──────────────────────────────────────────────────────────────


def test_invalid_json_raises():
    with pytest.raises(ConversionError):
        render_gliffy("{not valid")


def test_missing_stage_raises():
    with pytest.raises(ConversionError):
        render_gliffy('{"foo": 1}')


# ── resolve_gliffy_file ─────────────────────────────────────────────────────────


def test_resolve_renders_and_writes(tmp_path):
    src = tmp_path / "diagram.gliffy"
    src.write_text(_scene([_obj("Shape", {"tid": "rectangle"})]), encoding="utf-8")
    out = tmp_path / "out" / "diagram.svg"
    out_path, svg, method, metrics = resolve_gliffy_file(src, out)
    assert out_path == out
    assert out.exists()
    assert method == "rendered"
    assert metrics["shapes"] == 1
    _root(svg)  # well-formed


def test_resolve_prefers_existing_sibling_svg(tmp_path):
    src = tmp_path / "d.gliffy"
    src.write_text(_scene([_obj("Shape", {"tid": "rectangle"})]), encoding="utf-8")
    sentinel = '<svg xmlns="http://www.w3.org/2000/svg"><!-- gliffy native --></svg>'
    (tmp_path / "d.svg").write_text(sentinel, encoding="utf-8")
    out = tmp_path / "out" / "d.svg"
    out_path, svg, method, metrics = resolve_gliffy_file(src, out, prefer_existing_svg=True)
    assert method == "existing_svg"
    assert svg == sentinel
    assert out_path.read_text(encoding="utf-8") == sentinel
    assert metrics["objects"] == 0


def test_resolve_always_render_ignores_sibling(tmp_path):
    src = tmp_path / "d.gliffy"
    src.write_text(_scene([_obj("Shape", {"tid": "rectangle"})]), encoding="utf-8")
    (tmp_path / "d.svg").write_text("<svg/>", encoding="utf-8")
    out = tmp_path / "out" / "d.svg"
    _, _, method, _ = resolve_gliffy_file(src, out, prefer_existing_svg=False)
    assert method == "rendered"


def test_resolve_missing_file_raises(tmp_path):
    with pytest.raises(ConversionError):
        resolve_gliffy_file(tmp_path / "nope.gliffy")
