"""Tests for sdd_pipeline.structural."""

from __future__ import annotations

from sdd_pipeline.chunking import chunk_document
from sdd_pipeline.models import ContentType
from sdd_pipeline.structural import (
    _short_hash,
    build_structural_model,
)


def _ast_titled(blocks: list[dict], title: str | None = "My Page") -> dict:
    meta: dict = {}
    if title is not None:
        meta["title"] = {"t": "MetaInlines", "c": [{"t": "Str", "c": title}]}
    return {"pandoc-api-version": [1, 23, 1], "meta": meta, "blocks": blocks}


def _para(text: str) -> dict:
    return {"t": "Para", "c": [{"t": "Str", "c": text}]}


def _header1(title: str) -> dict:
    return {"t": "Header", "c": [1, [title.lower(), [], []], [{"t": "Str", "c": title}]]}


def _deflist(items: list[tuple[str, str]]) -> dict:
    """A pandoc DefinitionList AST node from (term, definition) string pairs."""
    content = [
        [[{"t": "Str", "c": term}], [[{"t": "Para", "c": [{"t": "Str", "c": definition}]}]]]
        for term, definition in items
    ]
    return {"t": "DefinitionList", "c": content}


class TestDefinitionList:
    def test_definition_list_recovered_as_definition_block(self):
        blocks = [
            _header1("Glossary"),
            _deflist(
                [("API", "Application Programming Interface"), ("DTO", "Data Transfer Object")]
            ),
        ]
        doc = build_structural_model(_ast_titled(blocks), doc_id="d1")
        section = doc.root_sections[0]
        defs = [b for b in section.blocks if b.content_type == ContentType.DEFINITION]
        assert len(defs) == 1
        assert "API — Application Programming Interface" in defs[0].text
        assert "DTO — Data Transfer Object" in defs[0].text

    def test_definition_block_survives_chunking_and_gate(self):
        from sdd_pipeline.quality import check_chunk

        blocks = [_header1("Glossary"), _deflist([("API", "Application Programming Interface")])]
        doc = build_structural_model(_ast_titled(blocks), doc_id="d2")
        chunks = chunk_document(doc)
        def_chunks = [c for c in chunks if c.content_type == ContentType.DEFINITION]
        assert def_chunks
        # Plain "term — definition" carries no markup shape → not poisoned.
        assert check_chunk(def_chunks[0]).is_clean


class TestShortHash:
    def test_returns_8_chars(self):
        assert len(_short_hash("a", "b", "c")) == 8

    def test_deterministic(self):
        assert _short_hash("x", "y") == _short_hash("x", "y")

    def test_different_inputs_different_hashes(self):
        assert _short_hash("a") != _short_hash("b")


