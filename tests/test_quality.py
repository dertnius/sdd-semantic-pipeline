"""Unit tests for the raw-source markdown quality linter (``quality.py``).

All fast: pure text analysis, no pandoc or model. Most fixtures pad their body
with ``PROSE`` (>200 meaningful chars) so the ``content_density`` stub check does
not fire and mask the rule under test; assertions target a specific rule via
``report.issue_summary`` rather than the exact issue count.
"""

from __future__ import annotations

from sdd_pipeline.quality import check_markdown

# A paragraph with > 200 chars of substantive text — keeps content_density quiet.
PROSE = (
    "The authentication service validates incoming requests against the policy "
    "engine and issues short-lived tokens. It records every decision for audit "
    "and exposes health metrics to the platform monitoring stack continuously."
)


def _rule(md: str, rule: str):
    """Return the issue for *rule* in *md*, or None."""
    return next((i for i in check_markdown("t", md).issues if i.rule == rule), None)


# ── html_leakage ──────────────────────────────────────────────────────────────


def test_html_leakage_warn_for_few_fragments():
    md = "# T\n\n" + PROSE + "\n\nSee <span>here</span> for details.\n"
    issue = _rule(md, "html_leakage")
    assert issue is not None
    assert issue.severity == "warn"


def test_html_leakage_block_for_many_fragments():
    md = "# T\n\n" + PROSE + "\n\n<span>a</span> <div>b</div> <p>c</p> <strong>d</strong>\n"
    issue = _rule(md, "html_leakage")
    assert issue is not None
    assert issue.severity == "block"


def test_br_is_not_html_leakage():
    # The converter emits <br/> in table cells on purpose — must not be flagged.
    md = "# T\n\n" + PROSE + "\n\nLine one<br/>line two<br>line three.\n"
    assert _rule(md, "html_leakage") is None


def test_inline_text_tags_are_html_leakage():
    # u/sup/sub/s/del/code/pre/img pass through pandoc's gfm writer as raw HTML;
    # the lint must see them (blind spot fixed per the conversion-rules doc §9).
    md = (
        "# T\n\n" + PROSE + "\n\n"
        "Area is m<sup>2</sup> and CO<sub>2</sub>; <u>key</u> term, "
        "<s>old</s> <del>gone</del>, <img src='x.png'>\n"
    )
    issue = _rule(md, "html_leakage")
    assert issue is not None
    assert issue.severity == "block"  # > 3 fragments


def test_inline_text_tags_in_fences_are_not_flagged():
    # Code examples documenting these tags must not false-positive (de-fenced scan).
    md = (
        "# T\n\n" + PROSE + "\n\n"
        "```html\n<sup>2</sup> <u>key</u> <pre>raw</pre> <img src='x'>\n```\n"
    )
    assert _rule(md, "html_leakage") is None


def test_clean_prose_has_no_issues():
    md = "# Title\n\n" + PROSE + "\n"
    report = check_markdown("t", md)
    assert report.issues == []
    assert report.is_embeddable is True


# ── confluence_artifacts ──────────────────────────────────────────────────────


def test_confluence_panel_macro_blocks():
    md = "# T\n\n" + PROSE + "\n\nThis {panel} survived conversion.\n"
    issue = _rule(md, "confluence_artifacts")
    assert issue is not None
    assert issue.severity == "block"


def test_confluence_storage_tag_blocks():
    md = "# T\n\n" + PROSE + "\n\nLeftover <ac:structured-macro/> here.\n"
    assert _rule(md, "confluence_artifacts") is not None


# ── code_ratio ────────────────────────────────────────────────────────────────


def test_code_ratio_warns_on_code_dump():
    code = "```python\n" + "value = compute(value)\n" * 40 + "```\n"
    md = "# Dump\n\n" + code
    issue = _rule(md, "code_ratio")
    assert issue is not None
    assert issue.severity == "warn"


# ── link_density ──────────────────────────────────────────────────────────────


def test_link_density_warns_on_toc():
    links = " ".join(f"[Page {i}](http://example/{i})" for i in range(20))
    md = "# Index\n\n" + links + "\n"
    issue = _rule(md, "link_density")
    assert issue is not None
    assert issue.severity == "warn"


# ── content_density ───────────────────────────────────────────────────────────


def test_content_density_blocks_near_empty_stub():
    md = "# Stub\n\nTODO\n"
    issue = _rule(md, "content_density")
    assert issue is not None
    assert issue.severity == "block"


# ── orphaned_headings (redefined: equal-or-higher level only) ──────────────────


def test_opening_with_a_subsection_is_allowed():
    md = "## Section A\n### Subsection\n\n" + PROSE + "\n"
    assert _rule(md, "orphaned_headings") is None


def test_empty_section_before_same_level_heading_is_flagged():
    md = "## Section A\n## Section B\n\n" + PROSE + "\n"
    issue = _rule(md, "orphaned_headings")
    assert issue is not None
    assert issue.severity == "warn"
    assert "line 1" in issue.detail


def test_section_with_only_a_code_block_is_not_orphaned():
    # The code block is blanked in de-fenced text, but it IS content — body
    # presence is judged on the raw source, so this must not be flagged.
    md = "## Config\n\n```yaml\nretention: 7d\npartitions: 12\n```\n\n## Next\n\n" + PROSE + "\n"
    assert _rule(md, "orphaned_headings") is None


# ── fence-awareness regression ────────────────────────────────────────────────


def test_code_examples_do_not_false_positive():
    md = (
        "# Doc\n\n" + PROSE + "\n\n"
        "```html\n<div class='x'>&nbsp;</div>\n```\n\n"
        "~~~\n{panel} <ac:foo/>\n~~~\n\n"
        "Indented example:\n\n"
        "    <span>{note}</span> &nbsp;\n"
    )
    summary = check_markdown("t", md).issue_summary
    assert "html_leakage" not in summary
    assert "confluence_artifacts" not in summary


# ── frontmatter regression (leading frontmatter is expected) ──────────────────


def test_leading_frontmatter_is_clean():
    md = "---\ntitle: Auth Service\nspace: PLAT\n---\n\n# Auth\n\n" + PROSE + "\n"
    assert check_markdown("t", md).issues == []


# ── locality ──────────────────────────────────────────────────────────────────


def test_detail_carries_first_occurrence_line_number():
    md = "# T\n\n" + PROSE + "\n\nBad <div>tag</div> here.\n"  # the <div> is on line 5
    issue = _rule(md, "html_leakage")
    assert issue is not None
    assert "line 5" in issue.detail


# ── report properties ─────────────────────────────────────────────────────────


def test_is_embeddable_false_when_block_issue_present():
    report = check_markdown("t", "# Stub\n\nTODO\n")  # content_density → block
    assert report.is_embeddable is False


def test_is_embeddable_true_for_warn_only():
    links = " ".join(f"[Page {i}](http://example/{i})" for i in range(20))
    report = check_markdown("t", "# Index\n\n" + links + "\n")  # link_density → warn
    assert report.is_embeddable is True
    assert "link_density" in report.issue_summary
