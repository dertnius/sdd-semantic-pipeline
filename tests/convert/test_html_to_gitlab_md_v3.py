"""v3 conversion-rules conformance tests for ``html_to_gitlab_md``.

Covers the rendered-HTML scope of ``docs/confluence-conversion-rules.md``:
chrome harvesting, the PFI contract, the new HX-* handlers, fence-aware
Stage-D fixes, YAML-safe frontmatter, the ``--toc`` flip, and the real-corpus
quality gate. Preprocess/postprocess tests are pandoc-free; the ``.tmp_dc``
regression is slow-marked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sdd_pipeline.cli import app
from sdd_pipeline.convert import html_to_gitlab_md as h2m
from sdd_pipeline.quality import check_markdown


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


def _pre(body_html: str) -> tuple[str, h2m.ConversionNotes]:
    notes = h2m.ConversionNotes()
    clean = h2m.preprocess(
        f"<html><body><main>{body_html}</main></body></html>", None, False, notes
    )
    return clean, notes


def _pre_full(page_html: str) -> tuple[str, h2m.ConversionNotes]:
    """Preprocess a FULL page (chrome outside the content root)."""
    notes = h2m.ConversionNotes()
    clean = h2m.preprocess(page_html, None, False, notes)
    return clean, notes


# ── Chrome harvest (HX-CHROME-TITLE / -METADATA, pre-root) ────────────────────


class TestHarvestAndChrome:
    PAGE = (
        "<html><head><title>OPS : Deploy Guide - Confluence</title></head><body>"
        "<div id='page'><div id='main-header'>"
        "<h1 id='title-heading' class='pagetitle'><span id='title-text'>OPS : Deploy Guide</span></h1>"
        "</div><div id='content' class='view'>"
        "<div class='page-metadata'>Created by <span class='author'>Jane Smith</span>, "
        "last modified on Mar 02, 2024</div>"
        "<div id='main-content' class='wiki-content'><p>Body prose.</p>"
        "<img src='attachments/123/456.png' alt='diagram'></div>"
        "</div></div></body></html>"
    )

    def test_title_and_space_harvested_from_title_text(self):
        _, notes = _pre_full(self.PAGE)
        assert notes.metadata["title"] == "Deploy Guide"
        assert notes.metadata["space"] == "OPS"

    def test_author_date_and_page_id_harvested(self):
        _, notes = _pre_full(self.PAGE)
        assert notes.metadata["author"] == "Jane Smith"
        assert notes.metadata["date"] == "Mar 02, 2024"
        assert notes.metadata["page_id"] == "123"

    def test_head_title_fallback(self):
        page = (
            "<html><head><title>OPS : Deploy Guide</title></head>"
            "<body><main><p>x</p></main></body></html>"
        )
        _, notes = _pre_full(page)
        assert notes.metadata["title"] == "Deploy Guide"
        assert notes.metadata["space"] == "OPS"

    def test_chrome_absent_from_clean_html(self):
        clean, _ = _pre_full(self.PAGE)
        assert "title-text" not in clean and "page-metadata" not in clean
        assert "Body prose." in clean


# ── PFI contract + new HX handlers (preprocess-only) ──────────────────────────


class TestPfiPreprocess:
    def test_pfi_elements_survive_unwrap_and_scrub(self):
        # The §1 PFI contract: adm/expand/lozenge/layout carriers keep their
        # class + data-* attributes through the blanket unwrap and the scrub.
        clean, _ = _pre(
            "<div class='confluence-information-macro "
            "confluence-information-macro-warning'><p class='title'>Hot path</p>"
            "<div class='confluence-information-macro-body'><p>Do not retry.</p></div></div>"
        )
        assert 'class="adm"' in clean
        assert 'data-macro="warning"' in clean
        assert 'data-title="Hot path"' in clean

    def test_strike_span_becomes_del(self):
        clean, _ = _pre("<p><span style='text-decoration: line-through;'>old plan</span></p>")
        assert "<del>old plan</del>" in clean

    def test_small_big_unwrapped_and_time_to_iso(self):
        clean, _ = _pre("<p><small>fine print</small> due <time datetime='2019-01-01'></time></p>")
        assert "fine print" in clean and "<small>" not in clean
        assert "2019-01-01" in clean and "<time" not in clean

    def test_expand_has_no_details(self):
        clean, notes = _pre(
            "<div class='expand-container' id='expander-1'>"
            "<div class='expand-control'><span class='expand-control-text'>Click here</span></div>"
            "<div class='expand-content'><p>the procedure</p></div></div>"
        )
        assert "<details>" not in clean
        assert 'class="expand"' in clean and 'data-title="Click here"' in clean
        assert "the procedure" in clean
        assert notes.macro_counts.get("expand") == 1

    def test_mention_link_becomes_plain_name(self):
        clean, notes = _pre(
            "<p>ping <a class='confluence-userlink user-mention' "
            "href='/display/~jdoe' data-username='jdoe'>Jane Doe</a></p>"
        )
        assert "Jane Doe" in clean
        assert "userlink" not in clean and "/display/~jdoe" not in clean
        assert notes.macro_counts.get("mention") == 1

    def test_jira_span_to_key_summary_status(self):
        clean, notes = _pre(
            "<p><span class='jira-issue resolved' data-jira-key='JENKINS-123'>"
            "<a class='jira-issue-key' href='https://issues.example/browse/JENKINS-123?src=confmacro'>"
            "JENKINS-123</a><span class='summary'>Fix agent leak</span>"
            "<span class='aui-lozenge'>Done</span></span></p>"
        )
        assert 'href="https://issues.example/browse/JENKINS-123"' in clean
        assert "Fix agent leak" in clean and "(Done)" in clean and "(resolved)" in clean
        assert "src=confmacro" not in clean
        assert notes.macro_counts.get("jira") == 1

    def test_profile_macro_to_name(self):
        clean, notes = _pre(
            "<div class='profile-macro'><div class='vcard'>"
            "<a class='userLogoLink' data-username='jdoe'>"
            "<img class='userLogo logo' alt='User icon: Jane Doe'></a></div></div>"
        )
        assert "Jane Doe" in clean and "profile-macro" not in clean
        assert notes.macro_counts.get("profile") == 1

    def test_gallery_to_filename_line(self):
        clean, notes = _pre(
            "<table class='gallery'><tr>"
            "<td><span class='confluence-embedded-file-wrapper'>"
            "<img class='confluence-embedded-image' src='attachments/1/2.png' "
            "data-linked-resource-default-alias='a.png'></span></td>"
            "<td><img class='confluence-embedded-image' src='attachments/1/3.png' "
            "data-linked-resource-default-alias='b.png'></td></tr></table>"
        )
        assert "Image gallery (2 images): a.png, b.png" in clean
        assert "<table" not in clean
        assert notes.macro_counts.get("gallery") == 1

    def test_viewfile_link_with_nice_type(self):
        clean, notes = _pre(
            "<span class='confluence-embedded-file-wrapper'>"
            "<a class='confluence-embedded-file' href='attachments/98/102.pdf' "
            "data-nice-type='PDF' data-linked-resource-default-alias='sample.pdf'>x</a></span>"
        )
        assert ">sample.pdf</a>" in clean and "(PDF)" in clean
        assert notes.macro_counts.get("viewfile") == 1

    def test_embedded_image_alias_copied_to_alt(self):
        clean, _ = _pre(
            "<span class='confluence-embedded-file-wrapper'>"
            "<img class='confluence-embedded-image' src='attachments/123/456.png' "
            "data-linked-resource-default-alias='network-topology.png'></span>"
        )
        assert 'alt="network-topology.png"' in clean

    def test_data_uri_image_reduced_to_alt(self):
        clean, notes = _pre("<p><img src='data:image/png;base64,AAAA' alt='auth flow'></p>")
        assert "auth flow" in clean and "data:" not in clean
        assert notes.macro_counts.get("data_uri_image") == 1

    def test_svg_figure_to_caption(self):
        clean, notes = _pre(
            "<figure><svg><text>garbled</text></svg><figcaption>Topology</figcaption></figure>"
        )
        assert "<em>Topology</em>" in clean
        assert "<svg" not in clean and "garbled" not in clean
        assert notes.macro_counts.get("diagram") == 1

    def test_samepage_link_flattened_heading_id_gone(self):
        clean, notes = _pre("<h2 id='Page-Setup'>Setup</h2><p><a href='#Page-Setup'>Setup</a></p>")
        assert "href" not in clean
        assert "Page-Setup" not in clean
        assert "Setup" in clean
        assert notes.macro_counts.get("anchor_link_flattened") == 1

    def test_noformat_panel_no_language_with_title(self):
        clean, _ = _pre(
            "<div class='preformatted panel'><div class='preformattedHeader panelHeader'>"
            "<b>Raw dump</b></div><div class='preformattedContent panelContent'>"
            "<pre>SELECT looks like sql but is not</pre></div></div>"
        )
        assert "language-" not in clean
        assert "<strong>Raw dump</strong>" in clean
        assert "SELECT looks like sql" in clean

    def test_bare_pre_gets_no_invented_language(self):
        # HX-PRE: pasted text must NOT be language-guessed (untrusted lang: tags).
        clean, _ = _pre("<pre>CREATE TABLE foo (id INT);</pre>")
        assert "language-" not in clean
        assert "CREATE TABLE foo" in clean

    def test_code_panel_title_to_bold_paragraph(self):
        clean, _ = _pre(
            "<div class='code panel pdl'><div class='codeHeader panelHeader pdl'>"
            "<b>install.sh</b></div><div class='codeContent panelContent pdl'>"
            "<pre class='syntaxhighlighter-pre' data-syntaxhighlighter-params='brush: bash'>"
            "echo hi</pre></div></div>"
        )
        assert "<strong>install.sh</strong>" in clean
        assert 'class="language-bash"' in clean

    def test_brush_java_distrusted_when_content_disagrees(self):
        clean, _ = _pre(
            "<div class='code panel'><pre class='syntaxhighlighter-pre' "
            "data-syntaxhighlighter-params='brush: java'>#!/bin/sh\necho hi</pre></div>"
        )
        assert 'class="language-bash"' in clean

    def test_task_list_becomes_checkbox_inputs(self):
        clean, notes = _pre(
            "<ul class='inline-task-list' data-inline-tasks-content-id='1'>"
            "<li data-inline-task-id='1' class='checked'>ship it</li>"
            "<li data-inline-task-id='2'>write docs</li></ul>"
        )
        assert clean.count('type="checkbox"') == 2
        assert 'checked=""' in clean or "checked" in clean
        assert notes.macro_counts.get("task") == 2

    def test_client_side_toc_removed(self):
        clean, _ = _pre("<div class='client-side-toc-macro'><ul><li>nav</li></ul></div><p>keep</p>")
        assert "nav" not in clean and "keep" in clean


# ── Stage D: fence-awareness + YAML-safe frontmatter ──────────────────────────


class TestPostprocessV3:
    def _post(self, md: str, **kw) -> str:
        defaults: dict = {
            "title": "T",
            "author": "",
            "source_path": Path("x.html"),
            "add_frontmatter": False,
            "add_toc": False,
        }
        defaults.update(kw)
        return h2m.postprocess(md, **defaults)

    def test_escapes_preserved_inside_fences(self):
        md = "prose \\*\\*bold\\*\\*\n\n```\nliteral \\* stays\n\n\n\nblank run stays\n```\n"
        out = self._post(md)
        assert "prose **bold**" in out
        assert "literal \\* stays" in out
        assert "\n\n\n\nblank run stays" in out  # MD-BLANKLINES skipped in fences

    def test_blank_lines_collapsed_in_prose(self):
        out = self._post("a\n\n\n\n\nb\n")
        assert "a\n\nb" in out

    def test_angle_escapes_are_kept(self):
        # The angle-bracket unescape was DELETED: List\<String\> must stay
        # escaped or GitLab swallows it as an unknown HTML tag.
        out = self._post("Use List\\<String\\> here\n")
        assert "List\\<String\\>" in out

    def test_yaml_frontmatter_roundtrips_with_quotes(self):
        out = self._post(
            "# B\n",
            add_frontmatter=True,
            title='OPS : Deploy "v2"',
            author="Jane",
            date="Mar 02, 2024",
            page_id="123",
        )
        fm_text = out.split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm["title"] == 'OPS : Deploy "v2"'
        assert fm["author"] == "Jane"  # singular key — what structural reads
        assert fm["date"] == "Mar 02, 2024"
        assert fm["page_id"] == 123 or fm["page_id"] == "123"
        assert "authors" not in fm

    def test_toc_off_by_default_on_when_asked(self):
        no_toc = self._post("# A\n", add_frontmatter=False)
        with_toc = self._post("# A\n", add_frontmatter=False, add_toc=True)
        assert "[[_TOC_]]" not in no_toc
        assert "[[_TOC_]]" in with_toc


# ── CLI: --toc flip ───────────────────────────────────────────────────────────


class TestCliTocFlag:
    def _fake(self, monkeypatch, captured: dict):
        # The `convert` CLI imports these from the `sdd_pipeline.convert` package.
        monkeypatch.setattr("sdd_pipeline.convert.resolve_pandoc", lambda _p=None: "pandoc")

        def fake_convert_file(src, output=None, **kw):
            captured.update(kw)
            src = Path(src)
            out = Path(output) if output is not None else src.with_suffix(".md")
            metrics = dict.fromkeys(
                ("sections", "pictures", "code_snippets", "lists", "tables", "urls"), 0
            )
            notes = {
                "warnings": [],
                "errors": [],
                "macro_counts": {},
                "languages": [],
                "metadata": {},
            }
            return out, "# md\n", metrics, notes

        monkeypatch.setattr("sdd_pipeline.convert.convert_file", fake_convert_file)

    def test_toc_default_off_and_opt_in(self, tmp_path: Path, monkeypatch):
        captured: dict = {}
        self._fake(monkeypatch, captured)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.html").write_text("<p>x</p>", encoding="utf-8")
        report = tmp_path / "r.json"

        runner.invoke(app, ["convert", str(docs), "--report", str(report)])
        assert captured["add_toc"] is False

        runner.invoke(app, ["convert", str(docs), "--toc", "--report", str(report)])
        assert captured["add_toc"] is True


# ── Real-corpus regression gate (slow) ────────────────────────────────────────

_TMP_DC = Path(__file__).resolve().parents[2] / ".tmp_dc"


@requires_pandoc
@pytest.mark.slow
class TestTmpDcCorpus:
    def test_real_exports_pass_quality_gate(self):
        if not _TMP_DC.is_dir():
            pytest.skip(".tmp_dc corpus not present")
        html_files = sorted(_TMP_DC.glob("*.html"))
        assert len(html_files) >= 4, "expected the real-export corpus at top level"
        for src in html_files:
            _, md, _, _notes = h2m.convert_file(src, write=False)
            report = check_markdown(src.name, md)
            blocks = [i for i in report.issues if i.severity == "block"]
            assert not blocks, f"{src.name}: {[(i.rule, i.detail) for i in blocks]}"
            leak_rules = {i.rule for i in report.issues}
            assert "html_leakage" not in leak_rules, f"{src.name} leaked HTML"
            assert "confluence_artifacts" not in leak_rules, f"{src.name} leaked macros"


# ── Committed example corpus (the regression net; runs in CI) ──────────────────

_EXAMPLES = Path(__file__).resolve().parent / "examples"


@requires_pandoc
@pytest.mark.slow
class TestConvertExamplesCorpus:
    """Committed ``tests/convert/examples`` fixtures — the regression net for the
    three-tier quality bar and the multi-header-table fix. Unlike the gitignored
    ``.tmp_dc`` gate above, these ship with the repo and run on a clean checkout.
    """

    def test_examples_pass_quality_gate(self):
        # Rendered-HTML exports only — storage-format fixtures (``*.storage.html``)
        # are refused at the front door (see test below), not quality-gated here.
        html_files = sorted(
            p for p in _EXAMPLES.glob("*.html") if not p.name.endswith(".storage.html")
        )
        assert len(html_files) >= 2, "expected the committed rendered example corpus"
        for src in html_files:
            _, md, _, _notes = h2m.convert_file(src, write=False)
            report = check_markdown(src.name, md)
            blocks = [(i.rule, i.detail) for i in report.issues if i.severity == "block"]
            assert not blocks, f"{src.name}: {blocks}"
            # Tier-3: no raw HTML / macro residue leaks (``<br />`` in cells is allowed).
            for residue in ("<table", "<div", "<span", "<ac:", "<ri:", "<at:", "[[_TOC_]]"):
                assert residue not in md, f"{src.name} leaked {residue!r}"

    def test_storage_format_example_is_refused_at_the_door(self):
        """P0.1 front door: storage-format input is rejected, not silently mangled."""
        src = _EXAMPLES / "order-management-sad.storage.html"
        with pytest.raises(h2m.ConversionError, match="storage format"):
            h2m.convert_file(src, write=False)

    def test_multiheader_table_does_not_leak_raw_html(self):
        """Regression for the rowspan/tiered-``th`` raw-``<table>`` leak (Tier-1):
        the whole table used to be dumped as raw HTML and dropped downstream."""
        src = _EXAMPLES / "adversarial-edge-cases.html"
        _, md, _, notes = h2m.convert_file(src, write=False)
        assert "<table" not in md and "&#10;" not in md
        # Every tiered-header cell survives, folded into the body as data rows.
        for txt in ("Environment", "Endpoints", "Read", "Write", "Prod", "Stage"):
            assert txt in md, f"lost tiered-header content: {txt!r}"
        assert notes["macro_counts"].get("multi_header_collapsed", 0) >= 1


@requires_pandoc
@pytest.mark.slow
class TestEndToEndChunkHygiene:
    """P2.1 — the non-skippable proof that the committed rendered fixtures survive
    the *whole* model-free chain (HTML → convert → chunk → Arm-1 hygiene gate)
    cleanly. Model-free: ``process_file`` parses/enriches/chunks and ``gate_chunks``
    runs the invariant — neither touches an embedder, so no model is downloaded."""

    def test_rendered_examples_produce_clean_chunks(self, tmp_path: Path):
        from sdd_pipeline.config import PipelineConfig
        from sdd_pipeline.pipeline import SemanticPipeline

        pipe = SemanticPipeline(config=PipelineConfig(embedding_model="all-MiniLM-L6-v2"))
        examples = sorted(
            p for p in _EXAMPLES.glob("*.html") if not p.name.endswith(".storage.html")
        )
        assert examples, "expected committed rendered example fixtures"
        for src in examples:
            md_path = tmp_path / f"{src.stem}.md"
            h2m.convert_file(src, md_path, write=True)
            chunks = pipe.process_file(md_path)
            assert chunks, f"{src.name} produced no chunks"
            poison = [
                (r.chunk_id, i.rule, i.detail) for r in pipe.gate_chunks(chunks) for i in r.poison
            ]
            assert not poison, f"{src.name} produced poisoned chunks: {poison}"
