"""Tests for the docx → Markdown converter (flow B, ``convert/docx_to_md.py``)
and its ``sdd-pipeline convert-docx`` CLI surface.

The metadata-harvest / image-strip / guard tests are pure (a synthesized docx
zip, no pandoc); the real round-trip and CLI end-to-end are ``slow`` + pandoc-
gated (they build a genuine docx with pandoc, then convert it back).
"""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sdd_pipeline.cli import app
from sdd_pipeline.convert import ConversionError
from sdd_pipeline.convert import docx_to_md as d2m

runner = CliRunner()

_CORE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
    xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:dcterms="http://purl.org/dc/terms/"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{title}</dc:title>
  <dc:creator>{creator}</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2024-02-01T12:00:00Z</dcterms:modified>
</cp:coreProperties>
"""


def _make_docx(
    path: Path,
    *,
    title: str = "Sample Title",
    creator: str = "Jane Doe",
    created: str = "2024-01-15T10:00:00Z",
    with_core: bool = True,
) -> Path:
    """Synthesize a minimal docx *package* (zip) — enough for the pure tests.

    Carries ``word/document.xml`` (so ``_is_docx`` accepts it) and, when
    ``with_core``, a ``docProps/core.xml`` with the given properties. Not a
    pandoc-valid document — the real round-trip uses a pandoc-built docx.
    """
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        if with_core:
            zf.writestr(
                "docProps/core.xml",
                _CORE_XML.format(title=title, creator=creator, created=created),
            )
    return path


def _pandoc_ok() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def _real_docx(path: Path, markdown: str) -> Path:
    """Build a genuine .docx from markdown via pandoc (for the slow tests)."""
    subprocess.run(
        ["pandoc", "--from", "gfm", "--to", "docx", "-o", str(path)],
        input=markdown.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return path


# ── harvest_docx_metadata — pure (stdlib zip/xml, no pandoc) ──────────────────


class TestHarvestMetadata:
    def test_reads_core_properties(self, tmp_path: Path):
        docx = _make_docx(
            tmp_path / "a.docx", title="My Doc", creator="Ada", created="2023-05-01T00:00:00Z"
        )
        meta = d2m.harvest_docx_metadata(docx)
        assert meta["title"] == "My Doc"
        assert meta["author"] == "Ada"
        assert meta["date"] == "2023-05-01T00:00:00Z"

    def test_missing_core_xml_returns_empty(self, tmp_path: Path):
        docx = _make_docx(tmp_path / "b.docx", with_core=False)
        assert d2m.harvest_docx_metadata(docx) == {}

    def test_non_zip_returns_empty(self, tmp_path: Path):
        plain = tmp_path / "c.docx"
        plain.write_text("not a zip", encoding="utf-8")
        assert d2m.harvest_docx_metadata(plain) == {}

    def test_blank_values_are_skipped(self, tmp_path: Path):
        docx = _make_docx(tmp_path / "d.docx", title="", creator="", created="")
        assert d2m.harvest_docx_metadata(docx) == {}


# ── guards / helpers — pure ───────────────────────────────────────────────────


class TestGuards:
    def test_is_docx_true_for_package(self, tmp_path: Path):
        assert d2m._is_docx(_make_docx(tmp_path / "ok.docx"))

    def test_is_docx_false_for_plain_file(self, tmp_path: Path):
        plain = tmp_path / "x.docx"
        plain.write_text("hello", encoding="utf-8")
        assert not d2m._is_docx(plain)

    def test_is_docx_false_for_non_word_zip(self, tmp_path: Path):
        z = tmp_path / "z.docx"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("foo.txt", "bar")
        assert not d2m._is_docx(z)

    def test_convert_rejects_non_docx(self, tmp_path: Path):
        plain = tmp_path / "fake.docx"
        plain.write_text("not really a docx", encoding="utf-8")
        with pytest.raises(ConversionError, match=r"not a valid \.docx"):
            d2m.convert_docx_file(plain, write=False)

    def test_convert_missing_file(self, tmp_path: Path):
        with pytest.raises(ConversionError, match="not found"):
            d2m.convert_docx_file(tmp_path / "nope.docx", write=False)


class TestStripImages:
    def test_image_becomes_alt_text(self):
        assert d2m._strip_images("see ![A diagram](media/x.png) here") == "see A diagram here"

    def test_empty_alt_dropped(self):
        assert d2m._strip_images("x ![](media/y.png) z") == "x  z"

    def test_non_image_link_untouched(self):
        md = "a [real link](http://e/x) b"
        assert d2m._strip_images(md) == md


# ── real round-trip + CLI — slow, pandoc-gated ────────────────────────────────

_SAMPLE_MD = """# Architecture Overview

