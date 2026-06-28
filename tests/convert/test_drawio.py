"""Tests for the draw.io emitter (model → mxGraph XML) and inverse parser."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from sdd_pipeline.convert import ConversionError, drawio_to_model, model_to_drawio
from sdd_pipeline.convert.diagram_model import DiagramModel, Edge, Node


def _emit(model: DiagramModel) -> tuple[str, ET.Element]:
    xml, _metrics = model_to_drawio(model)
    return xml, ET.fromstring(xml)  # also asserts well-formed XML


def _cells(root: ET.Element) -> list[ET.Element]:
    return [c for c in root.iter("mxCell") if c.get("id") not in ("0", "1")]


def _style_of(model: DiagramModel) -> str:
    _xml, root = _emit(model)
    return _cells(root)[0].get("style") or ""


# ── emit: per-kind style tokens ─────────────────────────────────────────────────


def test_rectangle_and_round_rectangle_style():
    assert "rounded=0;" in _style_of(DiagramModel(nodes=[Node(id="n0", kind="rectangle")]))
    assert "rounded=1;" in _style_of(DiagramModel(nodes=[Node(id="n0", kind="round_rectangle")]))


def test_ellipse_and_diamond_style():
    assert "ellipse;" in _style_of(DiagramModel(nodes=[Node(id="n0", kind="ellipse")]))
    assert "rhombus;" in _style_of(DiagramModel(nodes=[Node(id="n0", kind="diamond")]))


def test_text_style_carries_font_and_valign():
    style = _style_of(
        DiagramModel(
            nodes=[Node(id="n0", kind="text", font_px=18, text_color="#202124", valign="top")]
        )
    )
    assert "text;" in style and "fontSize=18;" in style
    assert "fontColor=#202124;" in style and "verticalAlign=top;" in style


def test_placeholder_has_marker_and_dashed():
    style = _style_of(DiagramModel(nodes=[Node(id="n0", kind="placeholder")]))
    assert "sddType=placeholder;" in style and "dashed=1;" in style


def test_geometry_is_copied_without_flip():
    _xml, root = _emit(
        DiagramModel(nodes=[Node(id="n0", kind="rectangle", x=10, y=20, w=100, h=50)])
    )
    geo = _cells(root)[0].find("mxGeometry")
    assert (geo.get("x"), geo.get("y"), geo.get("width"), geo.get("height")) == (
        "10",
        "20",
        "100",
        "50",
    )


def test_opacity_scaled_0_1_to_0_100():
    assert "opacity=50;" in _style_of(
        DiagramModel(nodes=[Node(id="n0", kind="rectangle", opacity=0.5)])
    )


def test_dash_emitted_as_dashed_with_pattern():
    style = _style_of(DiagramModel(nodes=[Node(id="n0", kind="rectangle", dash="8,8")]))
    assert "dashed=1;" in style and "dashPattern=8 8;" in style


def test_structural_cells_present():
    _xml, root = _emit(DiagramModel(nodes=[Node(id="n0", kind="rectangle")]))
    ids = [c.get("id") for c in root.iter("mxCell")]
    assert "0" in ids and "1" in ids  # mandatory root + default layer


def test_edge_emits_source_target_and_waypoints_and_arrow():
    model = DiagramModel(edges=[Edge(id="e0", points=[(0, 0), (5, 5), (10, 0)], end_arrow=True)])
    _xml, root = _emit(model)
    geo = _cells(root)[0].find("mxGeometry")
    roles = {pt.get("as") for pt in geo.findall("mxPoint")}
    assert {"sourcePoint", "targetPoint"} <= roles
    arr = geo.find("Array")
    assert arr is not None and len(arr.findall("mxPoint")) == 1  # one mid waypoint
    assert "endArrow=classic;" in (_cells(root)[0].get("style") or "")


# ── parse: inverse round-trips the model exactly ────────────────────────────────


@pytest.mark.parametrize(
    "node",
    [
        Node(
            id="n0",
            kind="rectangle",
            x=1,
            y=2,
            w=30,
            h=40,
            fill="#fff",
            stroke="#123",
            stroke_width=2,
        ),
        Node(id="n0", kind="round_rectangle", x=5, y=6, w=10, h=10, dash="4,4"),
        Node(id="n0", kind="ellipse", opacity=0.3),
        Node(id="n0", kind="diamond", rotation=45),
        Node(
            id="n0",
            kind="text",
            text="Hello World",
            font_px=16,
            text_color="#202124",
            valign="bottom",
        ),
        Node(id="n0", kind="image", image_url="data:image/png;base64,AAAB"),
        Node(
            id="n0", kind="svg", svg_inner="<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>"
        ),
        # placeholders always carry the fixed dashed-grey style (see _placeholder_node)
        Node(
            id="n0",
            kind="placeholder",
            x=1,
            y=1,
            w=9,
            h=9,
            fill="none",
            stroke="#cccccc",
            stroke_width=1.0,
            dash="4,4",
        ),
    ],
)
def test_node_roundtrips_through_drawio(node):
    model = DiagramModel(nodes=[node])
    back = drawio_to_model(model_to_drawio(model)[0])
    assert back.to_dict() == model.to_dict()


def test_edge_roundtrips_through_drawio():
    model = DiagramModel(
        edges=[
            Edge(
                id="e0",
                points=[(0, 0), (5, 5), (10, 0)],
                stroke="#555",
                stroke_width=2,
                dash="8,8",
                start_arrow=True,
                end_arrow=True,
            )
        ]
    )
    back = drawio_to_model(model_to_drawio(model)[0])
    assert back.to_dict() == model.to_dict()


def test_image_data_uri_with_semicolon_roundtrips():
    # ';base64,' would corrupt a ';'-separated style string if not escaped.
    url = "data:image/png;base64,iVBORw0KGgo="
    model = DiagramModel(nodes=[Node(id="n0", kind="image", image_url=url)])
    back = drawio_to_model(model_to_drawio(model)[0])
    assert back.nodes[0].image_url == url


def test_metrics_count_kinds():
    model = DiagramModel(
        nodes=[
            Node(id="n0", kind="rectangle"),
            Node(id="n1", kind="placeholder"),
            Node(id="n2", kind="svg", svg_inner="<svg/>"),
        ],
        edges=[Edge(id="e0", points=[(0, 0), (1, 1)])],
    )
    _xml, metrics = model_to_drawio(model)
    assert metrics == {"nodes": 3, "edges": 1, "placeholders": 1, "svgs": 1, "images": 0}


def test_mxfile_envelope_is_tolerated_by_parser():
    xml = model_to_drawio(DiagramModel(nodes=[Node(id="n0", kind="rectangle")]))[0]
    assert xml.startswith("<mxfile")  # emitter wraps in <mxfile><diagram>
    assert len(drawio_to_model(xml).nodes) == 1  # parser finds the nested mxGraphModel


def test_invalid_xml_raises():
    with pytest.raises(ConversionError):
        drawio_to_model("<mxfile><diagram>")
    with pytest.raises(ConversionError):
        drawio_to_model("<foo/>")  # no mxGraphModel
