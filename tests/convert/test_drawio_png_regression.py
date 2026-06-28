"""Secondary oracle: PNG-regression of the SVG renderer's output.

This is a drift tripwire on ``render_gliffy`` — NOT cross-tool Gliffy-vs-draw.io
equality. It needs the optional ``[raster]`` extra (cairosvg + pillow), so it is
``slow`` and skipped when those imports are unavailable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# cairosvg loads the native cairo lib at import time and raises OSError (not
# ImportError) when it's missing — common on Windows — so importorskip alone
# isn't enough; catch both and skip the whole module.
try:
    import cairosvg  # noqa: F401
    import PIL  # noqa: F401
except (ImportError, OSError) as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"raster deps unavailable ({exc})", allow_module_level=True)

from sdd_pipeline.convert import render_gliffy
from sdd_pipeline.convert.fidelity import png_regression_check, write_golden_png

pytestmark = pytest.mark.slow

_SCENE = json.dumps(
    {
        "stage": {
            "objects": [
                {
                    "x": 10,
                    "y": 10,
                    "width": 120,
                    "height": 60,
                    "order": 0,
                    "graphic": {
                        "type": "Shape",
                        "Shape": {
                            "tid": "rectangle",
                            "fillColor": "#4a86e8",
                            "strokeColor": "#000000",
                        },
                    },
                }
            ]
        }
    }
)


def test_png_regression_passes_against_its_own_golden(tmp_path: Path):
    svg, _ = render_gliffy(_SCENE)
    golden = write_golden_png(svg, tmp_path / "golden.png")
    result = png_regression_check(svg, golden)
    assert result["equal"] and result["diff_ratio"] == 0.0


def test_png_regression_detects_a_visual_change(tmp_path: Path):
    svg, _ = render_gliffy(_SCENE)
    golden = write_golden_png(svg, tmp_path / "golden.png")
    changed = svg.replace("#4a86e8", "#e06666")  # recolor the fill
    result = png_regression_check(changed, golden)
    assert not result["equal"] and result["diff_ratio"] > 0.0


def test_png_regression_missing_golden_is_not_equal(tmp_path: Path):
    svg, _ = render_gliffy(_SCENE)
    result = png_regression_check(svg, tmp_path / "nope.png")
    assert not result["equal"] and "missing" in result.get("reason", "")
