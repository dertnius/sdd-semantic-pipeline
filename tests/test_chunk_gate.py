"""Unit tests for the chunk-level hygiene invariant (``quality.check_chunk``).

Fast: pure text analysis, no pandoc or model. The gate is the binding "poisoned →
block, weak → warn" check that runs on a produced :class:`SemanticChunk`'s rendered
embed text — the thing that actually becomes a vector.
"""

from __future__ import annotations

from sdd_pipeline.models import ContentType, SectionType, SemanticChunk
from sdd_pipeline.quality import check_chunk

# Plain prose with no markup shape — the clean baseline.
CLEAN = (
    "The authentication service validates incoming requests against the policy "
    "engine and issues short-lived tokens for downstream callers."
)


def _chunk(
    content: str,
    *,
    content_type: ContentType = ContentType.PARAGRAPH,
    breadcrumb=("Doc", "Section"),
    entities=(),
    tags=(),
    title: str = "",
    language: str | None = None,
    section_type: SectionType = SectionType.CONTENT,
) -> SemanticChunk:
    return SemanticChunk(
        chunk_id="d_s_b_0",
        doc_id="d",
        breadcrumb=list(breadcrumb),
        content=content,
        content_type=content_type,
        language=language,
        section_type=section_type,
        entities=list(entities),
        tags=list(tags),
        depends_on=[],
        exposes=[],
        space="",
        labels=[],
        title=title,
    )


def _poison_rules(chunk: SemanticChunk, **kw) -> set[str]:
    return {i.rule for i in check_chunk(chunk, **kw).poison}


# ── Clean baseline ─────────────────────────────────────────────────────────────


def test_clean_prose_chunk_passes():
    assert check_chunk(_chunk(CLEAN)).is_clean


# ── Markup-shape residue in content → poison ───────────────────────────────────


def test_html_tag_residue_is_poison():
    rpt = check_chunk(_chunk(f"{CLEAN} See <span>here</span>."))
    assert not rpt.is_clean
    assert any("html_residue" in i.rule for i in rpt.poison)


def test_unknown_tag_shape_is_poison():
    # An invariant, not a blocklist: a tag the converter has never seen is caught.
    assert not check_chunk(_chunk(f"{CLEAN} <made-up-macro x=1>body</made-up-macro>")).is_clean


def test_confluence_namespace_token_is_poison():
    assert not check_chunk(_chunk(f"{CLEAN} see ac:image here")).is_clean


def test_confluence_macro_braces_are_poison():
    assert not check_chunk(_chunk(f"{CLEAN} {{panel:title=X}} body")).is_clean


def test_unrendered_entity_is_poison():
    assert not check_chunk(_chunk(f"{CLEAN}&nbsp;trailing")).is_clean


def test_base64_blob_is_poison():
    assert not check_chunk(_chunk(CLEAN + " " + "QUJD" * 80)).is_clean


def test_replacement_char_is_poison():
    assert not check_chunk(_chunk(f"{CLEAN} bad char � here")).is_clean


# ── Intended output is NOT poison ──────────────────────────────────────────────


def test_code_chunk_with_angle_brackets_is_clean():
    # Code legitimately contains <, {, : — the markup-shape check is skipped for it.
    code = "if (x < y) {\n    return cast<T>(value);\n}"
    assert check_chunk(_chunk(code, content_type=ContentType.CODE, language="cpp")).is_clean


def test_table_cell_br_is_clean():
    # The converter emits <br /> in table cells on purpose; br is exempt everywhere.
    table = "| env | endpoints |\n|---|---|\n| prod | read<br />write |"
    assert check_chunk(_chunk(table, content_type=ContentType.TABLE)).is_clean


def test_less_than_in_prose_without_tag_shape_is_clean():
    # "a < b" is not a tag shape (no closing >), so it does not false-positive.
    assert check_chunk(_chunk(f"{CLEAN} note that a < b in all cases.")).is_clean


def test_cli_placeholder_notation_is_clean():
    # CLI/template placeholders like <replace_file> are documentation content, not
    # markup — HTML element names cannot contain underscores.
    placeholder = "Run the tool with <replace_file> and <source_compare_file> set."
    assert check_chunk(_chunk(f"{CLEAN} {placeholder}")).is_clean


def test_bare_form_element_placeholder_is_clean():
    # <output> is a real HTML tag but also placeholder notation; a bare,
    # attribute-less occurrence with no closing tag is treated as content.
    table = "| field | value |\n|---|---|\n| result | <output> |"
    assert check_chunk(_chunk(table, content_type=ContentType.TABLE)).is_clean


def test_tag_with_attributes_is_poison_even_if_unknown():
    # A real markup signal (attributes) on an unknown tag is still caught.
    assert not check_chunk(_chunk(f'{CLEAN} <custom-el data-x="1">v</custom-el>')).is_clean


# ── Residue in the embed-header metadata → poison ──────────────────────────────


def test_residue_in_breadcrumb_is_poison():
    rpt = check_chunk(_chunk(CLEAN, breadcrumb=("Doc", "Section <h1>")))
    assert not rpt.is_clean
    assert any(i.rule.endswith("metadata") for i in rpt.poison)


# ── Positive assertions ────────────────────────────────────────────────────────


def test_empty_content_is_poison():
    assert "chunk_empty" in _poison_rules(_chunk("```\n```"))


# ── Budget breaches warn (visibility), never block — truncation is not certifiable
#    model-free, so it must not hard-block legitimate large content. ──────────────


def test_over_budget_is_a_warning_not_poison():
    rpt = check_chunk(_chunk(CLEAN), embed_char_budget=20, embed_char_hard_cap=10_000)
    assert rpt.is_clean  # weak, not poison
    assert any(i.rule == "chunk_over_budget" and i.severity == "warn" for i in rpt.issues)


def test_over_hard_cap_warns_but_does_not_block():
    rpt = check_chunk(_chunk(CLEAN), embed_char_budget=20, embed_char_hard_cap=40)
    assert rpt.is_clean  # truncation risk is a warning, not poison
    assert any(i.rule == "chunk_truncation_risk" and i.severity == "warn" for i in rpt.issues)
