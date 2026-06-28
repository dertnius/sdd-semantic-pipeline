"""Unit tests for the Stage-C panflute filter (``confluence_pf_filter``).

All pandoc-free: panflute element trees are constructed directly and run
through ``run_confluence_filter``, exactly as the module's design intends
(conversion-rules §5). The pandoc round-trip is covered by the slow
end-to-end tests in ``test_html_to_gitlab_md_v3.py``.
"""

from __future__ import annotations

import shutil

import panflute as pf
import pytest

from sdd_pipeline.convert import ConversionNotes
from sdd_pipeline.convert.confluence_pf_filter import (
    LANG_ALIASES,
    pfi_attr,
    run_confluence_filter,
)


def _run(*blocks: pf.Element) -> tuple[pf.Doc, ConversionNotes]:
    notes = ConversionNotes()
    doc = pf.Doc(*blocks)
    run_confluence_filter(doc, notes)
    return doc, notes


def _md(doc: pf.Doc) -> str:
    # The element-tree filtering above is pandoc-free; only this assertion helper
    # (panflute -> gfm) shells out to pandoc. Skip — rather than fail — when the
    # binary is absent, matching the repo's `requires_pandoc` convention so the fast
    # lane stays pandoc-free (the full round-trip lives in the slow e2e tests).
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc not on PATH (panflute -> gfm rendering needs it)")
    return pf.convert_text(doc, input_format="panflute", output_format="gfm")


# ── pfi_attr: the data- prefix gotcha ─────────────────────────────────────────


def test_pfi_attr_checks_both_spellings():
    # pandoc strips data- inconsistently: data-macro → 'macro', but data-title
    # stays 'data-title' (bare title collides with a known HTML attribute).
    el = pf.Div(pf.Para(pf.Str("x")), attributes={"macro": "info", "data-title": "T"})
    assert pfi_attr(el, "macro") == "info"
    assert pfi_attr(el, "title") == "T"
    assert pfi_attr(el, "colour") == ""


# ── PF-ADMONITION ─────────────────────────────────────────────────────────────


def test_admonition_renders_blockquote_with_plain_label():
    doc, notes = _run(
        pf.Div(
            pf.Para(pf.Str("Do"), pf.Space, pf.Emph(pf.Str("not")), pf.Space, pf.Str("retry.")),
            classes=["adm"],
            attributes={"macro": "warning", "data-title": "Hot path"},
        )
    )
    md = _md(doc)
    assert "> **Warning — Hot path:**" in md
    assert "Do *not* retry." in md
    assert notes.macro_counts.get("adm_rendered") == 1


def test_admonition_without_title():
    doc, _ = _run(pf.Div(pf.Para(pf.Str("body")), classes=["adm"], attributes={"macro": "info"}))
    assert "> **Info:**" in _md(doc)


# ── PF-EXPAND ─────────────────────────────────────────────────────────────────


def test_expand_renders_bold_paragraph_not_details():
    doc, notes = _run(
        pf.Div(pf.Para(pf.Str("hidden")), classes=["expand"], attributes={"data-title": "Prereqs"})
    )
    md = _md(doc)
    assert "**Prereqs**" in md and "hidden" in md
    assert "<details>" not in md
    assert notes.macro_counts.get("expand_rendered") == 1


# ── PF-LOZENGE ────────────────────────────────────────────────────────────────


def test_lozenge_renders_bold_text():
    doc, _ = _run(
        pf.Para(
            pf.Span(pf.Str("On track"), classes=["lozenge"], attributes={"data-colour": "success"})
        )
    )
    assert "**On track**" in _md(doc)


# ── PF-LAYOUT-FLATTEN + PF-HYGIENE-UNWRAP ─────────────────────────────────────


def test_layout_nesting_flattens_to_sequential_paragraphs():
    doc, _ = _run(
        pf.Div(
            pf.Div(pf.Para(pf.Str("Left")), classes=["layout-col"]),
            pf.Div(pf.Para(pf.Str("Right")), classes=["layout-col"]),
            classes=["layout"],
        )
    )
    md = _md(doc)
    assert "Left" in md and "Right" in md
    assert "<div" not in md and "-----" not in md


