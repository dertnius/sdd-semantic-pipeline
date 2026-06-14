"""
Tests for sdd_pipeline.html_to_gitlab_md and the ``sdd-pipeline convert`` CLI.

Metric tests are pure-Python (no pandoc). End-to-end conversion tests are
guarded by ``requires_pandoc`` and marked ``slow``. The CLI batch/report tests
monkeypatch the converter so they exercise discovery, report shape, and
partial-failure handling without needing pandoc.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sdd_pipeline import html_to_gitlab_md as h2m
from sdd_pipeline.cli import app

# ── Skip guard ────────────────────────────────────────────────────────────────


def _pandoc_available() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


requires_pandoc = pytest.mark.skipif(
    not _pandoc_available(),
    reason="pandoc binary not found on PATH",
)

runner = CliRunner()


# ── stats / metrics ─────────────────────────────────────────────────────────


class TestStats:
    def test_counts_sections(self):
        md = "# A\n\n## B\n\n### C\n\ntext\n"
        assert h2m.stats(md)["sections"] == 3

    def test_counts_pictures(self):
        md = "![alt](a.png)\n\nwords ![](b.png) more\n"
        assert h2m.stats(md)["pictures"] == 2

    def test_counts_code_snippets(self):
        md = "```python\nx = 1\n```\n\n```\nplain\n```\n"
        assert h2m.stats(md)["code_snippets"] == 2

    def test_counts_lists(self):
        md = "- a\n- b\n1. c\n* d\n"
        assert h2m.stats(md)["lists"] == 4

    def test_counts_one_table_per_delimiter_row(self):
        md = "| H1 | H2 |\n| --- | --- |\n| a | b |\n| c | d |\n"
        assert h2m.stats(md)["tables"] == 1

    def test_thematic_break_is_not_a_table(self):
        md = "before\n\n---\n\nafter\n"
        assert h2m.stats(md)["tables"] == 0

    def test_counts_urls_links_autolinks_and_bare(self):
        md = (
            "[link](https://a.com)\n"
            "<https://b.com>\n"
            "see https://c.com here\n"
            "![img](https://d.com/x.png)\n"  # image, not a URL link
        )
        assert h2m.stats(md)["urls"] == 3

    def test_aliases_match(self):
        md = "# A\n\n```\ncode\n```\n"
        s = h2m.stats(md)
        assert s["sections"] == s["headings"]
        assert s["code_snippets"] == s["code_blocks"]

    def test_report_fields_present(self):
        s = h2m.stats("# Title\n")
        for field in ("sections", "pictures", "code_snippets", "lists", "tables", "urls"):
            assert field in s


# ── resolve_pandoc ───────────────────────────────────────────────────────────


class TestResolvePandoc:
    def test_explicit_path_returned(self):
        assert h2m.resolve_pandoc("/custom/pandoc") == "/custom/pandoc"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.setattr(h2m.shutil, "which", lambda _: None)
        with pytest.raises(h2m.ConversionError):
            h2m.resolve_pandoc(None)


# ── convert_file (end-to-end, needs pandoc) ──────────────────────────────────


class TestConvertFile:
    def test_raises_on_missing_source(self, tmp_path: Path):
        with pytest.raises(h2m.ConversionError):
            h2m.convert_file(tmp_path / "nope.html")

    @requires_pandoc
    @pytest.mark.slow
    def test_writes_md_and_returns_metrics(self, tmp_path: Path):
        src = tmp_path / "doc.html"
        src.write_text(
            "<html><body><main>"
            "<h1>Title</h1><h2>Section</h2>"
            "<p>Body with <a href='https://x.com'>a link</a>.</p>"
            "<ul><li>one</li><li>two</li></ul>"
            "</main></body></html>",
            encoding="utf-8",
        )
        out_path, md, metrics, notes = h2m.convert_file(src)
        assert out_path == src.with_suffix(".md")
        assert out_path.exists()
        assert metrics["sections"] >= 2
        assert metrics["lists"] >= 2
        assert metrics["urls"] >= 1
        assert "Title" in md
        assert set(notes) == {"warnings", "errors", "macro_counts", "languages", "metadata"}


# ── convert CLI (monkeypatched converter) ────────────────────────────────────


class _FakeMetrics:
    """Helper returning deterministic metrics for the fake converter."""

    SLIM = {
        "sections": 2,
        "pictures": 1,
        "code_snippets": 3,
        "lists": 4,
        "tables": 1,
        "urls": 5,
    }


def _install_fake_converter(monkeypatch, *, fail_on: str | None = None):
    monkeypatch.setattr(h2m, "resolve_pandoc", lambda _p=None: "pandoc")

    def fake_convert_file(src, output=None, **_kw):
        src = Path(src)
        if fail_on and src.name == fail_on:
            raise h2m.ConversionError("boom")
        out = Path(output) if output is not None else src.with_suffix(".md")
        metrics = dict(_FakeMetrics.SLIM)
        notes = {"warnings": [], "errors": [], "macro_counts": {}, "languages": [], "metadata": {}}
        return out, "# md\n", metrics, notes

    monkeypatch.setattr(h2m, "convert_file", fake_convert_file)


class TestConvertCli:
    def _make_docs(self, tmp_path: Path, names: list[str]) -> Path:
        docs = tmp_path / "docs"
        docs.mkdir()
        for n in names:
            (docs / n).write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
        return docs

    def test_no_files_found_exits_zero(self, tmp_path: Path, monkeypatch):
        _install_fake_converter(monkeypatch)
        docs = tmp_path / "docs"
        docs.mkdir()
        report = tmp_path / "report.json"
        result = runner.invoke(app, ["convert", str(docs), "--report", str(report)])
        assert result.exit_code == 0
        assert "No HTML files" in result.stdout

    def test_report_written_with_metrics_and_totals(self, tmp_path: Path, monkeypatch):
        _install_fake_converter(monkeypatch)
        docs = self._make_docs(tmp_path, ["a.html", "b.html"])
        report = tmp_path / "out" / "report.json"

        result = runner.invoke(app, ["convert", str(docs), "--report", str(report)])
        assert result.exit_code == 0

        doc = json.loads(report.read_text(encoding="utf-8"))
        assert doc["total_files"] == 2
        assert doc["succeeded"] == 2
        assert doc["failed"] == 0
        assert len(doc["files"]) == 2
        # Per-file metrics carry exactly the report fields (invariant preserved).
        for entry in doc["files"]:
            assert entry["status"] == "ok"
            assert set(entry["metrics"]) == set(_FakeMetrics.SLIM)
            # Notes ride alongside metrics (spec §16), not inside them.
            assert set(entry["notes"]) == {
                "warnings",
                "errors",
                "macro_counts",
                "languages",
                "metadata",
            }
        # Totals == sum of per-file metrics.
        assert doc["totals"]["urls"] == 2 * _FakeMetrics.SLIM["urls"]
        assert doc["totals"]["sections"] == 2 * _FakeMetrics.SLIM["sections"]
        # Report-level aggregates exist.
        assert "warnings_total" in doc
        assert "macro_counts" in doc

    def test_partial_failure_captured_and_nonzero_exit(self, tmp_path: Path, monkeypatch):
        _install_fake_converter(monkeypatch, fail_on="bad.html")
        docs = self._make_docs(tmp_path, ["good.html", "bad.html"])
        report = tmp_path / "report.json"

        result = runner.invoke(app, ["convert", str(docs), "--report", str(report)])
        assert result.exit_code == 1

        doc = json.loads(report.read_text(encoding="utf-8"))
        assert doc["succeeded"] == 1
        assert doc["failed"] == 1
        errors = [f for f in doc["files"] if f["status"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error"] == "boom"
        assert errors[0]["metrics"] is None

    def test_output_dir_mirrors_tree(self, tmp_path: Path, monkeypatch):
        _install_fake_converter(monkeypatch)
        docs = tmp_path / "docs"
        (docs / "sub").mkdir(parents=True)
        (docs / "sub" / "page.html").write_text("<p>x</p>", encoding="utf-8")
        out_dir = tmp_path / "md_out"
        report = tmp_path / "report.json"

        result = runner.invoke(
            app,
            ["convert", str(docs), "--output", str(out_dir), "--report", str(report)],
        )
        assert result.exit_code == 0
        doc = json.loads(report.read_text(encoding="utf-8"))
        expected = str(out_dir / "sub" / "page.md")
        assert doc["files"][0]["output"] == expected


# ── spec conformance (preprocess-only, no pandoc) ─────────────────────────────


def _pre(body_html: str) -> tuple[str, h2m.ConversionNotes]:
    """Run preprocess on <main>{body}</main> and return (clean_html, notes)."""
    notes = h2m.ConversionNotes()
    clean = h2m.preprocess(
        f"<html><body><main>{body_html}</main></body></html>", None, False, notes
    )
    return clean, notes


class TestContentRoot:
    def test_prefers_content_view_over_main_content(self):
        soup = __import__("bs4").BeautifulSoup(
            "<body><div id='main-content'><p>a</p></div>"
            "<div id='content-view'><p>b</p></div></body>",
            "lxml",
        )
        assert h2m._find_content_root(soup, None).get("id") == "content-view"

    def test_content_is_a_root(self):
        # HX-ROOT: div#content joined the chain (catalog-backed wrapper; space
        # index pages root there) — it now wins over the inner #main quirk.
        soup = __import__("bs4").BeautifulSoup(
            "<body><div id='content'><div id='main'><p>x</p></div></div></body>", "lxml"
        )
        assert h2m._find_content_root(soup, None).get("id") == "content"

    def test_main_fallback(self):
        soup = __import__("bs4").BeautifulSoup(
            "<body><div id='wrapper'><div id='main'><p>x</p></div></div></body>", "lxml"
        )
        assert h2m._find_content_root(soup, None).get("id") == "main"

    def test_explicit_selector_wins(self):
        soup = __import__("bs4").BeautifulSoup(
            "<body><div id='content-view'>x</div><article>y</article></body>", "lxml"
        )
        assert h2m._find_content_root(soup, "article").name == "article"


class TestSpecConformance:
    def test_lozenge_current_to_pfi_span(self):
        # HX-STATUS: PFI span.lozenge[data-colour] — no emoji, no inline code
        # (backticked status text gets mistaken for code entities).
        clean, _ = _pre("<span class='status-macro aui-lozenge aui-lozenge-current'>Active</span>")
        assert 'class="lozenge"' in clean and 'data-colour="current"' in clean
        assert "Active" in clean
        assert "🔵" not in clean and "<code>" not in clean

    def test_lozenge_success_to_pfi_span(self):
        clean, notes = _pre(
            "<span class='status-macro aui-lozenge aui-lozenge-success'>Approved</span>"
        )
        assert 'data-colour="success"' in clean and "Approved" in clean
        assert "✅" not in clean
        assert notes.macro_counts.get("status") == 1

    def test_brush_map_extended_langs(self):
        for brush, lang in [
            ("ts", "typescript"),
            ("terraform", "hcl"),
            ("powershell", "powershell"),
            ("golang", "go"),
        ]:
            clean, _ = _pre(
                f"<div class='code panel'><pre class='syntaxhighlighter-pre' "
                f"data-syntaxhighlighter-params='brush: {brush}'>x</pre></div>"
            )
            assert f'class="language-{lang}"' in clean

    def test_emoticon_name_keys_and_ac_emoticon(self):
        # HX-EMOTICON: plain searchable WORDS, never emoji.
        clean, _ = _pre(
            "<p><img class='emoticon' alt='(tick)'> and <ac:emoticon ac:name='smile'/></p>"
        )
        assert "yes" in clean and "smile" in clean
        assert "✅" not in clean and "😊" not in clean

    def test_info_macro_to_pfi_adm(self):
        # HX-ADMONITION: PFI div.adm[data-macro] with the body as real block
        # children (no flattening, no emoji) — PF-ADMONITION renders the quote.
        clean, notes = _pre(
            "<div class='confluence-information-macro confluence-information-macro-information'>"
            "<span class='aui-icon'>icon-text</span>"
            "<div class='confluence-information-macro-body'>Body here</div></div>"
        )
        assert "icon-text" not in clean
        assert 'class="adm"' in clean and 'data-macro="info"' in clean
        assert "Body here" in clean
        assert "ℹ️" not in clean
        assert notes.macro_counts.get("info") == 1

    def test_children_macro_removed(self):
        clean, _ = _pre("<div class='children-macro'><p>dynamic</p></div><p>keep</p>")
        assert "dynamic" not in clean and "keep" in clean

    def test_panel_title_and_body(self):
        clean, notes = _pre(
            "<div class='panel'><div class='panelHeader'>My Title</div>"
            "<div class='panelContent'>The body</div></div>"
        )
        assert 'data-macro="panel"' in clean and 'data-title="My Title"' in clean
        assert "The body" in clean
        assert "📋" not in clean
        assert notes.macro_counts.get("panel") == 1

    def test_code_panel_not_treated_as_panel(self):
        clean, notes = _pre(
            "<div class='code panel'><pre class='syntaxhighlighter-pre' "
            "data-syntaxhighlighter-params='brush: java'>class A{}</pre></div>"
        )
        assert 'class="language-java"' in clean
        assert "panel" not in notes.macro_counts

    def test_anchor_span_deleted(self):
        # Anchor policy: empty anchor targets are dropped; ids never survive
        # the scrub (the corpus carries no intra-page hrefs worth the HTML).
        clean, _ = _pre("<span id='sec-1'></span><p>text</p>")
        assert "sec-1" not in clean and "text" in clean

    def test_standalone_syntaxhighlighter_brush(self):
        clean, _ = _pre(
            "<pre class='syntaxhighlighter-pre' "
            "data-syntaxhighlighter-params='brush: sql'>SELECT 1</pre>"
        )
        assert 'class="language-sql"' in clean

    def test_pagesection_unwrapped(self):
        clean, _ = _pre("<div class='pageSection'><h2>Heading</h2></div>")
        assert "pageSection" not in clean and "Heading" in clean

    def test_attachments_pagesection_dropped(self):
        # HX-CHROME-ATTACH-SECTION: dropped wholesale BEFORE the generic unwrap
        # would leak the raw link dump (the canonical link_density failure).
        clean, notes = _pre(
            "<div class='pageSection group'><h2 id='attachments' class='pageSectionTitle'>"
            "Attachments:</h2><div class='greybox'>"
            "<a href='attachments/123/456.png'>img.png</a></div></div><p>keep</p>"
        )
        assert "img.png" not in clean and "keep" in clean
        assert notes.macro_counts.get("attachments_section") == 1

    def test_comments_pagesection_dropped(self):
        clean, notes = _pre(
            "<div class='pageSection'><h2 id='comments' class='pageSectionTitle'>Comments</h2>"
            "<div class='comment-body'>hot take</div></div><p>keep</p>"
        )
        assert "hot take" not in clean and "keep" in clean
        assert notes.macro_counts.get("comments_section") == 1

    def test_columnlayout_to_pfi_no_hr(self):
        # HX-LAYOUT: PFI layout/layout-col divs, plain concatenation in
        # document order — NO <hr> separators, no review warning.
        clean, notes = _pre(
            "<div class='columnLayout'>"
            "<div class='cell'><p>Left</p></div>"
            "<div class='cell'><p>Right</p></div></div>"
        )
        assert "Left" in clean and "Right" in clean
        assert "<hr" not in clean
        assert 'class="layout"' in clean and 'class="layout-col"' in clean
        assert not any("flattened" in w for w in notes.warnings)
        assert notes.macro_counts.get("layout") == 2  # one per cell

    def test_merged_cell_table_warns(self):
        _, notes = _pre(
            "<table><tr><td colspan='2'>wide</td></tr><tr><td>a</td><td>b</td></tr></table>"
        )
        assert any("merged cells" in w for w in notes.warnings)
        assert notes.macro_counts.get("merged_table") == 1

    def test_ac_link_page_and_attachment(self):
        clean, notes = _pre(
            "<ac:link><ri:page ri:content-title='Other' ri:space-key='FOO'/>"
            "<ac:link-body>Other Page</ac:link-body></ac:link>"
            "<ac:link><ri:attachment ri:filename='spec.pdf'/>"
            "<ac:link-body>Spec</ac:link-body></ac:link>"
        )
        assert 'href="#"' in clean
        assert "./attachments/spec.pdf" in clean
        assert any("page link" in w for w in notes.warnings)
        assert any("co-locate" in w for w in notes.warnings)

    def test_ac_image_attachment_and_url(self):
        clean, _ = _pre(
            "<ac:image ac:alt='Arch' ac:width='400'><ri:attachment ri:filename='d.png'/></ac:image>"
            "<ac:image><ri:url ri:value='https://x/y.png'/></ac:image>"
        )
        assert "./attachments/d.png" in clean
        assert "https://x/y.png" in clean

    def test_template_vars_and_placeholder(self):
        clean, _ = _pre("<p><at:var at:name='Title'/> <ac:placeholder>type</ac:placeholder></p>")
        assert "{Title}" in clean and "*[type]*" in clean

    def test_leftover_ac_stripped_no_xml(self):
        clean, notes = _pre(
            "<ac:structured-macro ac:name='unknown'><ac:rich-text-body><p>kept</p>"
            "</ac:rich-text-body></ac:structured-macro>"
        )
        assert "ac:" not in clean and "kept" in clean
        assert any("leftover" in w.lower() for w in notes.warnings)


class TestPostprocessFixes:
    def test_nbsp_replaced(self):
        out = h2m.postprocess(
            "a b\n",
            title="T",
            author="",
            source_path=Path("x.html"),
            add_frontmatter=False,
            add_toc=False,
        )
        assert " " not in out
        assert "a b" in out
