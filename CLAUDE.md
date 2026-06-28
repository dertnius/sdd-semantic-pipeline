# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Layout note

This directory **is** the Python project root — `pyproject.toml`, `src/`,
`tests/`, `docs/`, `config/`, `inbox/`, and `outbox/` all live here. Run all
commands from here, and use the project venv at `.venv/`
(`.\.venv\Scripts\python.exe` on Windows).

## Workspace contract (inbox / outbox)

The CLI enforces a two-zone workspace: every pipeline **input** must live under
`inbox/` and every **output** under `outbox/` (subfolders allowed). Defaults
point into the zones (input → `inbox/`, outputs → `outbox/<sub>/`), so bare
commands need no path flags. The guard lives in `workspace.py` (a CLI-layer
module wired into every `cli.py` command and `dump.py`; it never touches the
deterministic core). Out-of-zone paths are rejected (exit 2) unless
`PIPELINE_ENFORCE_WORKSPACE=false`. Standard outbox sub-layout: `outbox/index/`
(vector index), `outbox/md/` (converted markdown), `outbox/chunks/` (exported
chunks), `outbox/reports/` (convert/lint reports), `outbox/vocab/` (entity
vocabulary), `outbox/taxonomy/` (taxonomy + field vocabulary), `outbox/media/`
(resolved diagram SVGs), `outbox/drawio/` (converted draw.io diagrams),
`outbox/dump/`.
The `scan`/`scan-taxonomy` outputs land in `outbox/`; promote a reviewed copy
into committed `config/` by hand (`config/` is configuration, not an output
zone). Tests bypass the guard via an autouse `PIPELINE_ENFORCE_WORKSPACE=false`
fixture in `tests/conftest.py`; `tests/test_workspace.py` +
`tests/test_cli_workspace.py` cover the contract itself.

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
| `workspace.py` | inbox/outbox path contract (CLI-layer guard; resolvers + `WorkspaceError`) — imported by `cli.py`/`dump.py` only |
| `models.py` | pure dataclasses, no external deps or service logic |

`pipeline.py` lazily constructs the embedder and vector store on first access,
so unit tests inject mocks for both without side effects. `parse_file` runs
stages 2–4; `process_file` runs stages 2–6 (no indexing); `index_file`/
`index_directory` add embedding + store.

**Enrichment, retrieval & ingestion support modules** (also flow A, deterministic
unless noted; keep them as unit-testable as the core):

| Module | Role |
|---|---|
| `retrieval.py` | BM25 (Okapi) lexical index + Reciprocal Rank Fusion — powers `--hybrid` and model-free `--lexical` search; optional snowball stemming (`[stem]`) |
| `lang_rules.py` | per-language enrichment rule packs (`LangPack` for en/de/fr/it) — **data only**, consumed by `enrichment.py` |
| `detection.py` | per-document language auto-detection (langdetect wrapper, `[lang]` extra) for `--lang auto` |
| `header_norm.py` | deterministic table header / column-label normalisation (lowercase, singularise, strip qualifiers) |
| `template_taxonomy.py` | section→field taxonomy extracted from the SAD template's tables |
| `corpus_taxonomy.py` | data-aligned section→field taxonomy derived from the **corpus** by document-frequency (`scan-taxonomy`) |
| `doc_router.py` | detect a document's type (SAD fingerprint) and route it to the matching taxonomy |
| `extract_structural.py` | table-cell entity records (confidence 1.0, field-routed) |
| `extract_prose.py` | prose entity records (regex + optional spaCy NER/noun-chunks; `ner:*` facets are metadata-only, never embedded) |
| `reconcile.py` | union + dedupe mixed-section entity records by confidence (table cells > ALLCAPS > prose) |
| `direction.py` | field-name → dependency direction (`depends_on`/`exposes`) from `config/field_directions.yaml` |
| `config.py` | `PipelineConfig` (pydantic-settings; **dual v2/v1 branches**) |
| `report.py` | per-file diagnostic HTML report (`sdd-pipeline report`) — every stage's artifact, chunk quality, info-loss vs the original HTML, an SVG relationship graph |
| `download.py` | optional SiteMinder-aware ingestion (`sdd-pipeline download`, `[download]` extra) — CLI-layer; the core never reads its secrets |
| `dump.py` | debug export of intermediate stage artifacts |