def test_unknown_div_and_span_are_unwrapped():
    doc, _ = _run(
        pf.Div(pf.Para(pf.Str("kept")), classes=["mystery"]),
        pf.Para(pf.Span(pf.Str("inline"), classes=["decor"])),
    )
    md = _md(doc)
    assert "kept" in md and "inline" in md
    assert "<div" not in md and "<span" not in md


# ── PF-CODELANG ───────────────────────────────────────────────────────────────


def test_codelang_normalizes_aliases_and_records_lang():
    doc, notes = _run(
        pf.CodeBlock("x=1", classes=["language-js"]),
        pf.CodeBlock("y=2", classes=["py"]),
        pf.CodeBlock("plain", classes=["none"]),
    )
    blocks = list(doc.content)
    assert blocks[0].classes == ["javascript"]
    assert blocks[1].classes == ["python"]
    assert blocks[2].classes == []
    assert notes.languages == ["javascript", "python"]
    assert LANG_ALIASES["terraform"] == "hcl"  # alias map owned by the filter


# ── PF-INLINE-TEXT ────────────────────────────────────────────────────────────


def test_underline_and_subscript_splice():
    doc, _ = _run(
        pf.Para(pf.Underline(pf.Str("key")), pf.Space, pf.Str("CO"), pf.Subscript(pf.Str("2")))
    )
    md = _md(doc)
    assert "key" in md and "CO2" in md
    assert "<u>" not in md and "<sub>" not in md


def test_superscript_unit_becomes_caret_notation():
    doc, _ = _run(pf.Para(pf.Str("m"), pf.Superscript(pf.Str("2"))))
    assert "m^2" in _md(doc)


def test_superscript_standalone_footnote_marker_dropped():
    doc, notes = _run(pf.Para(pf.Str("see "), pf.Superscript(pf.Str("1"))))
    md = _md(doc)
    assert "^1" not in md
    assert notes.macro_counts.get("sup_footnote_dropped") == 1


def test_strikeout_is_kept():
    doc, _ = _run(pf.Para(pf.Strikeout(pf.Str("old plan"))))
    assert "~~old plan~~" in _md(doc)


# ── PF-JUNK-PARA ──────────────────────────────────────────────────────────────


def test_junk_para_dropped_but_image_para_survives():
    doc, notes = _run(
        pf.Para(pf.Str("\\")),
        pf.Para(pf.Image(url="img.png")),
    )
    md = _md(doc)
    assert "img.png" in md
    assert "\\" not in md.replace("![](img.png)", "")
    assert notes.macro_counts.get("junk_para_dropped") == 1


# ── PF-DROP (data-URI images) ─────────────────────────────────────────────────


def test_data_uri_image_reduced_to_alt_text():
    doc, notes = _run(
        pf.Para(
            pf.Image(pf.Str("auth"), pf.Space, pf.Str("flow"), url="data:image/png;base64,AAAA")
        )
    )
    md = _md(doc)
    assert "auth flow" in md
    assert "data:" not in md
    assert notes.macro_counts.get("data_uri_image") == 1


# ── PF-TABLE-SIMPLIFY + PF-TABLE-PIPE-IN-CODE ─────────────────────────────────


def _cell(*blocks: pf.Element, **kw) -> pf.TableCell:
    return pf.TableCell(*blocks, **kw)


def _table(
    rows: list[pf.TableRow],
    n_cols: int,
    head_rows: list[pf.TableRow] | None = None,
    row_head: int = 0,
) -> pf.Table:
    return pf.Table(
        pf.TableBody(*rows, row_head_columns=row_head),
        head=pf.TableHead(*(head_rows or [])),
        colspec=[("AlignDefault", "ColWidthDefault")] * n_cols,
    )


def test_list_in_cell_flattens_to_joined_inline_run():
    table = _table(
        [
            pf.TableRow(
                _cell(pf.Plain(pf.Str("a"))),
                _cell(
                    pf.BulletList(
                        pf.ListItem(pf.Plain(pf.Str("item1"))),
                        pf.ListItem(pf.Plain(pf.Str("item2"))),
                    )
                ),
            )
        ],
        n_cols=2,
    )
    doc, _ = _run(table)
    md = _md(doc)
    assert "item1; item2" in md
    assert "<table" not in md


