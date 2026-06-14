# Tour 02 — ast_parser.py & structural.py: markdown → typed tree

**Role in the pipeline.** Stage 2 ([ast_parser.py](../../../src/sdd_pipeline/ast_parser.py))
shells out to pandoc and gets back a JSON syntax tree. Stages 3+4
([structural.py](../../../src/sdd_pipeline/structural.py)) turn that tree into the
typed `DocumentModel` from [tour 01](01-models-and-config.md). Everything after
this point is pure Python on plain dataclasses.

## ast_parser.py — a deliberately thin wrapper

Read the whole file (86 lines): `ast_parser.py::generate_ast` is a
`subprocess.run(["pandoc", ..., "--to=json", "--standalone"])` call plus
`json.loads` — comparable to a thin `Process.Start` wrapper class in C#.
*Why `--standalone`?* (The inline comment answers it.) This module is the
**only** pandoc caller in flow A — an architecture guardrail spelled out in
[CLAUDE.md](../../../CLAUDE.md) and decided in
[ADR-0001](../../../docs/adr/adr-0001-modular-semantic-pipeline.md): isolating the
external binary keeps every later stage deterministic and unit-testable, and a
real parser-grade AST beats regexing markdown yourself.

What pandoc hands back — a real excerpt from
[outbox/dump/retailnexus/ast.json](../../../outbox/dump/retailnexus/ast.json) (whitespace
reformatted):

```json
{
  "t": "Header",
  "c": [
    1,
    ["introduction", [], []],
    [{ "t": "Str", "c": "Introduction" }]
  ]
}
```

Every node is `{"t": <type>, "c": <content>}` — a tagged union, like a C#
discriminated-union-by-convention (`JsonDerivedType`). For a `Header`, `c` is
`[level, [identifier, classes, attrs], inlines]`. That `"introduction"`
identifier becomes the `section_id` downstream.

## structural.py — reading order

1. **`structural.py::build_structural_model`** (start at the bottom of the
   file). The core loop walks top-level blocks once; headers open sections,
   everything else lands in the section currently on top of a stack:

   ```python
   # Pop the stack until we find a valid parent
   while stack and stack[-1].level >= elem.level:
       stack.pop()
   ```

   *Guiding question:* given headings H1, H2, H3, H2 — which sections are on
   `stack` when the second H2 arrives, and where does it get attached? This
   stack is the central trick that turns a **flat** H1–H6 sequence into a
   **tree** (the same algorithm you'd use to build an outline from
   `<h1>..<h6>` in C#: a `Stack<Section>` keyed on level). Also note how
   `breadcrumb` is computed from the stack *before* popping, filtered by
   `s.level < elem.level`.
2. **`structural.py::_elem_to_content_block`** — the per-block-type dispatch
   (`isinstance` chain ≈ C# `switch` on pattern types). Each branch delegates
   to a structure-*preserving* serializer; read the comment block above
   `_link_hint` for why these exist instead of `pf.stringify`.
3. **The serializers** — `structural.py::_serialize_table` (rebuilds a GitHub
   pipe table, keeps the header row — [tour 05](05-taxonomy-modules.md) parses
   these back), `_serialize_list` (numbering survives, empty items don't
   consume a number), `_serialize_inline_list` (backticks kept so entity
   regexes in [tour 03](03-enrichment.md) still fire). *Question:* why does
   `_serialize_inline_list` strip `Emph`/`Strong` markers but keep `Code`
   backticks?
4. **`structural.py::_extract_metadata`** — YAML frontmatter → 
   `DocumentMetadata`, with alias chains like
   `get("space") or get("space-key") or get("spaceKey")` because Confluence
   exports are inconsistent.

## doc_id: stable, but only on your machine

`pipeline.py::_stable_doc_id` derives the id as
`hashlib.md5(str(path.resolve()).encode()).hexdigest()[:12]` — md5 of the
**absolute resolved path**, 12 chars. Consequence: the same file produces a
different `doc_id` (and thus different chunk ids) on every machine/checkout.
That is why the retrieval eval
([src/tools/scripts/eval_retrieval.py](../../../src/tools/scripts/eval_retrieval.py)) judges hits by
`(doc, breadcrumb-substring)` matching, never by ids.

## Executable documentation

- [tests/test_ast_parser.py](../../../tests/test_ast_parser.py) — every real
  pandoc call is `@pytest.mark.slow` (needs the binary on PATH). Read
  `test_returns_dict_with_required_keys` and
  `test_writes_json_files_when_output_dir_given`.
- [tests/test_structural.py](../../../tests/test_structural.py) — runs **without**
  pandoc: the `sample_ast` fixture returns the hand-written `SAMPLE_AST` dict
  from [tests/conftest.py](../../../tests/conftest.py) (~line 84). Read
  `test_h2_sections_are_subsections_of_h1` (the stack in action) and
  `test_ordered_numbering_gap_free_when_item_empty` (the list serializer's
  trickiest rule).

## Self-check

1. What happens to a paragraph that appears *before the first heading* of a
   document?
   <details><summary>Answer</summary>
   It is **kept**. With no heading open yet (the <code>else</code> branch in
   <code>build_structural_model</code>), such blocks are buffered into
   <code>preamble_blocks</code>; if any exist, they are attached to a
   *synthesized* root section titled from <code>doc.metadata.title</code> (or
   "Document"), so a preamble — or a doc with no headings at all — still produces
   chunks instead of silently yielding zero. A warning is logged. (Historically
   these blocks were dropped under an <code>elif stack:</code> guard — that was a
   real exposure, since a Confluence title is harvested into metadata and is not
   guaranteed to be emitted as a body H1.)
   </details>
2. A document jumps from H1 straight to H3. Where does the H3 section land,
   and what is its breadcrumb?
   <details><summary>Answer</summary>
   The pop loop only removes entries with <code>level >= 3</code>, so the H1
   stays and the H3 becomes its direct subsection. The breadcrumb is
   <code>[H1 title, H3 title]</code> — levels are not "filled in"; the
   breadcrumb reflects actual ancestors, not nominal depth.
   </details>
3. Why does `_elem_to_content_block` wrap code in ` ```lang ` fences instead
   of storing the raw text, when `language` is already a field?
   <details><summary>Answer</summary>
   The inline comment says it: enrichment's <code>lang:</code> tag rule
   (<code>enrichment.py::extract_tags</code>) detects languages by scanning
   the <em>text</em> for fences, so the fence must be part of the block text —
   including for code nested in lists and blockquotes, which each re-emit the
   fence in their serializers.
   </details>