class TestBuildStructuralModel:
    def test_doc_id_stored(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="my-doc")
        assert doc.doc_id == "my-doc"

    def test_title_extracted_from_meta(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        assert doc.metadata.title == "Auth Service Design"

    def test_space_extracted_from_meta(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        assert doc.metadata.space == "PLATFORM"

    def test_root_sections_non_empty(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        assert len(doc.root_sections) >= 1

    def test_root_section_is_h1(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        assert doc.root_sections[0].level == 1

    def test_h2_sections_are_subsections_of_h1(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        root = doc.root_sections[0]
        assert len(root.subsections) > 0
        for sub in root.subsections:
            assert sub.level == 2

    def test_breadcrumbs_include_parent(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        root = doc.root_sections[0]
        for sub in root.subsections:
            assert root.title in sub.breadcrumb
            assert sub.title == sub.breadcrumb[-1]

    def test_code_blocks_extracted_with_language(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        all_blocks = [b for s in doc.iter_sections() for b in s.blocks]
        code_blocks = [b for b in all_blocks if b.content_type == ContentType.CODE]
        assert len(code_blocks) >= 1
        assert any(b.language == "json" for b in code_blocks)

    def test_paragraphs_extracted(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        all_blocks = [b for s in doc.iter_sections() for b in s.blocks]
        paras = [b for b in all_blocks if b.content_type == ContentType.PARAGRAPH]
        assert len(paras) >= 1

    def test_source_path_stored(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1", source_path="/docs/page.md")
        assert doc.source_path == "/docs/page.md"

    def test_empty_blocks_list(self):
        empty = {"pandoc-api-version": [1, 23, 1], "meta": {}, "blocks": []}
        doc = build_structural_model(empty, doc_id="empty")
        assert doc.root_sections == []

    def test_empty_meta(self):
        ast = {
            "pandoc-api-version": [1, 23, 1],
            "meta": {},
            "blocks": [{"t": "Header", "c": [1, ["h1", [], []], [{"t": "Str", "c": "Title"}]]}],
        }
        doc = build_structural_model(ast, doc_id="no-meta")
        assert doc.metadata.title == ""  # no meta, no title
        assert len(doc.root_sections) == 1

    def test_block_ids_unique(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        ids = [b.block_id for s in doc.iter_sections() for b in s.blocks]
        assert len(ids) == len(set(ids))

    def test_section_ids_unique(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        ids = [s.section_id for s in doc.iter_sections()]
        assert len(ids) == len(set(ids))

    def test_section_titles_non_empty(self, sample_ast):
        doc = build_structural_model(sample_ast, doc_id="t1")
        for s in doc.iter_sections():
            assert s.title.strip(), f"Section {s.section_id!r} has empty title"

    def test_list_block_extracted(self):
        ast = {
            "pandoc-api-version": [1, 23, 1],
            "meta": {},
            "blocks": [
                {"t": "Header", "c": [1, ["h1", [], []], [{"t": "Str", "c": "Root"}]]},
                {
                    "t": "BulletList",
                    "c": [
                        [{"t": "Para", "c": [{"t": "Str", "c": "Item one"}]}],
                        [{"t": "Para", "c": [{"t": "Str", "c": "Item two"}]}],
                    ],
                },
            ],
        }
        doc = build_structural_model(ast, doc_id="list-test")
        all_blocks = [b for s in doc.iter_sections() for b in s.blocks]
        list_blocks = [b for b in all_blocks if b.content_type == ContentType.LIST]
        assert len(list_blocks) == 1
        assert "Item one" in list_blocks[0].text


class TestPreambleSynthesis:
    """P0.2 — content before the first heading (or in a heading-less doc) must
    not be silently dropped; it is attached to a synthesized title-derived root
    section so the page still produces chunks."""

    def test_preamble_before_first_heading_is_kept(self):
        ast = _ast_titled(
            [_para("Intro paragraph before any heading."), _header1("Section"), _para("Body.")],
            title="My Page",
        )
        doc = build_structural_model(ast, doc_id="t")
        # First root section is synthesized from the page title and holds the intro.
        assert doc.root_sections[0].title == "My Page"
        assert any("Intro paragraph" in b.text for b in doc.root_sections[0].blocks)
        # The real heading still becomes its own section.
        assert "Section" in [s.title for s in doc.root_sections]

    def test_heading_less_doc_yields_one_section_and_chunks(self):
        ast = _ast_titled(
            [_para("Only paragraphs here, no headings at all."), _para("A second paragraph.")],
            title="Flat Doc",
        )
        doc = build_structural_model(ast, doc_id="t")
        assert len(doc.root_sections) == 1
        assert doc.root_sections[0].title == "Flat Doc"
        assert len(doc.root_sections[0].blocks) == 2
        # The point of the fix: a heading-less page is no longer 0 chunks.
        assert chunk_document(doc), "heading-less doc produced no chunks"

    def test_preamble_without_title_falls_back_to_document(self):
        ast = _ast_titled([_para("Body with no title and no heading.")], title=None)
        doc = build_structural_model(ast, doc_id="t")
        assert doc.root_sections[0].title == "Document"


# ── Structure-preserving serialization ───────────────────────────────────────


def _h1(title: str) -> dict:
    return {"t": "Header", "c": [1, ["h1", [], []], [{"t": "Str", "c": title}]]}


def _doc(*blocks: dict) -> dict:
    return {"pandoc-api-version": [1, 23, 1], "meta": {}, "blocks": list(blocks)}


def _first_block(ast: dict, content_type: ContentType):
    doc = build_structural_model(ast, doc_id="t")
    blocks = [b for s in doc.iter_sections() for b in s.blocks if b.content_type == content_type]
    return blocks[0]


class TestSemanticSerialization:
    def test_para_link_preserves_host(self):
        link = {
            "t": "Link",
            "c": [
                ["", [], []],
                [{"t": "Str", "c": "VSCode"}],
                ["https://code.visualstudio.com/docs", ""],
            ],
        }
        ast = _doc(
            _h1("Root"),
            {
                "t": "Para",
                "c": [
                    {"t": "Str", "c": "Install"},
                    {"t": "Space"},
                    link,
                ],
            },
        )
        block = _first_block(ast, ContentType.PARAGRAPH)
        assert "VSCode" in block.text
        assert "code.visualstudio.com" in block.text

    def test_relative_link_keeps_path(self):
        link = {
            "t": "Link",
            "c": [
                ["", [], []],
                [{"t": "Str", "c": "Bootstrapping"}],
                ["/confluence/display/IMPALA/Bootstrapping", ""],
            ],
        }
        ast = _doc(_h1("Root"), {"t": "Para", "c": [link]})
        block = _first_block(ast, ContentType.PARAGRAPH)
        assert "/confluence/display/IMPALA/Bootstrapping" in block.text

    def test_inline_code_keeps_backticks(self):
        code = {"t": "Code", "c": [["", [], []], "AuthService"]}
        ast = _doc(
            _h1("Root"),
            {
                "t": "Para",
                "c": [
                    {"t": "Str", "c": "Call"},
                    {"t": "Space"},
                    code,
                ],
            },
        )
        block = _first_block(ast, ContentType.PARAGRAPH)
        assert "`AuthService`" in block.text

    def test_ordered_list_preserves_numbering(self):
        ast = _doc(
            _h1("Root"),
            {
                "t": "OrderedList",
                "c": [
                    [1, {"t": "Decimal"}, {"t": "Period"}],
                    [
                        [{"t": "Para", "c": [{"t": "Str", "c": "First"}]}],
                        [{"t": "Para", "c": [{"t": "Str", "c": "Second"}]}],
                    ],
                ],
            },
        )
        block = _first_block(ast, ContentType.LIST)
        assert "1. First" in block.text
        assert "2. Second" in block.text
        assert "- First" not in block.text

    def test_nested_list_indented(self):
        inner = {
            "t": "BulletList",
            "c": [[{"t": "Para", "c": [{"t": "Str", "c": "Child"}]}]],
        }
        ast = _doc(
            _h1("Root"),
            {
                "t": "OrderedList",
                "c": [
                    [1, {"t": "Decimal"}, {"t": "Period"}],
                    [
                        [{"t": "Para", "c": [{"t": "Str", "c": "Parent"}]}, inner],
                    ],
                ],
            },
        )
        block = _first_block(ast, ContentType.LIST)
        assert "1. Parent" in block.text
        assert "  - Child" in block.text

    def test_codeblock_is_fenced_with_language(self):
        ast = _doc(
            _h1("Root"),
            {
                "t": "CodeBlock",
                "c": [["", ["json"], []], '{"a": 1}'],
            },
        )
        block = _first_block(ast, ContentType.CODE)
        assert block.text.startswith("```json")
        assert block.text.rstrip().endswith("```")
        assert block.language == "json"

    def test_table_renders_pipe_table(self):
        def cell(text: str) -> list:
            return [
                ["", [], []],
                {"t": "AlignDefault"},
                1,
                1,
                [{"t": "Plain", "c": [{"t": "Str", "c": text}]}],
            ]

        def row(*texts: str) -> list:
            return [["", [], []], [cell(t) for t in texts]]

        colspec = [{"t": "AlignDefault"}, {"t": "ColWidthDefault"}]
        table = {
            "t": "Table",
            "c": [
                ["", [], []],
                [None, []],
                [colspec, colspec],
                [["", [], []], [row("Method", "Path")]],
                [[["", [], []], 0, [], [row("POST", "/auth/token")]]],
                [["", [], []], []],
            ],
        }
        ast = _doc(_h1("Root"), table)
        block = _first_block(ast, ContentType.TABLE)
        assert "| Method | Path |" in block.text
        assert "| --- | --- |" in block.text
        assert "| POST | /auth/token |" in block.text
        assert "[Table]" not in block.text

    def test_blockquote_prefixes_gt(self):
        ast = _doc(
            _h1("Root"),
            {
                "t": "BlockQuote",
                "c": [{"t": "Para", "c": [{"t": "Str", "c": "Quoted"}]}],
            },
        )
        block = _first_block(ast, ContentType.BLOCKQUOTE)
        for line in block.text.splitlines():
            assert line.startswith("> ")
        assert "Quoted" in block.text

    def test_emphasis_and_strong_surface_plain_text(self):
        para = {
            "t": "Para",
            "c": [
                {"t": "Emph", "c": [{"t": "Str", "c": "AuthService"}]},
                {"t": "Space"},
                {"t": "Strong", "c": [{"t": "Str", "c": "Redis"}]},
            ],
        }
        block = _first_block(_doc(_h1("Root"), para), ContentType.PARAGRAPH)
        # Markers are stripped so entity word boundaries stay intact.
        assert "AuthService Redis" in block.text
        assert "*" not in block.text

    def test_image_keeps_alt_text_only(self):
        img = {
            "t": "Image",
            "c": [["", [], []], [{"t": "Str", "c": "Diagram"}], ["arch.png", ""]],
        }
        block = _first_block(_doc(_h1("Root"), {"t": "Para", "c": [img]}), ContentType.PARAGRAPH)
        assert "Diagram" in block.text
        assert "arch.png" not in block.text

    def test_unknown_inline_falls_back(self):
        # Strikeout is not special-cased → hits the has-content recursion branch.
        para = {
            "t": "Para",
            "c": [{"t": "Strikeout", "c": [{"t": "Str", "c": "deprecated"}]}],
        }
        block = _first_block(_doc(_h1("Root"), para), ContentType.PARAGRAPH)
        assert "deprecated" in block.text

    def test_ordered_list_respects_start_offset(self):
        ast = _doc(
            _h1("Root"),
            {
                "t": "OrderedList",
                "c": [
                    [3, {"t": "Decimal"}, {"t": "Period"}],
                    [
                        [{"t": "Para", "c": [{"t": "Str", "c": "Third"}]}],
                        [{"t": "Para", "c": [{"t": "Str", "c": "Fourth"}]}],
                    ],
                ],
            },
        )
        block = _first_block(ast, ContentType.LIST)
        assert "3. Third" in block.text
        assert "4. Fourth" in block.text

    def test_blockquote_with_nested_list(self):
        inner = {
            "t": "BulletList",
            "c": [[{"t": "Para", "c": [{"t": "Str", "c": "point"}]}]],
        }
        block = _first_block(
            _doc(_h1("Root"), {"t": "BlockQuote", "c": [inner]}), ContentType.BLOCKQUOTE
        )
        assert "> - point" in block.text

    def test_table_without_header_synthesizes_blank(self):
        def cell(text: str) -> list:
            return [
                ["", [], []],
                {"t": "AlignDefault"},
                1,
                1,
                [{"t": "Plain", "c": [{"t": "Str", "c": text}]}],
            ]

        def row(*texts: str) -> list:
            return [["", [], []], [cell(t) for t in texts]]

        colspec = [{"t": "AlignDefault"}, {"t": "ColWidthDefault"}]
        table = {
            "t": "Table",
            "c": [
                ["", [], []],
                [None, []],
                [colspec, colspec],
                [["", [], []], []],  # empty head
                [[["", [], []], 0, [], [row("a", "b")]]],
                [["", [], []], []],
            ],
        }
        block = _first_block(_doc(_h1("Root"), table), ContentType.TABLE)
        assert "| --- | --- |" in block.text
        assert "| a | b |" in block.text

    def test_linebreak_and_empty_url_link(self):
        para = {
            "t": "Para",
            "c": [
                {"t": "Str", "c": "a"},
                {"t": "LineBreak"},
                {"t": "Link", "c": [["", [], []], [{"t": "Str", "c": "x"}], ["", ""]]},
            ],
        }
        block = _first_block(_doc(_h1("Root"), para), ContentType.PARAGRAPH)
        assert "\n" in block.text  # LineBreak preserved
        assert "x" in block.text
        assert "()" not in block.text  # empty url → no parenthesised hint

    def test_list_item_with_extra_para_and_code(self):
        item = [
            {"t": "Para", "c": [{"t": "Str", "c": "lead"}]},
            {"t": "Para", "c": [{"t": "Str", "c": "more"}]},
            {"t": "CodeBlock", "c": [["", [], []], "x = 1"]},
        ]
        block = _first_block(_doc(_h1("Root"), {"t": "BulletList", "c": [item]}), ContentType.LIST)
        assert "- lead" in block.text
        assert "more" in block.text
        assert "x = 1" in block.text

    def test_empty_para_is_skipped(self):
        doc = build_structural_model(
            _doc(
                _h1("Root"), {"t": "Para", "c": []}, {"t": "Para", "c": [{"t": "Str", "c": "real"}]}
            ),
            doc_id="t",
        )
        paras = [
            b
            for s in doc.iter_sections()
            for b in s.blocks
            if b.content_type == ContentType.PARAGRAPH
        ]
        assert len(paras) == 1
        assert paras[0].text == "real"

    def test_empty_list_is_skipped(self):
        doc = build_structural_model(_doc(_h1("Root"), {"t": "BulletList", "c": []}), doc_id="t")
        blocks = [b for s in doc.iter_sections() for b in s.blocks]
        assert blocks == []

    def test_ordered_numbering_gap_free_when_item_empty(self):
        # An empty middle item must not open a numbering gap (would read 1,_,3).
        ast = _doc(
            _h1("Root"),
            {
                "t": "OrderedList",
                "c": [
                    [1, {"t": "Decimal"}, {"t": "Period"}],
                    [
                        [{"t": "Para", "c": [{"t": "Str", "c": "First"}]}],
                        [{"t": "Para", "c": []}],  # empty item
                        [{"t": "Para", "c": [{"t": "Str", "c": "Third"}]}],
                    ],
                ],
            },
        )
        block = _first_block(ast, ContentType.LIST)
        assert "1. First" in block.text
        assert "2. Third" in block.text
        assert "3." not in block.text

    def test_ordered_item_leading_with_nested_list_keeps_marker(self):
        inner = {
            "t": "BulletList",
            "c": [[{"t": "Para", "c": [{"t": "Str", "c": "child"}]}]],
        }
        ast = _doc(
            _h1("Root"),
            {
                "t": "OrderedList",
                "c": [
                    [1, {"t": "Decimal"}, {"t": "Period"}],
                    [[inner]],  # item whose only content is a nested list
                ],
            },
        )
        block = _first_block(ast, ContentType.LIST)
        lines = block.text.splitlines()
        assert lines[0] == "1."  # marker still shown, not dropped
        assert "  - child" in block.text

    def test_blockquote_with_codeblock(self):
        block = _first_block(
            _doc(
                _h1("Root"),
                {
                    "t": "BlockQuote",
                    "c": [
                        {"t": "CodeBlock", "c": [["", [], []], "do_thing()"]},
                    ],
                },
            ),
            ContentType.BLOCKQUOTE,
        )
        assert "> do_thing()" in block.text

    def test_list_item_code_keeps_language_fence(self):
        # Code nested in a list keeps its fence + language so the `lang:` tag fires.
        item = [
            {"t": "Para", "c": [{"t": "Str", "c": "lead"}]},
            {"t": "CodeBlock", "c": [["", ["python"], []], "x = 1"]},
        ]
        block = _first_block(_doc(_h1("Root"), {"t": "BulletList", "c": [item]}), ContentType.LIST)
        assert "```python" in block.text
        assert "x = 1" in block.text

    def test_blockquote_code_keeps_language_fence(self):
        block = _first_block(
            _doc(
                _h1("Root"),
                {
                    "t": "BlockQuote",
                    "c": [
                        {"t": "CodeBlock", "c": [["", ["python"], []], "do_thing()"]},
                    ],
                },
            ),
            ContentType.BLOCKQUOTE,
        )
        assert "> ```python" in block.text
        assert "> do_thing()" in block.text
