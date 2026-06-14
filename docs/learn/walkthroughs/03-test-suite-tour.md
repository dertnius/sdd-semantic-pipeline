# Test-suite tour — the tests are the documentation

> The fastest way to learn what a module *guarantees* is to read its tests next to it.
> This page shows you the suite's layout, its three quality tiers, and where a new test
> belongs. Commands: [CLAUDE.md](../../../CLAUDE.md); module map: [architecture map](02-architecture-map.md).

## The 1:1 convention — tests as a navigation system

List `tests/` and you'll see almost every `src/sdd_pipeline/<module>.py` has a
`tests/test_<module>.py` twin: `test_ast_parser.py`, `test_structural.py`,
`test_enrichment.py`, `test_chunking.py`, `test_vocabulary.py`, `test_doc_router.py`,
`test_extract_prose.py`, `test_extract_structural.py`, `test_retrieval.py`, … So the
study recipe for any tour is: open `module.py` and `test_module.py` side by side — the
test names are the module's contract in plain English (e.g.
`test_chunking.py::test_breadcrumb_includes_section_title`). The few non-1:1 files are
the interesting exceptions covered below (`test_enrichment_inventory.py`,
`test_memory_vector_store.py`, and the e2e pair).

## `conftest.py` — why most tests need no pandoc and no model

[`tests/conftest.py`](../../../tests/conftest.py) holds two hand-crafted constants and four
fixtures, auto-injected into every test file (pytest's DI — think xUnit fixtures, but
resolved by *parameter name*):

| Fixture | What it gives you | Replaces |
|---|---|---|
| `sample_md_file` | `SAMPLE_MARKDOWN` (a fake "Auth Service Design" doc) written to `tmp_path` | a real input file |
| `sample_ast` | `SAMPLE_AST`, a hand-written dict matching pandoc 3.x JSON | the pandoc binary |
| `sample_document_model` | a pre-built `DocumentModel` with 5 typed sections | stages 2–3 entirely |
| `sample_chunks` | two minimal `SemanticChunk`s | stages 2–6 entirely |

**Guiding question:** why does `SAMPLE_AST` exist when pandoc could generate it? Because
`structural.py` tests can then run with *no binary installed* — the fixture pins the AST
shape the code must accept. Each fixture enters the pipeline one stage later, so every
stage is testable in isolation.

## Marker tiers (defined in [`pyproject.toml`](../../../pyproject.toml), `[tool.pytest.ini_options] markers`)

- *(no marker)* — pure unit tests; the dev loop is `pytest -m "not slow"`.
- `slow` — "tests that require pandoc or a real ML model". E.g. every test in
  `test_ast_parser.py::TestGenerateAst` is `@pytest.mark.slow` because
  `generate_ast(sample_md_file)` shells out to real pandoc.
- `integration` — "end-to-end tests requiring all runtime services".

`test_pipeline.py` shows the trick that keeps the orchestrator in the fast tier: it
injects `MagicMock` embedder/store (`test_pipeline.py::_mock_embedder` / `_mock_store`)
into `SemanticPipeline`, which only constructs real ones lazily.

## The e2e tier — what the big tests prove beyond units

- **`test_pipeline_inventory_e2e.py`** proves the stage-3.5 *wiring*, not one module:
  `test_directional_table_column_reaches_chunk_and_embed_text` builds a one-table doc and
  asserts a `Consumer` column value lands in `chunk.depends_on` **and** appears as
  `"depends on: order-service"` in `to_embed_text()` — table → inventory → routing
  (`config/field_directions.yaml`) → chunk → vector text, in one fast test. Its `slow`
  sibling `test_real_sad_populates_directional_fields_end_to_end` repeats this on the
  real `src/tools/eval/corpus/sad-retailnexus-oms.md` via `process_file`.
- **`test_e2e_real_docs.py`** proves enrichment works on *real public* architecture docs,
  not just the synthetic SAD. It is `slow`, **skips** (never fails) when
  `src/tools/eval/e2e_corpus/` is empty (fetch with `src/tools/scripts/fetch_e2e_corpus.py` — the only
  networked code), reuses the eval harness's deterministic `HashingEmbedder` (no model
  download), and runs an A/B retrieval comparison with inventory enrichment on vs off —
  hard gate: no regression + the feature is live.

## The third tier — retrieval *quality*, not correctness

Unit tests answer "does the code do what it says?"; nothing above answers "did this
change make **search results better or worse**?" That's `src/tools/scripts/eval_retrieval.py`: it
re-indexes `src/tools/eval/corpus/` fresh each run and scores recall@5/10 + MRR against the
**frozen** golden set `src/tools/eval/queries.yaml` (categories: `cross-reference`, `paraphrase`,
`lexical-control` — frozen so nobody edits it to chase a score). Results append to
[`RETRIEVAL_LOG.md`](../../../src/tools/eval/RETRIEVAL_LOG.md); the contract is *"After M5 must beat
Baseline"*. Full protocol: [src/tools/eval/README.md](../../../src/tools/eval/README.md).

## Where would a new test go? A decision guide

1. **Which stage's *input* does your code consume?** Take the fixture that produces it
   and nothing earlier: testing chunk logic → `sample_document_model` (as all of
   `test_chunking.py` does); testing embed-text consumption → `sample_chunks` (as
   `test_embeddings.py::test_embed_chunks_uses_embed_text` does, with a fake recording
   backend instead of a real model).
2. **Does it touch pandoc or a real model?** Then `@pytest.mark.slow`, like
   `test_ast_parser.py`. If you can mock the boundary instead (à la
   `test_pipeline.py::_mock_embedder`), do that and stay fast.
3. **Is it cross-stage wiring?** Build a tiny in-memory `DocumentModel` by hand, like
   `test_pipeline_inventory_e2e.py::_doc_with_table` — still fast, no fixtures needed.
4. **Could it change ranking?** Code tests won't see it — add a query to
   `src/tools/eval/queries.yaml` *only before* a baseline is recorded, and run the eval harness.

## Self-check

**Q1. You add a keyword to `enrichment._SECTION_RULES`. Which test files should change,
and does anything need `@pytest.mark.slow`?**

<details><summary>Answer</summary>

`tests/test_enrichment.py` (the 1:1 twin) — assert the new classification, and that the
keyword isn't a substring of an unrelated word (the `contra` ⊂ `contract` pitfall in
[CLAUDE.md](../../../CLAUDE.md)). No `slow` marker: enrichment is deterministic and tests
run on `sample_document_model` or hand-built `Section`s — no pandoc, no model. If the
rule could shift retrieval ranking, that's the eval harness's job, not pytest's.
</details>

**Q2. Why does `test_e2e_real_docs.py` use a hashing embedder instead of the real model,
and what does that mean its A/B comparison can and cannot prove?**

<details><summary>Answer</summary>

Determinism and zero download — CI never pulls ~1.3 GB. A hashing embedder only matches
overlapping token n-grams, so the A/B measures enrichment's **lexical** contribution
(extra terms folded into `embed_text`). It cannot prove *semantic* gain (e.g. that
`depends on:` phrasing matches "what depends on X" queries) — per
[src/tools/eval/README.md](../../../src/tools/eval/README.md), that needs a real model via
`src/tools/scripts/eval_retrieval.py`.
</details>
