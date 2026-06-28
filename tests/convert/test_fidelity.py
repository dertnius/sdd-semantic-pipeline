"""Tests for the fidelity oracles: compare_models + the round-trip check."""

from __future__ import annotations

import pytest

from sdd_pipeline.convert import compare_models, roundtrip_check
from sdd_pipeline.convert.diagram_model import DiagramModel, Edge, Node


def _scene(objects: list[dict], **stage) -> dict:
    return {"stage": {"objects": objects, **stage}}


def _shape(tid: str, **kw) -> dict:
    return {
        "x": kw.get("x", 0),
        "y": kw.get("y", 0),
        "width": kw.get("w", 100),
        "height": kw.get("h", 50),
        "order": kw.get("order", 0),
        "graphic": {"type": "Shape", "Shape": {"tid": tid, **kw.get("style", {})}},
    }


# ── compare_models ──────────────────────────────────────────────────────────────


def test_identical_models_compare_equal():
    a = DiagramModel(nodes=[Node(id="n0", kind="rectangle", x=1, y=2, w=3, h=4)])
    b = DiagramModel(nodes=[Node(id="n0", kind="rectangle", x=1, y=2, w=3, h=4)])
    res = compare_models(a, b)
    assert res["equal"] and res["diffs"] == []


def test_field_change_is_reported():
    a = DiagramModel(nodes=[Node(id="n0", kind="rectangle", fill="#fff")])
    b = DiagramModel(nodes=[Node(id="n0", kind="rectangle", fill="#000")])
    res = compare_models(a, b)
    assert not res["equal"]
    diff = res["diffs"][0]
    assert (
        diff["id"] == "n0"
        and diff["field"] == "fill"
        and diff["a"] == "#fff"
        and diff["b"] == "#000"
    )


def test_numeric_tolerance_absorbs_subpixel_drift():
    a = DiagramModel(nodes=[Node(id="n0", kind="rectangle", x=10.0)])
    b = DiagramModel(nodes=[Node(id="n0", kind="rectangle", x=10.2)])
    assert compare_models(a, b, tol=0.5)["equal"]
    assert not compare_models(a, b, tol=0.05)["equal"]


def test_missing_and_extra_ids_reported():
    a = DiagramModel(nodes=[Node(id="n0", kind="rectangle")])
    b = DiagramModel(nodes=[Node(id="n1", kind="rectangle")])
    fields = {d["field"] for d in compare_models(a, b)["diffs"]}
    assert {"<missing>", "<extra>"} <= fields


def test_arrow_direction_mismatch_detected():
    a = DiagramModel(edges=[Edge(id="e0", points=[(0, 0), (1, 1)], end_arrow=True)])
    b = DiagramModel(edges=[Edge(id="e0", points=[(0, 0), (1, 1)], start_arrow=True)])
    res = compare_models(a, b)
    assert not res["equal"]
    assert {d["field"] for d in res["diffs"]} == {"start_arrow", "end_arrow"}


# ── roundtrip_check (the authoritative oracle) ──────────────────────────────────


@pytest.mark.parametrize(
    "tid",
    [
        "com.gliffy.stencil.rectangle.basic_v1",
        "com.gliffy.stencil.round_rectangle.basic_v1",
        "com.gliffy.stencil.ellipse.basic_v1",
        "com.gliffy.shape.flowchart.flowchart_v1.default.decision",
        "com.gliffy.stencil.unknown.network_v1",  # → placeholder
    ],
)
def test_roundtrip_per_shape_kind(tid):
    res = roundtrip_check(
        _scene([_shape(tid, style={"fillColor": "#abc", "strokeColor": "#123", "strokeWidth": 2})])
    )
    assert res["equal"], res["diffs"]


def test_roundtrip_mixed_scene_with_text_line_and_placeholder():
    scene = _scene(
        [
            _shape("rectangle", order=0, style={"fillColor": "#e8f0fe", "strokeColor": "#1a73e8"}),
            _shape("cloud", order=1),  # placeholder
            {
                "x": 0,
                "y": 80,
                "width": 0,
                "height": 0,
                "order": 2,
                "graphic": {
                    "type": "Line",
                    "Line": {
                        "controlPath": [[0, 0], [50, 0], [50, 40]],
                        "endArrow": 1,
                        "strokeColor": "#555",
                    },
                },
            },
            {
                "x": 10,
                "y": 10,
                "width": 80,
                "height": 24,
                "order": 3,
                "graphic": {"type": "Text", "Text": {"html": "<p>Label</p>", "valign": "middle"}},
            },
        ]
    )
    res = roundtrip_check(scene)
    assert res["equal"], res["diffs"]
    assert res["summary"]["nodes_a"] == 3 and res["summary"]["edges_a"] == 1


def test_roundtrip_empty_scene_is_equal():
    assert roundtrip_check(_scene([]))["equal"]
