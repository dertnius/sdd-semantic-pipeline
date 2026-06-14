# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Layout note

The actual Python project lives one directory **below** this file, in the
inner `sdd-semantic-pipeline/` folder (it contains `pyproject.toml`, `src/`,
`tests/`, `docs/`). Run all commands from that inner project root, and use the
project venv at `.venv/` (`.\.venv\Scripts\python.exe` on Windows).

## Commands

```powershell
# Install (editable, with dev tools)
pip install -e ".[dev]"

# Fast unit tests — default while iterating (no pandoc / ML model needed)
pytest -m "not slow"

# Full suite (requires pandoc on PATH; first run downloads an embedding model)
pytest

# Single test
pytest tests/test_enrichment.py -k "test_extract_entities"

# With coverage (gate: fail_under=70; cli.py is omitted from coverage)
pytest -m "not slow" --cov=sdd_pipeline --cov-report=term-missing

# Lint + format (ruff: line-length 100, double quotes, py311 target)
ruff format src/ tests/ && ruff check src/ tests/

# Type-check
mypy src/
```

`pyproject.toml` sets `pythonpath=["src"]`, so `import sdd_pipeline` works in
tests without installing. CLI entry point: `sdd-pipeline` → `sdd_pipeline.cli:app`.

### Test markers

- *(none)* — fast unit tests, always run.
- `slow` — needs the pandoc binary or a real ML model. Mark any such test slow.
- `integration` — full end-to-end with all services.

To exercise the real index→search path (enrich→chunk→embed→store→search/hybrid)
**without a model or pandoc** in the fast lane, inject the `hashing_embedder` fixture
(deterministic, model-free; `tests/conftest.py`) into
`SemanticPipeline(..., embedding_model=hashing_embedder)` over the pre-built
`sample_document_model` — see `tests/test_search_offline.py`. It validates the search
*contract* (filters narrow, output is stable, hybrid/RRF runs), not semantic relevance
(which needs a real model and lives in the `slow` e2e tests).

## Architecture

Two distinct flows share the package:

**A. Indexing/search pipeline** (`SemanticPipeline` in `pipeline.py`) — a 7-stage
Confluence-MD → vector-search flow, one module per stage:

| Module | Role |
|---|---|
| `ast_parser.py` | `.md` → pandoc JSON AST (subprocess wrapper; **only** pandoc caller) |
| `structural.py` | AST → `DocumentModel` section tree (panflute, deterministic); content before the first heading (or in a heading-less doc) is attached to a **synthesized** title-derived root section so the page never silently yields 0 chunks |
| `enrichment.py` | rule-based `SectionType` / entity / tag tagging + `scan_corpus` (deterministic) |
| `chunking.py` | `DocumentModel` → `list[SemanticChunk]` (deterministic) |
| `quality.py` | raw-`.md` lint (`check_markdown`) **and** the binding chunk-level hygiene gate (`check_chunk`) — stdlib `re`, deterministic |
| `vocabulary.py` | JSON load/save of the cross-corpus entity vocabulary (I/O kept out of `enrichment.py`) |
| `embeddings.py` | sentence-transformers wrapper (**only** model loader) |
| `vector_store.py` | pluggable vector-store backends (`memory` default via langchain-core, Chroma via the `[chroma]` extra) — selected by `make_vector_store(config)` |
| `pipeline.py` | orchestration + lazy dependency wiring |
| `models.py` | pure dataclasses, no external deps or service logic |

`pipeline.py` lazily constructs the embedder and vector store on first access,
so unit tests inject mocks for both without side effects. `parse_file` runs
stages 2–4; `process_file` runs stages 2–6 (no indexing); `index_file`/
`index_directory` add embedding + store.

**Cross-corpus vocabulary (optional):** when `PIPELINE_ENTITY_VOCAB_PATH` is set,
`index_directory` runs a two-pass flow — parse every doc, `scan_corpus` to discover
an entity vocabulary across the whole set (seeded by `entity_terms` + the persisted
file), `save_vocabulary`, then enrich/index each doc with the full vocabulary — so
a term seen in one doc is recognised in all. Empty path = per-file behavior. The
discovery-only patterns (`_ALLCAPS_PATTERN`, `_BACKTICK_PATTERN`, filtered by
`_ALLCAPS_STOPLIST` + `min_length`) broaden recall for the scan but are **not** used
by `extract_entities` (precise per-section tagging).

