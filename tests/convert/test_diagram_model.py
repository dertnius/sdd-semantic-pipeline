"""Tests for the engine-neutral DiagramModel + its canonical to_dict()."""

from __future__ import annotations

from sdd_pipeline.convert.diagram_model import DiagramModel, Edge, Node


def test_node_to_dict_rounds_floats_and_lowercases_colors():
    n = Node(
        id="n0000", kind="rectangle", x=1.0, y=2.0, w=3.333, h=4.0, fill="#FFAA00", stroke="#00FF00"
    )
    d = n.to_dict()
    assert d["w"] == 3.33  # rounded to 2 d.p.
    assert d["fill"] == "#ffaa00"
    assert d["stroke"] == "#00ff00"


def test_node_svg_inner_is_hashed_not_inlined():
    a = Node(id="n0", kind="svg", svg_inner="<svg>A</svg>").to_dict()
    b = Node(id="n0", kind="svg", svg_inner="<svg>B</svg>").to_dict()
    assert a["svg_hash"] and a["svg_hash"] != b["svg_hash"]
    assert "svg_inner" not in a  # the raw blob never enters the canonical dict
    assert Node(id="n0", kind="rectangle").to_dict()["svg_hash"] == ""


def test_edge_points_rounded_and_dash_normalized():
    e = Edge(id="e0", points=[(0.0, 0.0), (10.5, 5.25)], dash="8 8", end_arrow=True)
    d = e.to_dict()
    assert d["points"] == [[0.0, 0.0], [10.5, 5.25]]
    assert d["dash"] == "8,8"  # space-form normalized to comma-form
    assert d["start_arrow"] is False
    assert d["end_arrow"] is True


def test_model_to_dict_sorts_by_id_and_omits_canvas():
    m = DiagramModel(
        nodes=[Node(id="n0002", kind="rectangle"), Node(id="n0001", kind="ellipse")],
        edges=[Edge(id="e0001")],
        width=100,
        height=50,
        background="#ffffff",
    )
    d = m.to_dict()
    assert [n["id"] for n in d["nodes"]] == ["n0001", "n0002"]  # sorted by id
    assert set(d.keys()) == {"nodes", "edges"}  # canvas size/background excluded


def test_transparent_and_empty_color_normalize():
    assert Node(id="n0", kind="rectangle", fill="").to_dict()["fill"] == ""
    assert Node(id="n0", kind="rectangle", fill="NONE").to_dict()["fill"] == "none"
