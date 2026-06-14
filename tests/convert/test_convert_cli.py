"""Tests for the convert-related CLI surface (``sdd-pipeline convert``) and the
legacy standalone script entry. Extracted from ``tests/test_cli.py`` so the
converter (flow B) owns its own test collection.

The confidence-verdict and frontmatter tests are pure logic (no pandoc); the
quarantine end-to-end and the script-mode smoke are ``slow`` + pandoc-gated.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sdd_pipeline.cli import app
from sdd_pipeline.convert import html_to_gitlab_md as h2m

runner = CliRunner()

# Inner project root (… / tests / convert / this file → parents[2]).
_ROOT = Path(__file__).resolve().parents[2]

# A body with > 200 substantive chars so the content_density stub check stays quiet.
_PROSE = (
    "The authentication service validates incoming requests against the policy "
    "engine and issues short-lived tokens. It records every decision for audit "
    "and exposes health metrics to the platform monitoring stack continuously.\n"
)


def _pandoc_ok() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


class TestConvertConfidenceVerdict:
    """Arm 2 verdict logic is pure dict work — no pandoc needed."""

    def test_clean_notes_are_trustworthy(self):
        from sdd_pipeline.cli import _convert_confidence_reasons

        notes = {"metadata": {"confluence_version": "dc"}, "macro_counts": {"panel": 2}}
        assert _convert_confidence_reasons(notes, 8) == []

    def test_root_fallback_quarantines(self):
        from sdd_pipeline.cli import _convert_confidence_reasons

        notes = {"metadata": {"root_fallback": "true"}, "macro_counts": {}}
        assert _convert_confidence_reasons(notes, 8)

    def test_many_dropped_tags_quarantine(self):
        from sdd_pipeline.cli import _convert_confidence_reasons

        notes = {"metadata": {}, "macro_counts": {"dropped_tag": 20}}
        assert _convert_confidence_reasons(notes, 8)

    def test_few_dropped_tags_are_fine(self):
        from sdd_pipeline.cli import _convert_confidence_reasons

        notes = {"metadata": {}, "macro_counts": {"dropped_tag": 3}}
        assert _convert_confidence_reasons(notes, 8) == []


class TestConvertFrontmatter:
    """Provenance frontmatter emission is pure string work — no pandoc needed."""

    def test_postprocess_emits_provenance_keys(self):
        from sdd_pipeline.convert import postprocess

        md = postprocess(
            md="# Head\n\nbody\n",
            title="AIP-107",
            author="",
            source_path=Path("aip-107.html"),
            add_frontmatter=True,
            add_toc=False,
            space="DEMO",
            source_url="https://example/aip-107",
            labels=["airflow", "aip"],
        )
        # Keys must match what structural._extract_metadata reads back.
        # FM-YAML-SAFE: the block is real YAML now — assert parsed values, not
        # the quote style.
        import yaml

        fm = yaml.safe_load(md.split("---")[1])
        assert fm["space"] == "DEMO"
        assert fm["url"] == "https://example/aip-107"
        assert fm["labels"] == ["airflow", "aip"]

    def test_postprocess_omits_absent_provenance(self):
        from sdd_pipeline.convert import postprocess

        md = postprocess(
            md="# Head\n\nbody\n",
            title="T",
            author="",
            source_path=Path("p.html"),
            add_frontmatter=True,
            add_toc=False,
        )
        assert "space:" not in md
        assert "\nurl:" not in md
        assert "labels:" not in md


class TestLegacyScriptEntry:
    """The standalone `python …/convert/html_to_gitlab_md.py` entry (documented in
    docs/inbox/Convert.*.Readme.md) must keep working after the package move —
    previously an untested silent-break surface."""

    def test_build_parser_parses_core_args(self):
        # Pandoc-free: proves the argparse entry still constructs.
        args = h2m.build_parser().parse_args(
            ["in.html", "-o", "out.md", "--toc", "--no-frontmatter"]
        )
        assert str(args.input) == "in.html"
        assert str(args.output) == "out.md"
        assert args.toc is True
        assert args.no_frontmatter is True

    @pytest.mark.slow
    @pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
    def test_script_mode_invocation_runs(self, tmp_path: Path):
        # Exercises the script-mode import fallback (`from sdd_pipeline.convert…`).
        script = _ROOT / "src" / "sdd_pipeline" / "convert" / "html_to_gitlab_md.py"
        src_html = Path(__file__).resolve().parent / "examples" / "order-management-sad.html"
        out_md = tmp_path / "out.md"
        # The legacy script's main() prints emoji status lines; PYTHONUTF8 keeps the
        # child's stdout UTF-8 so it doesn't crash on a Windows cp1252 console.
        result = subprocess.run(
            [sys.executable, str(script), str(src_html), "-o", str(out_md)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 0, result.stderr
        assert out_md.exists() and out_md.read_text(encoding="utf-8").strip()


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
class TestConvertQuarantineEndToEnd:
    def test_low_confidence_page_is_quarantined(self, tmp_path: Path):
        # No recognised content container → root falls back to <body> → quarantine.
        (tmp_path / "page.html").write_text(
            "<html><body><h1>Title</h1><p>" + _PROSE + "</p></body></html>",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        report = tmp_path / "r.json"
        result = runner.invoke(app, ["convert", str(tmp_path), "-o", str(out), "-r", str(report)])
        assert result.exit_code == 1, result.output
        assert (out / "_quarantine" / "page.md").exists()
        assert not (out / "page.md").exists()
        doc = json.loads(report.read_text(encoding="utf-8"))
        assert doc["quarantined"] == 1
        entry = next(f for f in doc["files"] if f["source"].endswith("page.html"))
        assert entry["status"] == "quarantined"
        assert entry["quarantine_reasons"]