def test_spans_reset_and_rows_padded():
    table = _table(
        [pf.TableRow(_cell(pf.Plain(pf.Str("wide")), colspan=2))],
        n_cols=2,
    )
    doc, notes = _run(table)
    tbl = next(b for b in doc.content if isinstance(b, pf.Table))
    body = next(iter(tbl.content))
    row = next(iter(body.content))
    cells = list(row.content)
    assert len(cells) == 2
    assert cells[0].colspan == 1
    assert notes.macro_counts.get("merged_table_simplified") == 1


def test_row_header_table_bolds_first_column():
    table = _table(
        [
            pf.TableRow(_cell(pf.Plain(pf.Str("Owner"))), _cell(pf.Plain(pf.Str("Jane")))),
            pf.TableRow(_cell(pf.Plain(pf.Str("Status"))), _cell(pf.Plain(pf.Str("Active")))),
        ],
        n_cols=2,
        row_head=1,
    )
    doc, notes = _run(table)
    md = _md(doc)
    assert "**Owner**" in md and "**Status**" in md
    assert notes.macro_counts.get("row_header_table") == 1
    assert any("Row-header table" in w for w in notes.warnings)


def test_pipe_in_code_escaped_inside_cells_only():
    table = _table(
        [pf.TableRow(_cell(pf.Plain(pf.Code("a | b"))))],
        n_cols=1,
    )
    doc, notes = _run(table, pf.Para(pf.Code("x | y")))
    md = _md(doc)
    assert "a \\| b" in md  # escaped inside the table cell
    assert "`x | y`" in md  # untouched outside tables
    assert notes.macro_counts.get("pipe_in_code") == 1


def _body_with_head(
    head_rows: list[pf.TableRow], body_rows: list[pf.TableRow], n_cols: int
) -> pf.Table:
    """A Table whose first TableBody carries *intermediate* header rows — where
    pandoc parks tiered/rowspan ``th`` rows (not in ``Table.head``)."""
    return pf.Table(
        pf.TableBody(*body_rows, head=head_rows),
        head=pf.TableHead(),
        colspec=[("AlignDefault", "ColWidthDefault")] * n_cols,
    )


def test_tiered_intermediate_header_rows_folded_no_raw_table():
    # Pandoc parks tiered/rowspan <th> rows in TableBody.head; GFM cannot render
    # >1 head row or a spanning header cell, so the writer would dump the whole
    # table as raw HTML (a Tier-1 drop). The filter must fold them into the body.
    table = _body_with_head(
        head_rows=[
            pf.TableRow(
                _cell(pf.Plain(pf.Str("Environment")), rowspan=2),
                _cell(pf.Plain(pf.Str("Endpoints")), colspan=2),
            ),
            pf.TableRow(_cell(pf.Plain(pf.Str("Read"))), _cell(pf.Plain(pf.Str("Write")))),
        ],
        body_rows=[
            pf.TableRow(
                _cell(pf.Plain(pf.Str("Prod"))),
                _cell(pf.Plain(pf.Str("r.example"))),
                _cell(pf.Plain(pf.Str("w.example"))),
            )
        ],
        n_cols=3,
    )
    doc, notes = _run(table)
    md = _md(doc)
    assert "<table" not in md and "&#10;" not in md  # no raw-HTML fallback
    for txt in ("Environment", "Endpoints", "Read", "Write", "Prod"):
        assert txt in md  # all header content preserved, folded into the body
    tbl = next(b for b in doc.content if isinstance(b, pf.Table))
    assert all(len(b.head) == 0 for b in tbl.content)  # no intermediate head rows left
    assert notes.macro_counts.get("multi_header_collapsed") == 1


def test_lone_spanless_intermediate_header_not_collapsed():
    # A single span-free intermediate header row renders fine on its own; folding
    # it (and warning) would spray over every real th-in-tbody table. Leave it.
    table = _body_with_head(
        head_rows=[
            pf.TableRow(_cell(pf.Plain(pf.Str("Env"))), _cell(pf.Plain(pf.Str("Endpoint"))))
        ],
        body_rows=[
            pf.TableRow(_cell(pf.Plain(pf.Str("Prod"))), _cell(pf.Plain(pf.Str("r.example"))))
        ],
        n_cols=2,
    )
    doc, notes = _run(table)
    md = _md(doc)
    assert "<table" not in md
    for txt in ("Env", "Endpoint", "Prod"):
        assert txt in md
    assert notes.macro_counts.get("multi_header_collapsed") is None
