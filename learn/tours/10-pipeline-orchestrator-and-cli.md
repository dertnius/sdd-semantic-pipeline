# Tour 10 — Orchestrator & CLI: where everything is wired

**Modules:** [pipeline.py](../../src/sdd_pipeline/pipeline.py),
[cli.py](../../src/sdd_pipeline/cli.py)

## Role in the pipeline

`SemanticPipeline` is the composition root **and** the application service —
the only place the seven stages meet (≈ `Program.cs` wiring plus the service
class your controllers would call). `cli.py` is a thin typer front-end that
builds a `PipelineConfig`, instantiates the pipeline, and formats output.

## Reading order: pipeline.py

Read `pipeline.py::SemanticPipeline` top to bottom; each method is one
composition of the stages (verify each docstring against the body):

| Method | One line |
|---|---|
| `parse_file` | stages 2–4: pandoc AST → structural `DocumentModel` (no enrichment yet) |
| `_build_inventory` | stage 3.5: structural + prose `EntityRecord`s per section ([tour 06](06-inventory-extraction-modules.md)) |
| `enrich_and_chunk` | stages 5–6: inventory (if `config.inventory_enrichment`) → `enrich_document` → `chunk_document` with the injected `entity_fn` |
| `process_file` | stages 2–6 = `enrich_and_chunk(parse_file(...), config.entity_terms)` — no indexing |
| `index_doc` | + stage 7: embed, `store.add_chunks`, then `set_provenance` |
| `index_file` | `index_doc(parse_file(path), config.entity_terms)` |
| `index_directory` | glob + per-file loop; two-pass `_index_with_corpus_scan` when `config.entity_vocab_path` is set |
| `scan_and_persist` | pass 1 only: parse all, `scan_corpus`, `save_vocabulary` — embedder never touched |
| `search` | `_verify_provenance` → embed query → dense `store.search`, or `_hybrid_search` ([tour 09](09-retrieval-and-hybrid-search.md)) |

Two cross-cutting details:

- **Lazy seams** — `embedder`/`store` properties build via `make_embedder` /
  `make_vector_store` only on first access; the constructor accepts injected
  protocol instances instead ([tour 08](08-embeddings-and-vector-store.md)).
- **Error policy in `index_directory`** — each file is wrapped in
  `try/except Exception`: `logger.exception(...)` then
  `results[str(path)] = -1`. One corrupt file never aborts a batch; `-1` is the
  failure sentinel in the returned `{path: chunk_count}` map (same convention in
  `_index_with_corpus_scan` for parse and index failures).

## Reading order: cli.py

Exactly **eight** `@app.command()` functions (count the decorators):

| Command | Calls |
|---|---|
| `index` | `index_directory` (two-pass, when `entity_vocab_path` set) or per-file `index_file`; `process_file` for `--dry-run` |
| `convert` | flow B: `html_to_gitlab_md.convert_file` per file + JSON report — no `SemanticPipeline` at all |
| `export` | `process_file` per file; or `scan_and_persist` + `enrich_and_chunk` when the vocab path is set (model-free either way) |
| `lint` | `quality.check_markdown` per file + JSON report — no `SemanticPipeline`, no pandoc, no model (pure text analysis of raw `.md`) |
| `scan` | `scan_and_persist` only |
| `scan_taxonomy` | `corpus_taxonomy.build_corpus_taxonomy` (invoked as `scan-taxonomy` — typer hyphenates the function name) |
| `search` | `pipeline.search` (plus an empty-store hint before searching) |
| `check` | no pipeline — probes pandoc, imports, and Azure env vars |

Flags are documented in [README.md](../../README.md) — don't memorise them here.

**Config override pattern** (read `cli.py::index`): CLI options become a
constructor-overrides dict, ≈ layering command-line config over environment in
`IConfigurationBuilder`:

```python
overrides: dict = {
    "chroma_persist_dir": output_dir,
    "embedding_model": model,
    ...
}
# Only override when the flag was given, so PIPELINE_VECTOR_STORE_BACKEND
# keeps working when --backend is omitted.
if backend is not None:
    overrides["vector_store_backend"] = backend
config = PipelineConfig(**overrides)
```

The `--backend` subtlety: its typer default is `None`, not `"memory"` — an
always-present key would silently clobber the env var. (Note the asymmetry:
`--model`/`--provider` have real defaults and *do* override env config every
run.) `pydantic-settings` fills everything not overridden from `PIPELINE_*` env
vars / `.env` (≈ `IOptions<T>` binding) — see [CLAUDE.md](../../CLAUDE.md)
*Configuration*.

## Developer tools (not commands)

- [dump.py](../../src/sdd_pipeline/dump.py) — run as a script: writes
  `ast.json` / `enriched.json` / `chunks.json` for one file; model-free.
- [scripts/eval_retrieval.py](../../scripts/eval_retrieval.py) — retrieval
  quality harness over the golden set ([eval/README.md](../../eval/README.md)).

## Executable documentation

- `tests/test_pipeline.py::_make_pipeline` — the mock-injection helper: a real
  `PipelineConfig` plus `MagicMock` embedder/store, so orchestration tests run
  with no pandoc, model, or disk. Then
  `TestIndexDirectory::test_error_returns_minus_one` (the `-1` sentinel) and
  `TestCrossCorpusScan::test_term_from_doc_a_tags_doc_b` (the two-pass scan).
- `tests/test_cli.py` — typer's `CliRunner` invokes the app **in-process**
  (≈ `WebApplicationFactory`, but for a console app):
  `TestExportValidation::test_rejects_unknown_format`,
  `TestScanValidation::test_requires_a_vocab_path`.

## Self-check

1. `export` and `index` share stages 2–6. Why is `export` guaranteed never to
   download a model, while `index` may?
   <details><summary>Answer</summary><code>export</code> only calls
   <code>process_file</code> / <code>scan_and_persist</code> +
   <code>enrich_and_chunk</code> — none touch the lazy <code>embedder</code>
   property. <code>index</code> calls <code>index_doc</code>, whose
   <code>self.embedder.embed_chunks(...)</code> triggers
   <code>make_embedder</code> on first use.</details>

2. `PIPELINE_VECTOR_STORE_BACKEND=chroma` is set and you run
   `sdd-pipeline index docs/`. Which backend is used? And with
   `--backend memory`?
   <details><summary>Answer</summary>chroma, then memory. <code>--backend</code>
   defaults to <code>None</code> and is only copied into the overrides dict when
   given, so the env var wins unless the flag is explicit.</details>

3. Why does `index` touch `pipeline.store` once before the file loop (skipped on
   `--dry-run`)?
   <details><summary>Answer</summary>Fail fast: an unknown backend or missing
   <code>chromadb</code> raises <code>ValueError</code>/<code>ImportError</code>
   once with a clear message, instead of repeating the same error for every
   file. A dry run never touches the store, so the probe would be a pointless
   import.</details>
