"""Tests for parse_gliffy — the gliffy→model oracle the round-trip can't cover.

These assert the model captured the Gliffy source faithfully (field by field),
reusing the same fixture shapes as the SVG renderer's tests.
"""

from __future__ import annotations

import pytest

from sdd_pipeline.convert import ConversionError, parse_gliffy, render_gliffy


def _obj(gtype: str, sub: dict, **kw) -> dict:
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


def _scene(objects: list[dict], **stage) -> dict:
    return {"stage": {"objects": objects, **stage}}


def _one(objects: list[dict]):
    m = parse_gliffy(_scene(objects))
    return m


# ── shapes ──────────────────────────────────────────────────────────────────────


def test_rectangle_node_fields():
    m = _one(
        [
            _obj(
                "Shape",
                {"tid": "rectangle", "fillColor": "#fff", "strokeColor": "#123", "strokeWidth": 2},
            )
        ]
    )
    n = m.nodes[0]
    assert n.kind == "rectangle"
    assert (n.x, n.y, n.w, n.h) == (0.0, 0.0, 100.0, 50.0)
    assert n.fill == "#fff" and n.stroke == "#123" and n.stroke_width == 2.0


def test_round_rectangle_and_ellipse_and_diamond_kinds():
    m = parse_gliffy(
        _scene(
            [
                _obj("Shape", {"tid": "com.gliffy.stencil.round_rectangle.basic_v1"}, order=0),
                _obj("Shape", {"tid": "com.gliffy.stencil.ellipse.basic_v1"}, order=1),
                _obj("Shape", {"tid": "...flowchart...decision"}, order=2),
            ]
        )
    )
    assert [n.kind for n in m.nodes] == ["round_rectangle", "ellipse", "diamond"]


def test_unknown_stencil_becomes_placeholder_node():
    n = _one(
        [_obj("Shape", {"tid": "com.gliffy.stencil.cloud.network_v1", "fillColor": "#abc"})]
    ).nodes[0]
    assert n.kind == "placeholder"
    assert n.fill == "none" and n.stroke == "#cccccc" and n.dash == "4,4"  # fixed placeholder style


def test_transparent_fill_becomes_none():
    n = _one([_obj("Shape", {"tid": "rectangle", "fillColor": "transparent"})]).nodes[0]
    assert n.fill == "none"


def test_opacity_kept_only_when_below_one():
    half = _one([_obj("Shape", {"tid": "rectangle", "opacity": 0.5})]).nodes[0]
    full = _one([_obj("Shape", {"tid": "rectangle", "opacity": 1})]).nodes[0]
    assert half.opacity == 0.5
    assert full.opacity == 1.0


# ── lines ─────────────────────────────────────────────────────────────────────


def test_line_edge_points_offset_and_arrows():
    e = _one(
        [_obj("Line", {"controlPath": [[0, 0], [10, 0], [10, 20]], "endArrow": 1}, x=200, y=300)]
    ).edges[0]
    assert e.points[0] == (200.0, 300.0)  # offset by object origin
    assert e.points[-1] == (210.0, 320.0)
    assert e.end_arrow is True and e.start_arrow is False


def test_degenerate_line_makes_no_edge():
    m = _one([_obj("Line", {"controlPath": [[0, 0]]})])
    assert m.edges == [] and m.nodes == []


# ── text / image / svg ───────────────────────────────────────────────────────


def test_text_node_fields():
    html = '<p style="text-align:center;"><span style="font-size:18px; color:#202124;">Hello<br>World</span></p>'
    n = _one([_obj("Text", {"html": html, "valign": "top"})]).nodes[0]
    assert n.kind == "text"
    assert n.text == "Hello World"  # lines joined with a space
    assert n.font_px == 18.0
    assert n.text_color == "#202124"
    assert n.valign == "top"


def test_empty_text_makes_no_node():
    assert _one([_obj("Text", {"html": "<p></p>"})]).nodes == []


def test_image_node_and_urlless_image_skipped():
    n = _one([_obj("Image", {"url": "data:image/png;base64,AAAA"})]).nodes[0]
    assert n.kind == "image" and n.image_url == "data:image/png;base64,AAAA"
    assert _one([_obj("Image", {"url": ""})]).nodes == []


def test_embedded_svg_inline_and_by_resource_id():
    blob = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
    inline = _one([_obj("Svg", {"svg": blob})]).nodes[0]
    assert inline.kind == "svg" and inline.svg_inner == blob
    via_res = parse_gliffy(
        {
            "stage": {"objects": [_obj("Svg", {"embeddedResourceId": 7})]},
            "embeddedResources": {"resources": [{"id": 7, "data": blob}]},
        }
    ).nodes[0]
    assert via_res.svg_inner == blob


# ── nesting / order / counts ────────────────────────────────────────────────────


def test_children_offset_and_parent_id():
    child = _obj("Shape", {"tid": "rectangle"}, x=10, y=10, w=20, h=20)
    m = _one([_obj("Shape", {"tid": "rectangle"}, x=50, y=50, children=[child])])
    parent, kid = m.nodes
    assert (kid.x, kid.y) == (60.0, 60.0)  # 50 + 10
    assert kid.parent_id == parent.id


def test_objects_parsed_in_order():
    a = _obj("Shape", {"tid": "rectangle", "fillColor": "#a"}, order=5)
    b = _obj("Shape", {"tid": "rectangle", "fillColor": "#b"}, order=1)
    m = _one([a, b])
    assert [n.fill for n in m.nodes] == ["#b", "#a"]  # order=1 first


def test_element_count_matches_rendered_objects_for_all_valid_scene():
    objs = [
        _obj("Shape", {"tid": "rectangle"}, order=0),
        _obj("Shape", {"tid": "ellipse"}, order=1),
        _obj("Line", {"controlPath": [[0, 0], [10, 0]]}, order=2),
        _obj("Text", {"html": "<p>x</p>"}, order=3),
    ]
    m = parse_gliffy(_scene(objs))
    _svg, metrics = render_gliffy(_scene(objs))
    assert len(m.nodes) + len(m.edges) == metrics["objects"]


def test_empty_diagram_is_empty_model():
    m = parse_gliffy(_scene([]))
    assert m.nodes == [] and m.edges == []


def test_invalid_inputs_raise():
    with pytest.raises(ConversionError):
        parse_gliffy("{not valid")
    with pytest.raises(ConversionError):
        parse_gliffy({"foo": 1})
