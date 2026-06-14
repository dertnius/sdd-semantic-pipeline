# Tour 05 — the taxonomy modules: what fields *should* a SAD have?

**Role in the pipeline.** Four small modules answer one question: *which
fields does the Solution Architecture Document template define, per section,
so a live document's tables can be matched against them?* The answer feeds
the inventory-driven enrichment of [tour 03](03-enrichment.md) (extraction
itself is [tour 06](06-inventory-extraction-modules.md)). All four are
pandoc-only, model-free.

## Reading order

1. **[header_norm.py](../../../src/sdd_pipeline/header_norm.py)** (50 lines) —
   read the module docstring first: **it is the spec**, a 5-step normalisation
   applied both when extracting the taxonomy and when matching live headers,
   so the two sides meet on canonical forms. Before reading
   `header_norm.py::normalise_header`, predict the outputs of:
   `"Consumer (system)"`, `"client/consumer"`, `"Related Components"`,
   `"Status"`. (Check yourself against the docstring; `_KEEP_S` guards
   `ss/us/is/as/os` endings so "status" keeps its s.) Note how conservative it
   is on purpose — merge obvious variants, no real lemmatisation.
2. **[template_taxonomy.py](../../../src/sdd_pipeline/template_taxonomy.py)** —
   - `template_taxonomy.py::_walk` — a 4-line *recursive generator*
     (`yield` + `yield from`; C# analog: an iterator method `yield return`-ing
     while recursing) that flattens the Section tree depth-first.
   - `template_taxonomy.py::parse_pipe_table` — reverses
     `structural._serialize_table` ([tour 02](02-ast-parser-and-structural.md)):
     splits on unescaped `|`, drops the separator row.
   - `template_taxonomy.py::fields_and_orientation` — *what does
     "orientation" mean?* A template table either has a real header row whose
     cells **are** the field names (**wide**: one entity per body row, body
     rows are samples and are *not read*), or an empty header with field names
     in **body column 0** and `[Describe …]` placeholders in column 1
     (**key_value**). Guiding question: why must the wide branch skip body
     rows entirely? (See `test_extract_taxonomy_never_leaks_body_sample_values`.)
   - `template_taxonomy.py::extract_taxonomy` — walks the template, emits
     `{normalised_section_key: {fields, orientation}}` →
     [data/taxonomy.json](../../../data/taxonomy.json).
3. **[corpus_taxonomy.py](../../../src/sdd_pipeline/corpus_taxonomy.py)** — same
   idea, but derived from the *real corpus* instead of the ideal template,
   because live docs diverge and carry richer fields. Read
   `corpus_taxonomy.py::build_corpus_taxonomy`: it reuses `parse_pipe_table` +
   `fields_and_orientation` per table, then gates fields by
   **document-frequency** (`min_docs`, default 2) — a field counts only if
   seen in ≥ N distinct documents. It also returns the ungated
   `{field: doc_freq}` vocabulary: the review artifact a human uses to fill
   `config/field_directions.yaml` (which field names mean depends_on/exposes).
4. **[doc_router.py](../../../src/sdd_pipeline/doc_router.py)** —
   `doc_router.py::SAD_FINGERPRINT` is a frozenset of five normalised
   top-level SAD headings; `doc_router.py::detect_doc_type` routes a doc to
   `"sad"` when its normalised headings overlap the fingerprint by ≥ 3
   (inclusive threshold), else `"unknown"` → empty taxonomy, heading-only
   enrichment. Per its docstring it is deliberately minimal — multi-template
   routing waits until a second template exists. (Today it is exercised by
   tests; the stage-3.5 extractors route fields by *name* via
   `field_directions.yaml`.)

## The payoff, in real numbers

Run `SemanticPipeline().process_file(...)` on the two eval docs (or inspect
[out/retailnexus/chunks.json](../../../out/retailnexus/chunks.json)):

- [eval/corpus/sad-retailnexus-oms.md](../../../eval/corpus/sad-retailnexus-oms.md)
  — a template-conforming SAD: **47 chunks**, 46 of them carrying inventory
  `metadata` fields, with `exposes` populated on the *Microservices Inventory*
  chunk (`REST (read-only)`, `GraphQL`, `Events (consume only)` …) and
  `depends_on` on *External Integration Contracts*.
- [eval/corpus/impala-vscode.md](../../../eval/corpus/impala-vscode.md) — not a
  SAD: **13 chunks**, **zero** `depends_on`/`exposes` (only audit-bucket
  `raw_entities` metadata).

Structured tables in, structured retrieval cues out — those values are folded
into the embed header by `models.py::SemanticChunk.to_embed_text`
([tour 01](01-models-and-config.md)).

## CLI

`cli.py::scan_taxonomy` — `sdd-pipeline scan-taxonomy <dir> --min-docs N`
writes `data/taxonomy.json` plus the frequency-ranked
`data/field_vocabulary.json` for review. (The *template* extractor runs as
`python -m sdd_pipeline.template_taxonomy <template.md>` — see
`template_taxonomy.py::main`.)

## Executable documentation

- [tests/test_header_norm.py](../../../tests/test_header_norm.py) —
  `test_normalise_examples` (the spec as a parametrized table) and
  `test_keep_s_endings_not_stripped`.
- [tests/test_template_taxonomy.py](../../../tests/test_template_taxonomy.py) —
  `test_key_value_orientation_uses_col0_skips_placeholders` and
  `test_extract_taxonomy_real_template` (runs against the committed template;
  slow — needs pandoc).
- [tests/test_corpus_taxonomy.py](../../../tests/test_corpus_taxonomy.py) —
  `test_two_doc_corpus_gates_to_shared_fields` (the min_docs gate).
- [tests/test_doc_router.py](../../../tests/test_doc_router.py) —
  `test_threshold_is_inclusive` and `test_taxonomy_for_routes_sad_to_taxonomy_else_empty`.

## Self-check

1. `normalise_header("Consumers (system)")` — walk the 5 steps. Result?
   <details><summary>Answer</summary>
   lowercase → <code>"consumers (system)"</code>; parenthetical stripped →
   <code>"consumers "</code>; no <code>/</code>; whitespace collapsed →
   <code>"consumers"</code>; singularised (len&gt;3, ends in s, not a
   <code>_KEEP_S</code> ending) → <code>"consumer"</code>.
   </details>
2. A one-document corpus is scanned with the default `min_docs=2`. What does
   `build_corpus_taxonomy` return?
   <details><summary>Answer</summary>
   An empty taxonomy — every field's doc-frequency is 1, below the gate
   (<code>test_min_docs_gate_empty_on_single_doc_corpus</code>) — but the
   field vocabulary still lists every field with frequency 1, because it is
   deliberately ungated for human review.
   </details>
3. Why does `detect_doc_type` compare *normalised, number-stripped* headings
   instead of raw titles?
   <details><summary>Answer</summary>
   Real SADs write headings like <code>"5.1.1 Solution Components"</code>.
   <code>_heading_keys</code> strips the leading numbering
   (<code>_LEAD_NUM</code>) and applies <code>normalise_header</code>, so
   <code>"Requirements"</code> ≡ <code>"requirement"</code> matches the
   fingerprint regardless of numbering, case, or plural form.
   </details>
