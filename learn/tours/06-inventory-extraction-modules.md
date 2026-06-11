# Tour 06 — Inventory extraction: tables + prose → routed fields

**Modules:** [extract_structural.py](../../src/sdd_pipeline/extract_structural.py),
[extract_prose.py](../../src/sdd_pipeline/extract_prose.py),
[direction.py](../../src/sdd_pipeline/direction.py),
[reconcile.py](../../src/sdd_pipeline/reconcile.py)

## Role in the pipeline

Stage 3.5 sits between structural parsing and enrichment: it mines per-section
`EntityRecord`s from a document's tables (confidence 1.0) and prose (0.5–0.9),
reconciles the two, and lets enrichment route each record into
`Section.depends_on` / `Section.exposes` / `Section.metadata` by **field name**.
Four small modules, all deterministic and pandoc-free — Sections in, records out.

## Reading order

1. Start with the data contract: `models.py::EntityRecord` (a `@dataclass(frozen=True)`
   ≈ a C# `record` with init-only setters). Note `__post_init__` defaults
   `canonical` to `text`. *Why does every record carry a `section_id`?*
2. Open [extract_structural.py](../../src/sdd_pipeline/extract_structural.py)
   (70 lines). Read `extract_structural.py::_records_from_table` — the two
   orientations: **wide** (headers are fields, each body cell → one record) vs
   **key-value** (empty header row → col 0 is the field, col 1 the value).
   *Guiding question: what does a record's `field` come from — the column's name
   or its position?* (The answer is the whole design: see
   `test_field_follows_header_name_not_position` below.)
3. Then `extract_structural.py::extract_structural` /
   `extract_structural.py::build_structural_inventory` — only `ContentType.TABLE`
   blocks are touched; everything is `confidence=1.0`, `source="table_cell"`.
4. Open [extract_prose.py](../../src/sdd_pipeline/extract_prose.py). Read the
   module docstring's confidence ladder (`allcaps_regex` 0.9 → `backtick_regex`
   0.8 → `prose` 0.6 → `noun_chunk` 0.5), then `extract_prose.py::extract_prose`.
   *Why do all prose records get `field=""`?* Then `extract_prose.py::_noun_chunks` —
   the spaCy import is guarded and every failure returns `[]` (silent fallback;
   the pipeline never requires an NLP model).
5. Open [direction.py](../../src/sdd_pipeline/direction.py).
   `direction.py::load_field_directions` reads `DEFAULT_DIRECTIONS_PATH =
   Path("config/field_directions.yaml")` (~line 17) — the reviewed map of field
   names to `"depends_on"` / `"exposes"`. Both the YAML entries and the queried
   field pass through `header_norm.normalise_header`, so "Consumers" matches
   "consumer". Missing file → `{}` (everything falls back to metadata).
6. Open [reconcile.py](../../src/sdd_pipeline/reconcile.py).
   `reconcile.py::reconcile` dedupes on `(section_id, canonical.casefold())`;
   read `reconcile.py::_supersedes`:

   ```python
   if candidate.confidence != incumbent.confidence:
       return candidate.confidence > incumbent.confidence
   return (candidate.field, candidate.source, candidate.text) < (...)
   ```

   Highest confidence wins; the tie-break is a stable key (≈ a deterministic
   C# `IComparer<T>`), so output never depends on input order.

## Integration point: how records reach chunks

In [pipeline.py](../../src/sdd_pipeline/pipeline.py), read
`pipeline.py::SemanticPipeline._build_inventory` — it merges
`build_structural_inventory(doc)` and `build_prose_inventory(doc)` into one
`{section_id: [records]}` dict. `pipeline.py::SemanticPipeline.enrich_and_chunk`
builds it only when `config.inventory_enrichment` is true (default; see
[config.py](../../src/sdd_pipeline/config.py)) and hands it to
`enrichment.py::enrich_document`. From there, follow
`enrichment.py::_apply_inventory` → `enrichment.py::_write_to_field`:

- field resolves to a direction → `section.depends_on` / `section.exposes`
- named but non-directional field → `section.metadata[<field>]`
- unnamed (prose) or below `confidence_threshold=0.6` → `metadata["raw_entities"]`

Chunking copies these onto every chunk, and `models.py::SemanticChunk.to_embed_text`
folds them into the vector text as `depends on: …` / `exposes: …`.

## Key design decisions

- **Name, never position.** A reordered or extended table still routes correctly,
  because records carry the table's own (normalised) header label and
  `direction.py::resolve_direction` looks up only that name.
- **Tables are authoritative.** Table cells get confidence 1.0, so after
  `reconcile`, a prose mention can never override a table cell's field/direction.
- **Additive and gated.** Legacy enrichment (section types, entities, tags)
  always runs; the inventory path is an optional layer behind one config flag.

## The observable payoff (real data)

Run `process_file` over [eval/corpus/sad-retailnexus-oms.md](../../eval/corpus/sad-retailnexus-oms.md):
its "External Integration Contracts" section has a `Direction` column
(mapped to `depends_on` in [config/field_directions.yaml](../../config/field_directions.yaml)),
so that chunk carries `depends_on = ['Bidirectional', 'OMS → Carrier', 'OMS → ERP',
'OMS → Provider', …]`, and "Microservices Inventory" carries `exposes` from its
`Exposes` column. The same run over `eval/corpus/impala-vscode.md` yields **zero**
`depends_on`/`exposes`: that doc contains no pipe tables at all, and prose records
(`field=""`) only ever land in `metadata.raw_entities`. (Template fingerprinting
for SAD-shaped docs lives in `doc_router.py` — see [tour 05](05-taxonomy-modules.md);
`_build_inventory` itself runs unconditionally on every doc.)

## Executable documentation

- `tests/test_extract_structural.py::test_field_follows_header_name_not_position`
- `tests/test_reconcile.py::test_table_beats_prose_for_same_canonical`
- `tests/test_pipeline_inventory_e2e.py::test_directional_table_column_reaches_chunk_and_embed_text`
  — the full wire: table column `Consumer` → `chunk.depends_on` → `"depends on: order-service"`
  in embed text. Also `tests/test_extract_prose.py`, `tests/test_direction.py`.

## Self-check

1. A section's prose says "the `payment-service` handles refunds" and its table
   has a `Related components` row listing `payment-service`. How many records
   survive reconciliation for that section, and which field do they carry?
   <details><summary>Answer</summary>One. Both records share
   <code>(section_id, "payment-service")</code>; the table cell has confidence 1.0
   vs 0.8 for the backtick mention, so <code>_supersedes</code> keeps the table
   record with <code>field="related component"</code> — which
   <code>field_directions.yaml</code> maps to <code>depends_on</code>.</details>

2. `config/field_directions.yaml` is deleted. Do table records disappear?
   <details><summary>Answer</summary>No. <code>load_field_directions</code> returns
   <code>{}</code>, so <code>resolve_direction</code> yields <code>None</code> for every
   field — named records route to <code>metadata.&lt;field&gt;</code> instead of
   depends_on/exposes. Nothing is dropped (the "conservation" note in
   <code>enrichment.py::_apply_inventory</code>).</details>

3. spaCy is not installed. Which extraction sources still fire?
   <details><summary>Answer</summary>All except <code>noun_chunk</code>:
   <code>allcaps_regex</code>, <code>backtick_regex</code>, and the PascalCase /
   kebab-case / path <code>prose</code> patterns are pure regex.
   <code>_noun_chunks</code> catches the ImportError and returns <code>[]</code>
   (see <code>test_extract_prose.py::test_runs_without_spacy_model</code>).</details>