**Multilingual enrichment.** Enrichment is language-parameterised: `lang_rules.py`
holds en/de/fr/it `LangPack`s (section/genre keywords, entity patterns) that
`enrichment.py` compiles per language; `--lang <code>` selects one and `--lang auto`
detects per file via `detection.py` (`[lang]`). Unsupported codes fall back to
English. The `--lang` flag is on `index`/`export`/`search`/`tui`/`mcp`.

**Data-aligned taxonomy.** `sdd-pipeline scan-taxonomy` derives a section→field
taxonomy from the corpus's tables by document-frequency (`corpus_taxonomy.py`),
normalising field names through `header_norm.py`; `template_taxonomy.py` does the
same from the SAD template, and `doc_router.py` fingerprints a doc to pick which
taxonomy applies. Outputs land in `outbox/taxonomy/`; promote a reviewed
`taxonomy.json` into `config/` by hand. Pandoc-only, no model.

**Entity inventory pipeline.** When `inventory_enrichment` is on (default),
enrichment runs a three-source extraction — `extract_structural.py` (table cells),
`extract_prose.py` (regex + optional spaCy) — and `reconcile.py` unions/dedupes them
by confidence; `direction.py` routes each field into a section's `depends_on`/
`exposes`/`metadata` (folded into the embed text as high-value retrieval cues).

**Ingestion (`download`).** `sdd-pipeline download <manifest>` fetches manifest-listed
Confluence HTML / SharePoint docx into the inbox behind SiteMinder SSO
(cookie/form/bearer/none). Credentials are **secrets — env only** (`PIPELINE_DOWNLOAD_*`),
never CLI flags; the deterministic core never touches them. Needs the `[download]`
extra; exits non-zero on any failure so a CI ingest stage surfaces it.

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
A Word **docx→MD** path also lives here: `convert/docx_to_md.py` (`convert_docx_file`,
reusing `base.py`) is pandoc-native with media extraction + frontmatter harvested
from the docx core properties, exposed as the `sdd-pipeline convert-docx` command
and driven by the `.claude/skills/docToMd` skill.
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
`sdd-pipeline convert` CLI command batches this over `inbox/**/*.html` (the
default input is the inbox), writes `.md` under `outbox/md/`, and emits a JSON
report (`outbox/reports/conversion-report.json`) with per-file + aggregate
metrics (`sections`, `pictures`, `code_snippets`, `lists`, `tables`, `urls`).
`[[_TOC_]]` injection is opt-in via `--toc` (default OFF — a TOC paragraph is a
junk chunk in the embedding corpus).

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

