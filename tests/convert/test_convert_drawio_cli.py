"""Tests for the ``sdd-pipeline convert-drawio`` CLI surface.

Model-free and pandoc-free (Gliffy→draw.io is pure JSON→XML). The autouse
``_workspace_env`` fixture disables the workspace guard so arbitrary tmp paths work.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from sdd_pipeline.cli import app

runner = CliRunner()

_RECT = {
    "stage": {
        "objects": [
            {
                "x": 10,
                "y": 10,
                "width": 100,
                "height": 50,
                "order": 0,
                "graphic": {"type": "Shape", "Shape": {"tid": "rectangle", "fillColor": "#fff"}},
            }
        ]
    }
}


def _write_gliffy(path: Path, scene: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scene), encoding="utf-8")


def test_convert_drawio_happy_path_with_check(tmp_path: Path):
    in_dir = tmp_path / "in"
    _write_gliffy(in_dir / "a.gliffy", _RECT)
    _write_gliffy(in_dir / "sub" / "b.gliffy", _RECT)
    out = tmp_path / "out"
    report = tmp_path / "r.json"

    result = runner.invoke(
        app, ["convert-drawio", str(in_dir), "-o", str(out), "-r", str(report), "--check"]
    )
    assert result.exit_code == 0, result.output
    assert (out / "a.drawio").exists()
    assert (out / "sub" / "b.drawio").exists()  # input tree mirrored

    doc = json.loads(report.read_text(encoding="utf-8"))
    assert doc["total_files"] == 2 and doc["succeeded"] == 2 and doc["mismatched"] == 0
    assert doc["checked"] is True
    entry = doc["files"][0]
    assert entry["status"] == "ok" and entry["fidelity"]["equal"] is True
    # the written file is real draw.io XML
    assert "<mxGraphModel" in (out / "a.drawio").read_text(encoding="utf-8")


def test_convert_drawio_reports_and_exits_on_bad_file(tmp_path: Path):
    in_dir = tmp_path / "in"
    (in_dir).mkdir(parents=True)
    (in_dir / "bad.gliffy").write_text("{not json", encoding="utf-8")
    out = tmp_path / "out"
    report = tmp_path / "r.json"

    result = runner.invoke(app, ["convert-drawio", str(in_dir), "-o", str(out), "-r", str(report)])
    assert result.exit_code == 1, result.output
    doc = json.loads(report.read_text(encoding="utf-8"))
    assert doc["failed"] == 1 and doc["files"][0]["status"] == "error"


def test_convert_drawio_no_files_exits_zero(tmp_path: Path):
    in_dir = tmp_path / "in"
    in_dir.mkdir(parents=True)
    result = runner.invoke(app, ["convert-drawio", str(in_dir), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0
    assert "No Gliffy files" in result.output
