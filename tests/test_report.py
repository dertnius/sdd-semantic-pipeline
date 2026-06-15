"""Tests for the per-file pipeline report (``sdd-pipeline report`` / report.py).

Fast tests are pure (tier mapping, HTML/graph helpers, and the storage-format
rejection — which is a pure-regex front door, so it needs no pandoc). The
end-to-end generation over the example corpus is ``slow`` + pandoc-gated.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.convert.base import ConversionNotes
from sdd_pipeline.report import (
    FileReport,
    GraphEdge,
    GraphModel,
    GraphNode,
    LossMetrics,
    _build_tiers,
    _collapsible,
    _esc,
    build_file_report,
    generate_reports,
    render_edge_table,
    render_graph_svg,
    render_index_html,
)

_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _ROOT / "tests" / "convert" / "examples"
_STORAGE = _EXAMPLES / "order-management-sad.storage.html"


def _pandoc_ok() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


# ── Fast: storage-format rejection (pure regex, no pandoc) ─────────────────────


def test_storage_file_reported_rejected(tmp_path: Path):
    rep = build_file_report(_STORAGE, tmp_path / "out", PipelineConfig())
    assert rep.status == "rejected"
    assert "storage" in rep.reason.lower()
    assert rep.loss is not None and rep.loss.visible_text_retention == 0.0
    out = tmp_path / "out"
    assert (out / "original.html").exists()
    assert (out / "rejection.json").exists()
    assert (out / "report.html").exists()
    assert not (out / "final.md").exists()  # the trace stops at the front door
    rejection = json.loads((out / "rejection.json").read_text("utf-8"))
    assert rejection["status"] == "rejected"


# ── Fast: tier mapping ─────────────────────────────────────────────────────────


def test_build_tiers_maps_each_signal():
    notes = ConversionNotes()
    notes.macro_counts = {"diagram": 1, "merged_table": 2, "dropped_tag": 3}
    loss = LossMetrics(
        md_quality_issues=[{"rule": "html_leakage", "severity": "block", "detail": "x"}],
        chunk_poison=1,
    )
    tiers = _build_tiers(loss, notes, dropped=["alpha", "beta"], has_table=True)
    joined = {k: " ".join(v) for k, v in tiers.items()}
    assert "diagram" in joined["tier1"]
    assert "token" in joined["tier1"]  # dropped source tokens
    assert "merged_table" in joined["tier2"]
    assert "colour" in joined["tier2"]  # silent cell-colour loss (table present)
    assert "dropped_tag" in joined["tier3"]
    assert "html_leakage" in joined["tier3"]
    assert "poisoned" in joined["tier3"]


def test_build_tiers_clean_doc_is_empty():
    tiers = _build_tiers(LossMetrics(), ConversionNotes(), dropped=[], has_table=False)
    assert tiers == {"tier1": [], "tier2": [], "tier3": []}


def test_is_low_signal_flags_hollow_prose_only():
    from types import SimpleNamespace

    from sdd_pipeline.report import _is_low_signal

    low = SimpleNamespace(content_type="paragraph", content="Release checklist:")
    fname = SimpleNamespace(content_type="paragraph", content="application.yaml")
    real = SimpleNamespace(
        content_type="paragraph", content="The order service validates requests and issues tokens."
    )
    code = SimpleNamespace(content_type="code", content="x = 1")  # short but legit
    assert _is_low_signal(low) and _is_low_signal(fname)
    assert not _is_low_signal(real)
    assert not _is_low_signal(code)  # code/table never flagged


# ── Fast: HTML + graph helpers ─────────────────────────────────────────────────


def test_esc_escapes_markup():
    assert _esc("<a href='x'>&") == "&lt;a href=&#x27;x&#x27;&gt;&amp;"


def test_collapsible_wraps_in_details():
    html = _collapsible("Title <x>", "<p>body</p>")
    assert html.startswith("<details>")
    assert "<summary>Title &lt;x&gt;</summary>" in html
    assert "<p>body</p>" in html


def _sample_graph() -> GraphModel:
    return GraphModel(
        nodes=[
            GraphNode("sec:a", "section", "Overview"),
            GraphNode("blk:1", "block", "paragraph"),
            GraphNode("chunk:1", "chunk", "paragraph #0"),
            GraphNode("ent:redis", "entity", "Redis"),
        ],
        edges=[
            GraphEdge("sec:a", "blk:1", "contains"),
            GraphEdge("sec:a", "chunk:1", "chunked_as"),
            GraphEdge("sec:a", "ent:redis", "entity"),
        ],
    )


def test_edge_table_contains_every_edge():
    table = render_edge_table(_sample_graph())
    assert table.count("<td>") == 9  # 3 edges x 3 cells (header uses <th>)
    assert "contains" in table and "chunked_as" in table and "entity" in table
    assert "Overview" in table and "Redis" in table


def test_graph_svg_is_self_contained():
    svg = render_graph_svg(_sample_graph())
    assert svg.startswith("<svg viewBox") and svg.endswith("</svg>")
    assert "http" not in svg.replace("http://www.w3.org/2000/svg", "")  # no external refs
    assert "Overview" in svg and "Redis" in svg


def test_render_index_html_lists_files():
    reps = [
        FileReport(
            source=Path("a.html"),
            out_dir=Path("a"),
            status="ok",
            chunk_count=3,
            loss=LossMetrics(
                visible_text_retention=0.9, tiers={"tier1": [], "tier2": ["x"], "tier3": []}
            ),
        ),
        FileReport(source=Path("b.storage.html"), out_dir=Path("b"), status="rejected"),
    ]
    html = render_index_html(reps)
    assert "a.html" in html and "b.storage.html" in html
    assert "90.0%" in html
    assert "badge ok" in html and "badge rejected" in html


# ── Slow + pandoc: full generation over the example corpus ─────────────────────


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
def test_generate_reports_over_examples(tmp_path: Path):
    reps = generate_reports(_EXAMPLES, tmp_path)
    by_name = {r.source.name: r for r in reps}
    assert by_name["order-management-sad.html"].status == "ok"
    assert by_name["adversarial-edge-cases.html"].status == "ok"
    assert by_name["order-management-sad.storage.html"].status == "rejected"

    # Index + machine report.
    assert (tmp_path / "index.html").exists()
    agg = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert agg["ok"] == 2 and agg["rejected"] == 1 and agg["errored"] == 0

    # Full artifact set for an ok file.
    sad = tmp_path / "order-management-sad"
    for name in (
        "report.html",
        "original.html",
        "stage_a_clean.html",
        "stage_b_ast.json",
        "stage_c_filtered_ast.json",
        "raw.gfm.md",
        "final.md",
        "ast.json",
        "structural.json",
        "enriched.json",
        "chunks.json",
        "quality.json",
        "taxonomy.json",
        "vocabulary.json",
        "inventory.json",
        "graph.json",
    ):
        assert (sad / name).exists(), f"missing {name}"


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
def test_loss_metrics_and_tiers(tmp_path: Path):
    reps = generate_reports(_EXAMPLES, tmp_path)
    by_name = {r.source.name: r for r in reps}
    for name in ("order-management-sad.html", "adversarial-edge-cases.html"):
        loss = by_name[name].loss
        assert loss is not None and 0.0 < loss.visible_text_retention <= 1.0
        assert by_name[name].chunk_count > 0
    # The adversarial corpus exercises Tier-2 degradations (merged table / diagram).
    adv = by_name["adversarial-edge-cases.html"].loss
    assert adv is not None and adv.tiers["tier2"]


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
def test_final_md_is_authoritative_convert_file_output(tmp_path: Path):
    # final.md must be exactly convert_file's output (the corpus input), so the
    # report never indexes a divergent replay. Compared in isolation per file.
    from sdd_pipeline.convert import convert_file

    src = _EXAMPLES / "order-management-sad.html"
    _, canonical, _, _ = convert_file(src, None, write=False)
    build_file_report(src, tmp_path / "o", PipelineConfig())
    disk = (tmp_path / "o" / "final.md").read_text("utf-8")
    # Report artifacts are LF-only; pandoc may emit CRLF on Windows. Content-equal.
    assert disk.replace("\r\n", "\n") == canonical.replace("\r\n", "\n")


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
def test_report_json_is_deterministic(tmp_path: Path):
    generate_reports(_EXAMPLES, tmp_path / "a")
    generate_reports(_EXAMPLES, tmp_path / "b")
    a = (tmp_path / "a" / "report.json").read_text("utf-8")
    b = (tmp_path / "b" / "report.json").read_text("utf-8")
    assert a == b  # report.json carries no timestamp → byte-identical