**Gliffy → SVG resolver (`convert/gliffy_to_svg.py`).** A Confluence-embedded Gliffy
diagram is **JSON, not SVG**, and in a *rendered* HTML export it appears only as a
raster `<img>` — the editable vector data lives in a sibling page **attachment**
(`<name>.gliffy`, sometimes `<name>.svg`), never in the HTML the converter consumes
(which deliberately drops diagrams to a caption — see `_normalise_diagrams`). This
out-of-band resolver turns the on-disk attachment into editable SVG: `resolve_gliffy_file`
prefers an existing sibling `<name>.svg` (Gliffy's own export — exact fidelity), else
`render_gliffy` walks `stage.objects` and emits primitives. Coverage is **best-effort
basic-shape** (rectangle/round-rectangle/ellipse/diamond, poly-lines with arrowheads,
text labels, embedded raster/SVG); unknown stencils become dashed placeholders and bump
an `unsupported` count. It is independent of flow A *and* of the HTML/docx engine deps
(stdlib `json`/`re`/`html` only; reuses only `base.ConversionError`). The
`sdd-pipeline resolve-gliffy <dir>` CLI batches `inbox/**/*.gliffy` → `outbox/media/`
(mirroring the tree) and writes `outbox/reports/gliffy-report.json` whose `diagrams`
map (stem → svg path + method) is the manifest a future opt-in branch in
`_normalise_diagrams` would consume to emit `![caption](media/<name>.svg)` instead of
dropping the diagram. For complex stencil-heavy diagrams the high-fidelity route is
Gliffy's own SVG export or a draw.io import/export.

**Gliffy → draw.io emitter + fidelity harness (`convert/diagram_model.py`,
`convert/drawio.py`, `convert/fidelity.py`).** draw.io imports `.gliffy` natively but
**only in the online app** (no headless/CLI path), so it can't run in this pipeline
or CI. These modules give a reproducible, testable `.gliffy → .drawio` route plus a
way to prove it faithful. The shared **semantic model** (`diagram_model.DiagramModel`
— pure `Node`/`Edge` dataclasses + a canonical `to_dict()`: 2-dp floats, lowercased
colors, sorted-by-id, embedded-svg hashed) is the currency between three pieces:
`gliffy_to_svg.parse_gliffy` (Gliffy JSON → model; a **separate** walk from the SVG
renderer's `_walk`, sharing only `_object_geometry`, so the SVG path is byte-for-byte
unchanged), `drawio.model_to_drawio`/`drawio_to_model` (model ⇄ mxGraph XML; both
y-down/top-left so **no axis flip**; ids carried through so the round-trip matches by
id; the `placeholder` kind round-trips via a private `sddType=placeholder` style
marker), and `fidelity.compare_models`/`roundtrip_check`. **The fidelity oracle is
`roundtrip_check`** (parse → emit → re-parse → compare): it proves emitter⇄parser
*self-consistency*, **not** that draw.io-the-app renders the file (needs a human /
headless export) nor that `parse_gliffy` read Gliffy correctly (covered by separate
gliffy→model unit tests). A **secondary, optional** `png_regression_check`
(`[raster]` extra → cairosvg + pillow; lazy-imported, `slow`/`importorskip`-gated)
rasterizes the SVG renderer's output and pixel-diffs it against a golden — a drift
tripwire on `render_gliffy`, *not* cross-tool Gliffy-vs-draw.io equality. The
`sdd-pipeline convert-drawio <dir> [--check]` CLI batches `inbox/**/*.gliffy` →
`outbox/drawio/` and writes `outbox/reports/drawio-report.json`; `--check` runs the
round-trip per file and exits non-zero on any mismatch. Coverage is the same
best-effort basic-shape set as the SVG renderer (icon stencils → dashed placeholders);
for editable native draw.io shapes of complex diagrams, use draw.io's own Gliffy import.

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
- **`Genre`** (`models.py`, classified in `enrichment.py` via `lang_rules.py`): the
  prose *shape* of a section — `glossary`/`faq`/`howto`/`policy`/`narrative` (`general`
  is the null genre) — an axis **orthogonal** to `SectionType` (a Security FAQ is
  `section_type=security` + `genre=faq`). Embedded as a `genre:` header token for
  non-null genres and filterable via `search --genre`. `ContentType.DEFINITION`
  (recovered from pandoc DefinitionList) signals a glossary section.
- **Model-free lexical mode** (`--lexical`, config `lexical_only`): builds/searches a
  BM25-only index with **no embedding model loaded** — works for every language, and
  is the default for a lexical-built index. Distinct from `--hybrid` (which fuses dense
  + BM25 and still needs the model). Both go through `retrieval.py`.
- **`EMBED_FORMAT_VERSION`** (`models.py`, currently `4`): bump it in the same change
  that alters `to_embed_text`'s composition; it is recorded in the index provenance so
  a search over an index built with an older format warns to re-index.
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
- **MCP server for Copilot** (`sdd-pipeline mcp`, module `mcp_server.py`, optional
  `[mcp]` extra → the `mcp` SDK's FastMCP): a CLI-layer presentation wrapper over
  `SemanticPipeline` (like `tui`) that serves semantic search over **stdio** so
  GitHub Copilot's ADR-generator agent can RAG over the indexed corpus. It imports
  `mcp` only when the command runs, so core flows never pull it in; it imports only
  the public `SemanticPipeline` + enums (no `vector_store`/`embeddings`/`workspace`
  — the CLI command does path resolution), so **no guardrail is broken**. Five
  tools: `semantic_search` (full content; lean `section_type`/`space`/`hybrid`
  filters; `hybrid=None` defers to the server default — never forces it off),
  `find_decision_context` (snippets grouped onto the ADR template — a guaranteed
  `general` recall bucket plus precision buckets `context`/`decision`/
  `alternatives`/`tradeoffs`/`consequences`/`done_criteria`, deduped precision-first
  so a passage appears once), `find_sad_coverage` (does a decision + its named
  entities appear in the SAD? — `doc_type="sad"`-filtered, an entity+section **hard**
  match else a section-scoped semantic **soft** match, for the SAD-sync step), and
  `list_section_types`/`list_spaces`. Each tool's
  logic is a plain module function (`run_search`/`find_decision_context_impl`/
  `find_sad_coverage_impl`/`result_to_dict`/`resolve_section_type`/…), so the contract is unit-tested
  model-free via `hashing_embedder` (no MCP runtime) — see `tests/test_mcp_server.py`.
  The **stdio contract** keeps stdout for JSON-RPC: all diagnostics go to stderr,
  ASCII-only (Windows cp1252). `run_server` eagerly warms the model at startup
  (so the first call is fast and a provenance mismatch surfaces in the VS Code
  server log); an empty/unbuilt index makes the search tools raise an actionable
  error rather than silently returning `[]`. The embedder **must match the index
  provenance** (`_verify_provenance` raises on mismatch, surfaced as a clean tool
  error). Wired for Copilot via `.vscode/mcp.json` (registers the stdio server) +
  a step-0 retrieval instruction in `.github/agents/adr-generator.agent.md`
  (no `tools:` allowlist — that would strip the agent's file-writing).

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
- `workspace.py` (inbox/outbox path contract) is a CLI-layer concern — keep it
  imported only by `cli.py`/`dump.py`; never wire it into the deterministic core.
- `shell.py` (PowerShell 7 discovery) is a stdlib-only CLI-layer util (like
  `convert.base.resolve_pandoc`) — keep it imported only by `cli.py`; never wire it
  into the deterministic core.

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

## Shell tooling (PowerShell 7 discovery)

`shell.py` is the **single canonical** PowerShell-7 resolver — a stdlib-only,
**non-intrusive** CLI-layer util (mirrors `convert.base.resolve_pandoc`; imported by
`cli.py` only). `resolve_pwsh(config, *, min_major=0)` discovers `pwsh` without ever
editing `PATH`: an explicit `PIPELINE_PWSH_PATH` pin (**sticky** — if set it commits
to that path and never falls through; a missing pin surfaces as
`source="config-missing"`), then `which pwsh` → `which pwsh-preview` → well-known
install dirs → Windows PowerShell 5.1 (**Windows only**). It confirms a candidate by
*invoking* it (`pwsh -NoProfile -NoLogo -Command $PSVersionTable…`, arg-list, no
shell) and returns a frozen `PwshInfo(path, version, major, source)` with `is_v7` /
`usable` properties. `min_major` *filters* (skip-and-continue): `0` returns the first
existing candidate (so the diagnostic can show a broken/old/5.1 install), `7` returns
only v7+, `1` the first usable of any version.

The Python core never *needs* pwsh today (pandoc is the only subprocess); this is a
**diagnostic + groundwork** layer that any future pwsh-launching code routes through.
Two surfaces consume it:
- **`sdd-pipeline check`** appends an *informational* pwsh row (`version @ path
  (source)`, or `not v7` / `not found` / broken-pin) — `ok=True` always, so it never
  changes the exit code (the optional-row convention).
- **`sdd-pipeline pwsh-path`** prints just the resolved path for scripts to capture
  (`$env:PWSH = (sdd-pipeline pwsh-path)`): enforces v7 by default (exit 1 + a stderr
  diagnostic + empty stdout when none), `--allow-any` accepts any usable version.

## Configuration

Settings load from env vars (prefix `PIPELINE_`) or `.env` via
`PipelineConfig` (pydantic-settings). Common: `PIPELINE_EMBEDDING_MODEL`,
`PIPELINE_VECTOR_STORE_BACKEND` (`memory` default | `chroma`),
`PIPELINE_CHROMA_PERSIST_DIR` (the persist dir for **both** backends, despite
the name; default `./outbox/index` — must stay under the outbox),
`PIPELINE_INBOX_DIR` / `PIPELINE_OUTBOX_DIR` / `PIPELINE_ENFORCE_WORKSPACE`
(the workspace contract; see the *Workspace contract* section),
`PIPELINE_MAX_CHUNK_CHARS`,
`PIPELINE_PANDOC_FROM_FORMAT`, `PIPELINE_ENTITY_TERMS` (JSON array of domain
vocabulary), `PIPELINE_ENTITY_VOCAB_PATH` (JSON vocabulary file; enables the
two-pass cross-corpus scan in `index`/`export` — `config/entity-vocab.json` is a
committed seed example with project terms like `XCom`/`triggerer`/`KPO`),
`PIPELINE_EMBED_CHAR_BUDGET`, `PIPELINE_CHUNK_MERGE_DEFINITIONS`,
`PIPELINE_HYBRID_SEARCH` (+ `PIPELINE_HYBRID_CANDIDATE_POOL`, `PIPELINE_RRF_K`),
`PIPELINE_PWSH_PATH` (explicit PowerShell 7 path for the shell resolver; *sticky*
when set, empty = auto-discover; non-intrusive, never edits PATH — see *Shell
tooling*).
Robustness gates: `PIPELINE_CHUNK_GATE` (default on — poison blocks the file),
`PIPELINE_EMBED_CHAR_HARD_CAP` (default 2048 — over it the chunk gate warns of
likely truncation), `PIPELINE_CONVERT_QUARANTINE` (default on) +
`PIPELINE_CONVERT_MAX_UNRECOGNIZED` (default 8) for the converter confidence gate.
New config fields must be added to **both** `PipelineConfig` branches
(pydantic-settings v2 and the pydantic-v1 fallback) **and** documented in
`docs/reference/configuration.md` (the CI doc-health check enforces both). The full,
authoritative field list lives there; other notable groups not called out above:
`PIPELINE_LANGUAGE` + `PIPELINE_LEXICAL_ONLY` / `PIPELINE_LEXICAL_STEMMING`
(multilingual / model-free), `PIPELINE_INVENTORY_ENRICHMENT`, the `PIPELINE_DOWNLOAD_*`
ingestion secrets, and the advisory `PIPELINE_DOC_PROFILE_*` / `PIPELINE_PROSE_*`
chunking knobs.

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

## GitHub Copilot integration

Each **project-specific** skill is authored **once** as a portable `SKILL.md` folder
under `.claude/skills/` and read **natively** by both Claude Code and GitHub Copilot —
they follow the [Agent Skills](https://agentskills.io) open standard, and `.claude/skills/`
is the one project directory both tools discover (Claude Code reads only `.claude/skills/`
+ plugins; Copilot reads `.github/skills/`, `.claude/skills/`, or `.agents/skills/`). So
`.claude/skills/` is the **single source of truth** for our own skills — it is the **one
tracked exception** to the otherwise-gitignored `.claude/` (see `.gitignore`). The
`.github/` assets are now only the things with **no** `.claude/skills/` equivalent:
Copilot-only **ports of Claude's bundled/plugin skills** (Claude Code already has those
built-in), the scoped instruction guardrails, the custom agent, and the MCP wiring.

| Asset | Path | Role |
|---|---|---|
| Agent Skills | `.claude/skills/*/SKILL.md` | the project skills (`doc-to-md`, `docs-sync`), invoked as `/<name>` in **both** Claude Code and Copilot Chat. Tracked; the single source of truth. |
| Prompt files | `.github/prompts/*.prompt.md` | Copilot-only ports of Claude's bundled/plugin skills, invoked as `/<name>` in Copilot Chat (`convert-confluence`, `index-corpus`, `code-review`, `simplify`, `security-review`, `verify-change`, `grill-me`, `gitlab-mr`, `copilot-context`). `.github/prompts/README.md` lists the port + the Claude-Code-only skills deliberately **not** ported. |
| Instruction files | `.github/instructions/*.instructions.md` | scoped guardrails auto-applied by `applyTo` glob — `python` (module boundaries/determinism), `tests` (markers/fixtures), `docs` (doc-health), `copilot-assets` (the conventions the gate below enforces). |
| Custom agent | `.github/agents/adr-generator.agent.md` | the ADR Generator persona (grounds ADRs via the `sdd-semantic` MCP server). |
| Repo-wide rules | `.github/copilot-instructions.md` | always-on Copilot instructions + the Know How wiki agent. |
| MCP server | `.vscode/mcp.json` | registers the `sdd-semantic` stdio server (`sdd-pipeline mcp --lexical`). |

These assets are kept honest by `src/tools/scripts/check_copilot.py` — a deterministic,
model-free gate (sibling of `check_docs.py`): C1 frontmatter present (prompts need a
`description`, agents `name`+`description` and any `agents:` refs resolve, instructions
`applyTo`), C2 every `sdd-pipeline <cmd>` in a code span is a real CLI command, C3 the
`.vscode/mcp.json` wiring is valid and every referenced MCP tool (`tool_name(...)`)
exists, C4 links resolve, C5 fences/frontmatter are well-formed, **C6** every
`.claude/skills/*/SKILL.md` has spec-valid frontmatter (`name` matching its dir +
grammar/length, `description` ≤1024 chars) — and C2/C4/C5 also cover the skill bodies.
It runs in the GitLab `verify:quality` stage and the GitHub `copilot-health` workflow,
so a broken skill or Copilot asset cannot merge (self-tested by
`tests/test_check_copilot.py`). VS Code discovery is enabled in `.vscode/settings.json`
(`chat.agentSkillsLocations` for skills, `chat.promptFiles`, the instruction-files
locations).

## Documentation

All human-facing docs live under `docs/` as Markdown (the single source) and render
with **MkDocs Material** (the `[docs]` extra → `mkdocs serve` for a local searchable
site; `mkdocs build` → `./site`). The site is **published as GitLab Pages** by the
`pages` job in `.gitlab-ci.yml` (`mkdocs build --strict --site-dir public` on the
default branch → served at `https://<namespace>.gitlab.io/<project>/`); the same
`--strict` build also runs as a *check* in `verify:quality`. `README.md` + `CLAUDE.md`
stay canonical at the repo root and are surfaced in-site via include-stubs
(`docs/_root/`). The authoritative
per-command and per-setting references are `docs/reference/cli.md` and
`docs/reference/configuration.md` — **when you add or change a CLI command/flag or a
`PipelineConfig` field, update the matching reference page** (the README CLI section
and CLAUDE module map point at them rather than duplicating).

Docs are kept honest by `src/tools/scripts/check_docs.py` (pure-stdlib, no
LLM/model/pandoc): it asserts the docs are **not broken** (intra-docs + source-file
links resolve, `mkdocs build --strict` for nav/render) **and updated** (every CLI
command/flag is in `cli.md`, every `PIPELINE_*` field is in `configuration.md`, every
`module.py::symbol` citation in `learn/` resolves). It runs in the CI `verify` stage
alongside `mkdocs build --strict`, so a stale or broken doc cannot merge. The
on-demand `.claude/skills/docs-sync` skill reconciles docs↔code and logs to
`docs/guides/log.md`. (It is a tracked portable Agent Skill — see *GitHub Copilot
integration* — but the enforceable guarantee remains `check_docs.py` + CI.)