The `sdd-pipeline export` command writes each file's `SemanticChunk`s (via
`SemanticChunk.to_dict()`, which adds the rendered `embed_text`) to per-file
`.chunks.json`/`.jsonl` artifacts + an `export-report.json`, for reuse by other
pipelines. It runs `process_file` only — **pandoc-only, no embedding model**.
Prefer `--merge-prose` for export: it packs each section's prose into one chunk
and removes the context-free fragment chunks (`"The following options were
considered:"`) that otherwise pollute a downstream index. For reference/spec
docs use `--merge-definitions`, which also folds a section's **code** into that
chunk (tables stay separate) so an instruction's explanation and its syntax share
one vector; it overrides `--merge-prose`. Junk chunks (content with no
alphanumerics, e.g. a stray `\` from a `<br/>`) are dropped automatically. When
`PIPELINE_ENTITY_VOCAB_PATH` is set, `export` runs the two-pass cross-corpus scan
first (still model-free) so the exported chunks carry cross-corpus entities.

The `sdd-pipeline scan <dir> [--vocab PATH]` command runs only the discovery half
— parse all docs, `scan_corpus`, persist the vocabulary JSON — so the term list
can be reviewed/edited before an index run. Both `scan` and the scan-enabled
`export` go through `SemanticPipeline.scan_and_persist` and load **no** model.

The `sdd-pipeline lint <dir>` command (`quality.check_markdown`) is a **report-only**
linter over **raw source `.md`** — run *before* pandoc, it flags embedding-harmful
residue (leaked HTML, untranslated Confluence macros, whole-doc code dumps,
TOC/nav link-dumps, near-empty stubs, empty section headings) and writes a
`quality-report.json`. Pure stdlib `re` — **no pandoc, no model, no pipeline** —
and it never drops/rewrites anything. Prose checks run on a *de-fenced* copy
(fenced/indented/inline code blanked, line numbers preserved) so code *examples*
don't false-positive. Point it at the real embedding corpus, not a docs tree that
*documents* Confluence syntax.

**Chunk hygiene gate (`quality.check_chunk`, the binding Arm 1).** The raw-markdown
linter above is only a *pre-filter*: it cannot see the chunk transforms that happen
after it (merge, table-summary, embed-budget split). The binding gate runs on the
produced `SemanticChunk.to_embed_text()` and is wired into `pipeline.index_doc` (via
`_enforce_chunk_gate`, gated by `config.chunk_gate`, default on). It is an
**invariant / structural-absence** check, not a residue blocklist: after de-fencing,
prose must contain no markup *shape* — a known HTML tag, a `<ac:`/`<ri:`/`<at:`
storage tag, an attributed/closing tag, a `{panel}`-style macro, an unrendered
entity, a base64 blob, or U+FFFD. A bare attribute-less `<word>` is **content**
(docs use `<placeholder>` notation), and `<br>` is exempt (intended table-cell
output); code chunks skip the markup check entirely. *Poisoned* (residue or empty)
→ **block the file** (raises `ChunkQualityError`); *weak* (over the embed budget /
hard cap) → **warn** — truncation is model-dependent and not certifiable from a char
count, so it never blocks (keeping `embed_text` within budget is chunking's job).
`pipeline.gate_chunks` exposes the same reports non-raising for `export`/inspection.

**B. HTML→GitLab-Markdown converter** (the `sdd_pipeline/convert/` subpackage) —
independent of flow A. Layout: `convert/base.py` holds the engine-agnostic shared
layer (`ConversionError`/`ConversionNotes`, `resolve_pandoc`/`_run_pandoc`, the
`postprocess`/frontmatter/`stats` text layer); `convert/html_to_gitlab_md.py` is
the HTML path (BeautifulSoup pre-clean + handlers + `convert_file`);
`convert/confluence_pf_filter.py` is the Stage-C panflute filter. Importing the
package (`from sdd_pipeline.convert import convert_file`) never pulls in flow A.
(A docx→MD path is planned to live here too, reusing `base.py` — not yet built.)
4-stage flow (spec: `docs/confluence-conversion-rules.md`, rendered-HTML scope):
BeautifulSoup pre-clean (rewrites Confluence constructs
into PFI-HTML — `div`/`span` carriers with `data-*` attrs; the blanket
unwrap/scrub is PFI-aware) → pandoc html→json → in-process panflute filter
(`confluence_pf_filter.py`: admonitions → plain blockquote labels, expand →
bold paragraph (no `<details>`), lozenges → bold, layouts flattened with no
`<hr>`, unconditional table simplification incl. `\|` escaping in code-in-cells
and `<br />` for cell line breaks) → pandoc json→gfm → fence-aware regex
post-process + YAML-safe frontmatter. Page chrome (title/space/author/date/
page_id) is harvested before root selection into `notes["metadata"]` and feeds
the frontmatter (`author:` singular — the key `structural._extract_metadata`
reads). Public API: `resolve_pandoc()`, `convert_file()` (returns
`(out_path, markdown, metrics, notes)`), `stats()`, and `ConversionError`
(raised, not `sys.exit`, so batch callers can collect failures). The
`sdd-pipeline convert` CLI command batches this over `docs/**/*.html` and emits
a JSON report with per-file + aggregate metrics (`sections`, `pictures`,
`code_snippets`, `lists`, `tables`, `urls`). `[[_TOC_]]` injection is opt-in
via `--toc` (default OFF — a TOC paragraph is a junk chunk in the embedding
corpus).

**Front door — rendered HTML only (`_reject_if_storage_format`).** `convert_file`
sniffs for a literal `<ac:`/`<ri:`/`<at:` tag opener (spec §1.2); storage-format
input only reaches the converter from REST `body.storage`/templates and lxml drops
its CDATA macro bodies, so it is **refused with `ConversionError`** rather than
silently mangled. The legacy `_normalise_ac_*` storage handlers are now unreachable
from `convert_file` (the door rejects first) and kept only for direct unit tests;
full storage support stays deferred — see the spec's SF-* rules and §12.

**Confidence gate (Arm 2).** `preprocess` records `notes.metadata["confluence_version"]`
and sets `root_fallback` when `_find_content_root` falls through to `<body>`. The
`convert` CLI reads these (`cli._convert_confidence_reasons`): when the converter's
own signals say it likely mangled a page — no recognised content container, or more
than `convert_max_unrecognized` leftover `dropped_tag`s — the file is written to an
`_quarantine/` subdir (not the corpus), marked `status: "quarantined"` with reasons
in the report, and the command exits non-zero. Tunable via `--quarantine/--no-quarantine`
and `--max-unrecognized` (config: `convert_quarantine`, `convert_max_unrecognized`).

### Key design points

- **Embed-text format** (`SemanticChunk.to_embed_text`): chunks are embedded with
  structural context prepended, not raw content:
  `[section_type] breadcrumb | keywords: … | tags: …\n\n<content>`. The header is
  kept lean for vector quality: the `[type]` prefix is omitted for the null
  `content` type, the section-type tag (which would echo the prefix) is dropped,
  keywords that merely repeat a breadcrumb token are dropped, and `lang:` tags are
  embedded only for trusted languages (`models._EMBED_LANGS`). Data **tables** are
  summarized (header row + `(table, N data rows)`) so high-entropy cells don't
  dominate the vector — the full table stays in `content`/`to_dict()`.
- **Embed budget** (`embed_char_budget`, default 1800): content is split so the
  rendered `embed_text` (header + content) stays under the model's ~512-token cap.
  `chunking._header_reserve` estimates the header so the split width leaves room for
  it — but the estimate can be wrong (e.g. inventory enrichment folds many table
  field-values into the header), so the chunk gate **warns** (never blocks) when a
  rendered `embed_text` exceeds the budget, and again past `embed_char_hard_cap`
  (default 2048) where the model likely truncates. Truncation is model-dependent and
  not certifiable from a char count, so it is a quality signal, not poison.
- **`SectionType`** (`models.py` + `enrichment._SECTION_RULES`): besides
  overview/architecture/api/decision/deployment/data_model/security, it carries
  ADR/AIP decision-record types — `alternative`, `tradeoff`, `consequence`,
  `done_criteria` — so a design doc's chosen decision, the options weighed, their
  trade-offs, consequences, and acceptance criteria are separately filterable.
  Rules are ordered (first match wins) and matched as plain substrings, so new
  keywords must not be substrings of unrelated words (`contra` ⊂ `contract`).
- **Entity scoping**: each chunk's `entities` are recomputed from its own content
  (`chunk_document(entity_fn=…)`), so a term mentioned once in a section no longer
  bleeds onto sibling chunks. `PIPELINE_ENTITY_TERMS` (a JSON array) injects a
  project vocabulary into `extract_entities` without code changes.
- **Provenance**: `SemanticChunk` carries `title`/`source_url` (and `space`/
  `labels`) so an exported record is citable on its own. The `convert` command's
  `--space`/`--source-url`/`--labels` write the matching YAML frontmatter keys
  that `structural._extract_metadata` reads back.
- **Vector-store metadata must be scalar** (`str | int | float | bool`). Lists are
  JSON-encoded strings — see `SemanticChunk.to_metadata`.
- **Hybrid retrieval** (`search --hybrid`/`-H`, or `PIPELINE_HYBRID_SEARCH`):
  fuses the dense vector ranking with a lexical BM25 ranking via Reciprocal Rank
  Fusion. `hybrid_candidate_pool` (default 50) is the per-scorer depth fused
  before top-k; `rrf_k` (default 60) is the RRF constant (higher = flatter
  weighting). Filters (`--section-type`/`--space`) apply to both rankings.
- `stats()` keeps legacy keys (`headings`, `code_blocks`) as aliases of the new
  metric names (`sections`, `code_snippets`) for back-compat.
- **Interactive search TUI** (`sdd-pipeline tui`, module `tui.py`, optional
  `[tui]` extra → Textual): a thin presentation layer over `SemanticPipeline`
  that keeps the embedder + index warm across queries (live query box, section/
  space filters, hybrid toggle, result table + content-preview pane). It imports
  `textual` only when the command runs, so core flows never pull it in; the
  blocking `pipeline.search` runs via `asyncio.to_thread` to keep the UI
  responsive. Needs a real terminal (not a redirected pipe). Pure helpers
  (`parse_top_k`/`resolve_section_type`/`format_preview`) are unit-tested and the
  app via Textual's headless `run_test()` pilot.

## Architecture guardrails

Preserve module boundaries unless the user explicitly asks otherwise; if a
request seems to require breaking one, flag the conflict and confirm first.

- `models.py` stays pure data contracts (no service logic).
- `vector_store.py` is the only module touching vector-store backends
  (langchain-core's `InMemoryVectorStore`, ChromaDB) — selected by
  `make_vector_store(config)`.
- `embeddings.py` is the only module that loads an embedding backend
  (sentence-transformers locally, or the Azure OpenAI SDK) — selected by
  `make_embedder(config)`.
- `ast_parser.py` is the only module invoking pandoc (within flow A).
- Keep `structural.py`, `enrichment.py`, `chunking.py` deterministic/unit-testable.

## Known pitfalls

- **pandoc** must be on PATH for AST and converter paths; missing pandoc is the
  usual cause of `slow`/integration failures.
- **First embedding run downloads the model** (~1.3 GB for the default
  `BAAI/bge-large-en-v1.5`). Use `--model all-MiniLM-L6-v2` (~80 MB) in dev, or
  switch to the Azure provider (no local download — see *Embedding providers*).
- **chromadb is an optional extra** (`pip install ".[chroma]"`; the dev extra
  includes it). The default backend is `memory` — an index built with
  `--backend chroma` searched without that flag loads an empty memory store and
  returns no results (the CLI prints an empty-index hint). The same persist dir
  can hold both backends' files side by side as two **independent** indexes —
  re-index after switching backends.
- **Memory backend scale**: the whole index lives in RAM and the JSON file is
  rewritten after every indexed file — fine at SDD-corpus scale, wrong tool for
  very large corpora (use chroma there).
- **Windows console encoding (cp1252)** crashes on emoji/non-ASCII when stdout is
  redirected. The `convert` command's output is deliberately ASCII-only; the
  legacy single-file script (`convert/html_to_gitlab_md.py` `main`, run as
  `python src/sdd_pipeline/convert/html_to_gitlab_md.py …`) and `index`/`check`
  still print emoji — set `$env:PYTHONUTF8 = "1"` for those. (Pandoc *subprocess*
  decoding is already pinned to UTF-8 in `ast_parser.py` and the converter's
  `_run_pandoc`, so non-ASCII page content no longer crashes the AST step on
  Windows — this was a real latent bug.)

## Configuration

Settings load from env vars (prefix `PIPELINE_`) or `.env` via
`PipelineConfig` (pydantic-settings). Common: `PIPELINE_EMBEDDING_MODEL`,
`PIPELINE_VECTOR_STORE_BACKEND` (`memory` default | `chroma`),
`PIPELINE_CHROMA_PERSIST_DIR` (the persist dir for **both** backends, despite
the name), `PIPELINE_MAX_CHUNK_CHARS`,
`PIPELINE_PANDOC_FROM_FORMAT`, `PIPELINE_ENTITY_TERMS` (JSON array of domain
vocabulary), `PIPELINE_ENTITY_VOCAB_PATH` (JSON vocabulary file; enables the
two-pass cross-corpus scan in `index`/`export` — `config/entity-vocab.json` is a
committed seed example with project terms like `XCom`/`triggerer`/`KPO`),
`PIPELINE_EMBED_CHAR_BUDGET`, `PIPELINE_CHUNK_MERGE_DEFINITIONS`,
`PIPELINE_HYBRID_SEARCH` (+ `PIPELINE_HYBRID_CANDIDATE_POOL`, `PIPELINE_RRF_K`).
Robustness gates: `PIPELINE_CHUNK_GATE` (default on — poison blocks the file),
`PIPELINE_EMBED_CHAR_HARD_CAP` (default 2048 — over it the chunk gate warns of
likely truncation), `PIPELINE_CONVERT_QUARANTINE` (default on) +
`PIPELINE_CONVERT_MAX_UNRECOGNIZED` (default 8) for the converter confidence gate.
New config fields must be added to **both** `PipelineConfig` branches
(pydantic-settings v2 and the pydantic-v1 fallback).

## Embedding providers

The embedder is pluggable via `embedding_provider` (`local` default | `azure`),
selected by `make_embedder(config)` in `embeddings.py`. Both implement
`EmbedderProtocol` (`embed_chunks` / `embed_query`), so the pipeline and tests
depend only on the protocol.

- **local** — sentence-transformers (`--model`, e.g. `all-MiniLM-L6-v2`). Default.
- **azure** — Azure OpenAI embeddings via the **optional** `openai` SDK
  (`pip install ".[azure]"`). Enable with `--provider azure` on `index`/`search`.
  Credentials come from env only (never CLI flags): `PIPELINE_AZURE_OPENAI_ENDPOINT`,
  `PIPELINE_AZURE_OPENAI_DEPLOYMENT`, `PIPELINE_AZURE_OPENAI_API_KEY` (secret), and
  optional `PIPELINE_AZURE_OPENAI_API_VERSION`. With `--provider azure` the
  deployment is the embedding model; `--model` is ignored. `sdd-pipeline check`
  reports `openai` availability and whether the Azure env vars are set.

**Index provenance:** `index_file` records `(provider, model, dimension)` with
the index — on the Chroma collection's metadata, or in a
`<collection>.provenance.json` sidecar for the memory backend; `search` verifies
it and raises a clear error if the configured embedder differs from the one that
built the index (different providers/models produce incompatible vector spaces).
Re-index or align `--provider`/`--model` to fix. Chroma's `set_provenance`
excludes reserved `hnsw:*` keys — `collection.modify` rejects a metadata payload
that contains them.

## Vector store backends

The store is pluggable via `vector_store_backend` (`memory` default | `chroma`),
selected by `make_vector_store(config)` in `vector_store.py`. Both implement
`VectorStoreProtocol` (`add_chunks`/`search`/`get_corpus`/`delete_document`/
`reset`/provenance/`count`), so the pipeline and tests depend only on the
protocol. Both backend libraries are imported lazily, so `export`/`scan`/
`convert` work with neither installed.

- **memory** — langchain-core's `InMemoryVectorStore`, persisted as
  `<persist_dir>/<collection>.json` (atomic tmp+replace writes) plus a
  `<collection>.provenance.json` sidecar, so index → search across separate
  processes works. Default; no optional deps. The pipeline supplies precomputed
  vectors by writing the documented `store` dict directly; the `Embeddings`
  stub passed to the constructor raises if anything tries to re-embed.
  Cosine similarity is mapped to `distance = 1 - similarity` (same space as
  Chroma cosine), so `SearchResult.score` semantics are identical.
- **chroma** — ChromaDB via the **optional** `chromadb` package
  (`pip install ".[chroma]"`). Enable with `--backend chroma` on
  `index`/`search`, or `PIPELINE_VECTOR_STORE_BACKEND=chroma`. The backend a
  search uses must match the one that built the index. `sdd-pipeline check`
  reports `langchain_core` as required and `chromadb` informationally.