The service validates requests and issues short-lived tokens.

## Decision

We chose PostgreSQL for durability.

- first point
- second point
"""


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
class TestRealRoundTrip:
    def test_docx_converts_to_markdown(self, tmp_path: Path):
        docx = _real_docx(tmp_path / "doc.docx", _SAMPLE_MD)
        out = tmp_path / "doc.md"
        out_path, md, metrics, notes = d2m.convert_docx_file(docx, out, extract_media=False)
        assert out_path == out and out.exists()
        assert "# Architecture Overview" in md
        assert "## Decision" in md
        assert "PostgreSQL" in md
        assert metrics["sections"] >= 2
        assert notes["errors"] == []

    def test_frontmatter_includes_provenance(self, tmp_path: Path):
        docx = _real_docx(tmp_path / "p.docx", _SAMPLE_MD)
        _, md, _, _ = d2m.convert_docx_file(
            docx, tmp_path / "p.md", space="ENG", source_url="http://e/p", labels=["a", "b"]
        )
        import yaml

        fm = yaml.safe_load(md.split("---")[1])
        assert fm["space"] == "ENG"
        assert fm["url"] == "http://e/p"
        assert fm["labels"] == ["a", "b"]
        assert fm["source_file"] == "p.docx"

    def test_no_frontmatter_flag(self, tmp_path: Path):
        docx = _real_docx(tmp_path / "n.docx", _SAMPLE_MD)
        _, md, _, _ = d2m.convert_docx_file(docx, tmp_path / "n.md", add_frontmatter=False)
        assert not md.startswith("---")


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
class TestConvertDocxCli:
    def test_batch_convert_and_report(self, tmp_path: Path):
        in_dir = tmp_path / "in"
        in_dir.mkdir()
        _real_docx(in_dir / "one.docx", _SAMPLE_MD)
        _real_docx(in_dir / "two.docx", _SAMPLE_MD)
        out = tmp_path / "out"
        report = tmp_path / "r.json"

        result = runner.invoke(
            app, ["convert-docx", str(in_dir), "-o", str(out), "-r", str(report), "--no-media"]
        )
        assert result.exit_code == 0, result.output
        assert (out / "one.md").exists()
        assert (out / "two.md").exists()
        doc = json.loads(report.read_text(encoding="utf-8"))
        assert doc["succeeded"] == 2
        assert doc["failed"] == 0

    def test_failed_file_exits_nonzero(self, tmp_path: Path):
        in_dir = tmp_path / "in"
        in_dir.mkdir()
        (in_dir / "bad.docx").write_text("not a docx", encoding="utf-8")
        out = tmp_path / "out"
        report = tmp_path / "r.json"

        result = runner.invoke(
            app, ["convert-docx", str(in_dir), "-o", str(out), "-r", str(report)]
        )
        assert result.exit_code == 1, result.output
        doc = json.loads(report.read_text(encoding="utf-8"))
        assert doc["failed"] == 1
        assert doc["files"][0]["status"] == "error"

    def test_no_docx_files_is_clean_exit(self, tmp_path: Path):
        in_dir = tmp_path / "empty"
        in_dir.mkdir()
        result = runner.invoke(
            app,
            [
                "convert-docx",
                str(in_dir),
                "-o",
                str(tmp_path / "o"),
                "-r",
                str(tmp_path / "r.json"),
            ],
        )
        assert result.exit_code == 0
        assert "No .docx files" in result.output
