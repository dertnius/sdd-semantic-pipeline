# SDD Semantic Pipeline

A 7-stage pipeline that turns **Confluence-exported markdown files** into a
**semantic vector search index** optimised for Software Design Documents.

```
Confluence MD → pandoc AST → Structural model → Semantic enrichment
             → Chunking → Embeddings → Vector search
               (in-memory store by default; ChromaDB optional)
```

---

## Quick start

Drop your source files under **`inbox/`** and let every command default to it;
all outputs land under **`outbox/`** (see [Workspace contract](#workspace-contract)).

```bash
# 0 – Convert Confluence HTML exports (in inbox/) → GitLab Markdown (outbox/md/)
#     + a JSON report (per-file section/picture/code/list/table/URL counts)
sdd-pipeline convert            # reads inbox/, writes outbox/md + outbox/reports/

# 1 – Index the converted corpus (or any .md under inbox/)
sdd-pipeline index inbox/sample/ --model all-MiniLM-L6-v2   # → outbox/index/

# 2 – Search
sdd-pipeline search "how does token refresh work?"
sdd-pipeline search "rate limiting algorithm" --section-type architecture

# 3 – Verify environment
sdd-pipeline check

# Model-free extras (pandoc only, no embedding model loaded):
# export chunks for reuse by another pipeline …
sdd-pipeline export inbox/sample/ --merge-prose             # → outbox/chunks/
# … or discover the cross-corpus entity vocabulary for review before indexing
sdd-pipeline scan inbox/sample/                             # → outbox/vocab/
```

> `convert` scans the input directory recursively for `*.html`, writes a `.md`
> per file, and emits a JSON report with per-file and aggregate metrics. See
> [docs/Convert.Linux.Readme.md](docs/Convert.Linux.Readme.md) /
> [docs/Convert.Windows.Readme.md](docs/Convert.Windows.Readme.md) for details.

See **[CLI reference](#cli-reference)** below for every command and flag. The
full, always-current option list is `sdd-pipeline <command> --help`.

---

## Workspace contract

The pipeline operates a two-zone workspace, enforced by default:

- **`inbox/`** — every file going **into** the pipeline lives here (subfolders
  allowed, e.g. `inbox/sample/`). Raw HTML for `convert`, `.md` for
  `index`/`export`/`lint`/`scan`.
- **`outbox/`** — every artifact the pipeline produces lands here, under a fixed
  sub-layout:

  | Subfolder | Produced by |
  |---|---|
  | `outbox/index/` | `index --output`; read by `search`/`tui --index` |
  | `outbox/md/` | `convert --output` (converted markdown) |
  | `outbox/chunks/` | `export --output` (exported chunks) |
  | `outbox/reports/` | `convert`/`lint` JSON reports |
  | `outbox/vocab/` | `scan --vocab` (entity vocabulary) |
  | `outbox/taxonomy/` | `scan-taxonomy` (taxonomy + field vocabulary) |
  | `outbox/dump/` | `python -m sdd_pipeline.dump` |

Every command **defaults** to these zones, so a bare `sdd-pipeline convert` or
`sdd-pipeline index inbox/sample/` needs no path flags. With enforcement on
(default), an input outside `inbox/` or an output outside `outbox/` is **rejected**
with a clear error (exit 2). Set `PIPELINE_ENFORCE_WORKSPACE=false` to bypass the
contract (used by tests and ad-hoc runs), or point the roots elsewhere with
`PIPELINE_INBOX_DIR` / `PIPELINE_OUTBOX_DIR`.

> The `scan`/`scan-taxonomy` discovery outputs land in `outbox/vocab/` and
> `outbox/taxonomy/`. To feed a reviewed vocabulary/taxonomy back as committed
> config, copy it into `config/` by hand (e.g.
> `config/entity-vocab.json`) — `config/` is committed configuration, not a
> pipeline output zone. The committed seed is still read via
> `PIPELINE_ENTITY_VOCAB_PATH`.

---

## CLI reference

Eight commands: `index`, `search`, `convert`, `export`, `scan`, `scan-taxonomy`,
`lint`, `check`. Only `index` and `search` load an embedding model; `convert`,
`export`, `scan`, and `scan-taxonomy` are **pandoc-only** (no model download),
and `lint` is **pure text** (neither pandoc nor a model).

### `index` — build the vector index

```bash
sdd-pipeline index [input_dir] [options]
```

`input_dir` defaults to the **inbox** (`inbox/`); pass a subfolder like
`inbox/sample/` to narrow it.

| Option | Default | Description |
|---|---|---|
| `--output` / `-o` | `outbox/index` | Vector index persistence path (under the outbox) |
| `--model` / `-m` | `BAAI/bge-large-en-v1.5` | Local embedding model (ignored when `--provider azure`) |
| `--provider` | `local` | Embedding backend: `local` \| `azure` |
| `--backend` | `memory` | Vector store backend: `memory` \| `chroma` (chroma needs `pip install ".[chroma]"`) |
| `--glob` / `-g` | `**/*.md` | File glob pattern |
| `--merge-prose` | off | Pack each section's prose into one chunk (code/tables stay separate) |
| `--merge-definitions` | off | Pack prose **and** code into one chunk (tables separate); overrides `--merge-prose` |
| `--chunk-gate` / `--no-chunk-gate` | on (`PIPELINE_CHUNK_GATE`) | Hygiene gate: a **poisoned** chunk (markup/macro residue, or empty) blocks the whole file from the index |
| `--dry-run` | off | Parse + chunk without indexing (no model loaded) |
| `--verbose` / `-v` | off | Per-file chunk counts |

> **Chunk hygiene gate (on by default):** before embedding, every chunk's rendered
> `embed_text` is checked for markup/macro residue and emptiness; a poisoned chunk
> *blocks the whole file* (raising rather than silently indexing a broken vector).
> Over-budget chunks only *warn*. Pass `--no-chunk-gate` (or `PIPELINE_CHUNK_GATE=false`)
> to override.

> When `PIPELINE_ENTITY_VOCAB_PATH` is set, `index` runs a two-pass cross-corpus
> scan first (discover + persist the entity vocabulary, then enrich every doc
> with it). See [Configuration](#configuration).

### `search` — query the index

```bash
sdd-pipeline search "<query>" [options]
```

| Option | Default | Description |
|---|---|---|
| `--index` / `-i` | `outbox/index` | Vector index path to query (under the outbox) |
| `--model` / `-m` | `BAAI/bge-large-en-v1.5` | Embedding model (**must match the index**) |
| `--provider` | `local` | Embedding backend: `local` \| `azure` (must match the index) |
| `--backend` | `memory` | Vector store backend: `memory` \| `chroma` (must match the index) |
| `--top-k` / `-k` | `5` | Number of results |
| `--section-type` / `-s` | — | Filter by type (see list below) |
| `--space` | — | Filter by Confluence space key |
| `--hybrid` / `-H` | off | Fuse dense + lexical (BM25) rankings via Reciprocal Rank Fusion |

`--section-type` values: `overview`, `architecture`, `api`, `decision`,
`alternative`, `tradeoff`, `consequence`, `done_criteria`, `deployment`,
`data_model`, `security`.

> `search` verifies the index's recorded `(provider, model, dimension)` and
> errors if your configured embedder differs from the one that built the index —
> re-index or align `--provider`/`--model` to fix.

### `convert` — HTML → GitLab Markdown (batch)

```bash
sdd-pipeline convert [input_dir] [options]
```

`input_dir` defaults to the **inbox** (`inbox/`).

| Option | Default | Description |
|---|---|---|
| `--output` / `-o` | `outbox/md` | Output directory for `.md` (mirrors input tree) |
| `--glob` / `-g` | `**/*.html` | HTML glob pattern |
| `--report` / `-r` | `outbox/reports/conversion-report.json` | JSON report path |
| `--selector` | auto-detect | CSS selector for the main content region |
| `--space` | — | Confluence space key → frontmatter (provenance) |
| `--source-url` | — | Canonical source URL → frontmatter (provenance) |
| `--labels` | — | Comma-separated labels → frontmatter (provenance) |
| `--no-frontmatter` | off | Skip the YAML frontmatter block |
| `--toc` | off | Inject `[[_TOC_]]` (opt-in; default OFF for the embedding corpus) |
| `--keep-diagrams` | off | Keep SVG diagram HTML instead of a placeholder |
| `--quarantine` / `--no-quarantine` | on (`PIPELINE_CONVERT_QUARANTINE`) | Route low-confidence conversions to `_quarantine/` and exit non-zero (see below) |
| `--max-unrecognized` | `8` (`PIPELINE_CONVERT_MAX_UNRECOGNIZED`) | Quarantine when dropped/unrecognised-construct count exceeds this |
| `--pandoc-path` | auto (`PATH`) | Path to a specific pandoc binary |
| `--verbose` / `-v` | off | Per-file metric summary line |

> **Scope — rendered HTML only.** `convert` handles *rendered* Confluence exports
> (Space export / "Export to HTML"). Storage-format input (`ac:`/`ri:`/`at:` XML
> from the REST `body.storage` or page templates) is **refused at the door** with a
> clear error rather than silently mangled (lxml drops its CDATA macro bodies).
>
> **Confidence gate (quarantine).** When the converter's own signals say it likely
> mangled a page — no recognised content container (it fell back to `<body>`), or
> more than `--max-unrecognized` leftover storage tags — the file is written to an
> `_quarantine/` subdir (not the corpus), marked `status: "quarantined"` in the
> report with reasons, and the command exits non-zero. Calibrate `--max-unrecognized`
> from a run over your known-good corpus, or disable with `--no-quarantine`.

### `export` — chunks to JSON/JSONL (model-free)

Runs the deterministic stages only (pandoc → structural → enrich → chunk); **no
embedding model is loaded**. Writes a `.chunks.json`/`.jsonl` per file plus an
`export-report.json`, for reuse by another pipeline.

```bash
sdd-pipeline export [input_dir] [options]
```

`input_dir` defaults to the **inbox** (`inbox/`).

| Option | Default | Description |
|---|---|---|
| `--output` / `-o` | `outbox/chunks` | Directory for `.chunks.json`/`.jsonl` (mirrors input tree) |
| `--format` / `-f` | `json` | Output format: `json` \| `jsonl` |
| `--glob` / `-g` | `**/*.md` | Markdown glob pattern |
| `--merge-prose` | off | Pack each section's prose into one chunk (code/tables separate) |
| `--merge-definitions` | off | Pack prose **and** code into one chunk; overrides `--merge-prose` |
| `--report` / `-r` | `<output>/export-report.json` | JSON report path (co-located with the chunks) |
| `--verbose` / `-v` | off | Per-file chunk counts |

> Prefer `--merge-prose` (or `--merge-definitions` for reference/spec docs) for
> export — it drops context-free fragment chunks that otherwise pollute a
> downstream index. With `PIPELINE_ENTITY_VOCAB_PATH` set, the two-pass
> cross-corpus scan runs first (still model-free).

### `scan` — discover the entity vocabulary (model-free)

Parses every doc, scans for entity candidates across the whole corpus, merges
the persisted vocabulary + `PIPELINE_ENTITY_TERMS`, and writes the sorted result
to the vocabulary JSON — for review/editing before an `index` run. **No model.**

```bash
sdd-pipeline scan [input_dir] [options]
```

`input_dir` defaults to the **inbox** (`inbox/`).

| Option | Default | Description |
|---|---|---|
| `--vocab` | `outbox/vocab/entity-vocab.json` | Output JSON vocabulary file (or `PIPELINE_ENTITY_VOCAB_PATH`) |
| `--glob` / `-g` | `**/*.md` | Markdown glob pattern |
| `--verbose` / `-v` | off | Print the discovered term list |

> Promote a reviewed vocabulary into committed config by copying it to
> `config/entity-vocab.json`, then point `PIPELINE_ENTITY_VOCAB_PATH` at it.

### `scan-taxonomy` — derive a section→field taxonomy (model-free)

Scans every doc's **tables**, aggregates field names by document-frequency, keeps
fields seen in ≥ `--min-docs` documents, and writes a canonical taxonomy plus a
frequency-ranked field vocabulary for review (used to fill
`config/field_directions.yaml`). **Pandoc-only: no model.**

```bash
sdd-pipeline scan-taxonomy [input_dir] [options]
```

`input_dir` defaults to the **inbox** (`inbox/`).

| Option | Default | Description |
|---|---|---|
| `--out` / `-o` | `outbox/taxonomy/taxonomy.json` | Output taxonomy JSON (section → fields) |
| `--vocab-out` | `outbox/taxonomy/field_vocabulary.json` | Frequency-ranked field vocabulary (review artifact) |
| `--min-docs` / `-n` | `2` | Keep a field only if seen in ≥ this many documents |
| `--glob` / `-g` | `**/*.md` | Markdown glob pattern |

### `lint` — audit raw `.md` quality (report-only)

Scans raw source markdown for embedding-harmful residue — leaked HTML tags,
untranslated Confluence macros, whole-doc code dumps, TOC/nav link-dumps,
near-empty stubs, and empty section headings — and writes a `quality-report.json`.
**Pure text analysis: no pandoc, no model.** It never drops or rewrites anything.
Point it at your real embedding corpus (not a docs tree that *documents*
Confluence syntax — those files legitimately contain the flagged tokens).

```bash
sdd-pipeline lint [input_dir] [options]
```

`input_dir` defaults to the **inbox** (`inbox/`).

| Option | Default | Description |
|---|---|---|
| `--glob` / `-g` | `**/*.md` | Markdown glob pattern |
| `--report` / `-r` | `outbox/reports/quality-report.json` | JSON report path (under the outbox, never the input tree) |
| `--strict` | off | Exit non-zero if any file has a block-severity issue |
| `--verbose` / `-v` | off | Per-file findings |

> Exit code is `0` by default (finding issues isn't a failure), `1` if a file
> can't be read, and `1` under `--strict` when any block-severity issue exists.
> Thresholds are tuned in `quality.py` — calibrate them against your corpus.
>
> `lint` is a **pre-filter on raw markdown**; the *binding* gate is the chunk-level
> hygiene check that runs inside `index` (on the produced chunks, after merge/split)
> and blocks poisoned files — see the `index` command above.

### `check` — verify the environment

```bash
sdd-pipeline check
```

Reports Python, pandoc, and each Python dependency, plus optional `chromadb`
and `openai` availability and whether the Azure env vars are set (the API key
value is never printed). Exits non-zero if a required dependency is missing.

---

## Full pipeline (end-to-end)

The commands chain into one flow. **M** = loads an embedding model, **P** = needs
pandoc. Steps 3–4 are optional; only `index`/`search` load a model. A minimal run
is `convert → index → search`.

Place the source HTML/MD under `inbox/` first. The defaults below land every
artifact in `outbox/`, so the explicit `-o`/`-r` flags shown are optional.

| # | Command | Input required | Output expected | M | P |
|---|---|---|---|:--:|:--:|
| 0 | `sdd-pipeline check` | — | dependency table (stdout); exit 1 if a required dep is missing | – | – |
| 1 | `sdd-pipeline convert [inbox/] [--space K --source-url U --labels a,b]` | dir of `*.html` (default `inbox/`); **pandoc on PATH** | one `.md` per HTML in `outbox/md/` (mirrors tree) + `outbox/reports/conversion-report.json` (per-file + aggregate metrics, macro counts, warnings) | – | ● |
| 2 | `sdd-pipeline lint [inbox/] [--strict]` | dir of `*.md` (e.g. the converted corpus under `inbox/`) | `outbox/reports/quality-report.json` + stdout summary; `--strict` → exit 1 on any block issue | – | – |
| 3a | `sdd-pipeline scan [inbox/]` *(optional)* | `*.md` dir; **pandoc** | entity-vocabulary JSON in `outbox/vocab/` (sorted terms) to review before indexing | – | ● |
| 3b | `sdd-pipeline scan-taxonomy [inbox/] [-n 2]` *(optional)* | `*.md` dir; **pandoc** | `outbox/taxonomy/taxonomy.json` (section → field) + `outbox/taxonomy/field_vocabulary.json` | – | ● |
| 4 | `sdd-pipeline export [inbox/] --merge-prose [-f jsonl]` *(optional)* | `*.md` dir; honours `PIPELINE_ENTITY_VOCAB_PATH` (two-pass) | `.chunks.json`/`.jsonl` per file in `outbox/chunks/` + `export-report.json` | – | ● |
| 5 | `sdd-pipeline index inbox/ --model all-MiniLM-L6-v2 [--backend chroma\|memory --merge-prose]` | `*.md` dir; **embedding model** (downloads on first run); chromadb if `--backend chroma`; optional `PIPELINE_ENTITY_VOCAB_PATH` | vector index at `outbox/index/` (memory: `<dir>/<collection>.json` + `.provenance.json`; chroma: persist dir) | ● | – |
| 6 | `sdd-pipeline search "<query>" --model all-MiniLM-L6-v2 [-k 5 -s architecture --space ARCH --hybrid]` | **prior index** at `outbox/index/` (provider/model/backend must match) + embedding model | results table (score, breadcrumb, type, preview) on stdout | ● | – |

**Dependencies:** `search` requires a prior `index` (same provider/model/backend);
`index`/`export` consume the vocabulary from `scan` when `PIPELINE_ENTITY_VOCAB_PATH`
is set; `lint` gates the corpus after `convert`; `check` and `scan-taxonomy` are
standalone.

---

## Vector store backends

The store is pluggable via `--backend` (`memory` default \| `chroma`) on
`index` and `search`, or `PIPELINE_VECTOR_STORE_BACKEND`.

- **memory** — langchain-core's `InMemoryVectorStore`, persisted as
  `<persist-dir>/<collection>.json` plus a `<collection>.provenance.json`
  sidecar, so `index` → `search` across separate runs works. Default; no
  optional dependencies. Holds the index in RAM — right-sized for SDD corpora.
- **chroma** — ChromaDB via the **optional** `chromadb` package:
  `pip install ".[chroma]"`. Use for larger corpora or when you already have a
  Chroma index.

The backend used by `search` must match the one that built the index; the two
backends keep **independent** indexes even in the same persist dir, so
re-index after switching.

```bash
sdd-pipeline index inbox/sample/ --backend chroma
sdd-pipeline search "token refresh" --backend chroma
```

---

## Embedding providers

The embedder is pluggable via `--provider` (`local` default \| `azure`) on
`index` and `search`.

- **local** — sentence-transformers (`--model`, e.g. `all-MiniLM-L6-v2`). The
  first run downloads the model.
- **azure** — Azure OpenAI embeddings via the **optional** `openai` SDK
  (`pip install ".[azure]"`). No local download. Credentials come from **env
  only** (never CLI flags):

  | Variable | Description |
  |---|---|
  | `PIPELINE_AZURE_OPENAI_ENDPOINT` | `https://<resource>.openai.azure.com/` |
  | `PIPELINE_AZURE_OPENAI_DEPLOYMENT` | Embeddings deployment (used as the model) |
  | `PIPELINE_AZURE_OPENAI_API_KEY` | API key (secret) |
  | `PIPELINE_AZURE_OPENAI_API_VERSION` | Optional (default `2024-10-21`) |

  With `--provider azure` the deployment **is** the embedding model, so `--model`
  is ignored. The configured provider/model must match the one that built the
  index (see `search` above).

```bash
sdd-pipeline index inbox/sample/ --provider azure
sdd-pipeline search "token refresh" --provider azure
```

---

## Environment setup

### Option A — Windows 11 with conda or micromamba

Recommended for local development on Windows.  Conda installs the `pandoc`
binary automatically via conda-forge, so no separate installer is needed.

```powershell
# Clone
git clone https://github.com/your-org/sdd-semantic-pipeline
cd sdd-semantic-pipeline

# Create environment (Miniconda / Anaconda)
conda env create -f environment.yml

# — OR — with micromamba (faster)
micromamba env create -f environment.yml

# Activate
conda activate sdd-pipeline
# micromamba activate sdd-pipeline

# Verify
sdd-pipeline check
```

> **Note:** The first `sdd-pipeline index` run downloads the embedding model
> (~1.3 GB for `BAAI/bge-large-en-v1.5`).  Use `--model all-MiniLM-L6-v2`
> (~80 MB) during development.

#### Updating the environment after a pull

```powershell
conda env update -f environment.yml --prune
```

---

### Option B — Remote devfile (OpenShift Dev Spaces / Eclipse Che)

The `devfile.yaml` at the repo root is picked up automatically when you open
the repository URL in Dev Spaces.

1. Navigate to your Dev Spaces instance.
2. Paste the repo URL → **Create Workspace**.
3. The `bootstrap` command runs automatically (`postStart` event):
   - Installs `pandoc` via `apt-get`
   - Runs `pip install -e ".[dev]"`
4. Open a terminal and run:
   ```bash
   sdd-pipeline check
   sdd-pipeline index inbox/sample/ --model all-MiniLM-L6-v2
   ```

#### Available devfile commands (Command Palette → *Run Task*)

| Command | What it does |
|---|---|
| `bootstrap` | Install pandoc + pip deps (runs on postStart) |
| `check` | Verify all dependencies |
| `test` | Unit tests (no pandoc / ML required) |
| `test-all` | All tests including slow integration |
| `index-samples` | Index `inbox/sample/` |
| `search-demo` | Run a demo search query |
| `lint` | ruff format + check |

---

### Option C — VS Code Dev Container (Docker Desktop)

Requires Docker Desktop on Windows / Mac / Linux.

1. Install the **Dev Containers** extension in VS Code.
2. Open the repo folder → VS Code detects `.devcontainer/devcontainer.json`.
3. Click **Reopen in Container**.
4. The `postCreateCommand` installs all dependencies automatically.

---

## Pipeline stages

| Stage | Module | Input → Output |
|---|---|---|
| 1 | *(external)* | Confluence page → `.md` file |
| 2 | `ast_parser` | `.md` → pandoc JSON AST (`dict`) |
| 3+4 | `structural` | AST → `DocumentModel` (section tree) |
| 5 | `enrichment` | `DocumentModel` → enriched with `SectionType`, entities, tags |
| 6 | `chunking` | `DocumentModel` → `list[SemanticChunk]` |
| 7a | `embeddings` | `list[SemanticChunk]` → `list[list[float]]` |
| 7b | `vector_store` | chunks + embeddings → vector index (`memory` default \| `chroma`) |

### Embed-text format

Each chunk is embedded using its structural context, not raw content
(`SemanticChunk.to_embed_text`):

```
[section_type] breadcrumb > path | keywords: … | tags: …

actual chunk content
```

Example:
```
[architecture] Auth Service > Architecture | tags: lang:python

Stateless JWT-based microservice deployed on Kubernetes.
The AuthService calls UserService for credential validation.
```

The header is kept lean for vector quality: the `[type]` prefix is omitted for
the null `content` type, the redundant section-type tag is dropped, keywords that
merely repeat a breadcrumb token are dropped, and only trusted `lang:` tags are
embedded. Data **tables** are summarized (header row + `(table, N data rows)`) so
high-entropy cells don't dominate the vector — the full table stays in `content`.

---

## Python API

```python
from pathlib import Path
from sdd_pipeline import SemanticPipeline, PipelineConfig, SectionType

config = PipelineConfig(
    embedding_model="all-MiniLM-L6-v2",
    chroma_persist_dir="./outbox/index",
)
pipeline = SemanticPipeline(config=config)

# Index a directory. The Python API takes explicit paths and does NOT enforce
# the inbox/outbox contract — that guard is a CLI-layer convenience.
counts = pipeline.index_directory(Path("inbox/sample/"))
print(counts)   # {'inbox/sample/auth-service.md': 34, 'inbox/sample/api-gateway.md': 28}

# Search
results = pipeline.search(
    "how does token refresh work?",
    n_results=5,
    section_type=SectionType.API,
)
for r in results:
    print(f"{r.score:.3f}  {r.metadata['breadcrumb']}")
    print(r.content[:200])
    print()
```

---

## Configuration

All settings can be set via environment variables (prefix `PIPELINE_`) or a `.env` file.
Copy `.env.example` to `.env` and customise. Full list in
[`config.py`](src/sdd_pipeline/config.py):

| Variable | Default | Description |
|---|---|---|
| `PIPELINE_PANDOC_FROM_FORMAT` | `gfm` | pandoc `--from` format |
| `PIPELINE_EMBEDDING_MODEL` | `BAAI/bge-large-en-v1.5` | sentence-transformers model |
| `PIPELINE_EMBEDDING_PROVIDER` | `local` | Embedding backend: `local` \| `azure` |
| `PIPELINE_EMBEDDING_BATCH_SIZE` | `32` | Encoding batch size |
| `PIPELINE_MAX_CHUNK_CHARS` | `2000` | Max characters per chunk before splitting |
| `PIPELINE_EMBED_CHAR_BUDGET` | `1800` | Target max chars for rendered `embed_text` (over-budget chunks warn) |
| `PIPELINE_EMBED_CHAR_HARD_CAP` | `2048` | Above this the model likely truncates the vector — the chunk gate *warns* (truncation is not certifiable model-free; chunking owns budget) |
| `PIPELINE_CHUNK_GATE` | `true` | Block a file from the index when a chunk is poisoned (markup/macro residue, or empty) |
| `PIPELINE_CONVERT_QUARANTINE` | `true` | Quarantine low-confidence conversions in `convert` (see the `convert` command) |
| `PIPELINE_CONVERT_MAX_UNRECOGNIZED` | `8` | Quarantine threshold for dropped/unrecognised constructs in `convert` |
| `PIPELINE_CHUNK_MERGE_PROSE` | `false` | Pack a section's prose into one chunk |
| `PIPELINE_CHUNK_MERGE_DEFINITIONS` | `false` | Pack prose + code into one chunk (overrides merge-prose) |
| `PIPELINE_ENTITY_TERMS` | `[]` | JSON array of domain vocabulary folded into entity extraction |
| `PIPELINE_ENTITY_VOCAB_PATH` | `""` | JSON vocab file; when set, enables the two-pass cross-corpus scan in `index`/`export` |
| `PIPELINE_VECTOR_STORE_BACKEND` | `memory` | Vector store backend: `memory` \| `chroma` |
| `PIPELINE_CHROMA_PERSIST_DIR` | `./outbox/index` | Vector index persistence path (both backends; must stay under the outbox) |
| `PIPELINE_COLLECTION_NAME` | `sdd_docs` | Vector store collection |
| `PIPELINE_INBOX_DIR` | `./inbox` | Root for all pipeline inputs (workspace contract) |
| `PIPELINE_OUTBOX_DIR` | `./outbox` | Root for all pipeline outputs (workspace contract) |
| `PIPELINE_ENFORCE_WORKSPACE` | `true` | Reject inputs outside `inbox/` and outputs outside `outbox/`; set `false` to bypass |
| `PIPELINE_HYBRID_SEARCH` | `false` | Fuse dense + lexical (BM25) rankings via RRF (same as `search --hybrid`) |
| `PIPELINE_HYBRID_CANDIDATE_POOL` | `50` | Per-scorer candidate depth fused before top-k |
| `PIPELINE_RRF_K` | `60` | Reciprocal Rank Fusion constant (higher = flatter weighting) |
| `PIPELINE_AZURE_OPENAI_ENDPOINT` | `""` | Azure OpenAI endpoint (provider `azure` only) |
| `PIPELINE_AZURE_OPENAI_DEPLOYMENT` | `""` | Azure embeddings deployment (used as the model) |
| `PIPELINE_AZURE_OPENAI_API_KEY` | `""` | Azure OpenAI API key (**secret**) |
| `PIPELINE_AZURE_OPENAI_API_VERSION` | `2024-10-21` | Azure OpenAI API version |

---

## Testing

```bash
# Fast unit tests (no pandoc / ML model required)
pytest -m "not slow"

# With coverage
pytest -m "not slow" --cov=sdd_pipeline --cov-report=term-missing

# All tests including integration (requires pandoc on PATH)
pytest

# Run a specific test
pytest tests/test_enrichment.py -v -k "test_extract_entities"
```

### Test markers

| Marker | When to use |
|---|---|
| *(none)* | Fast unit tests; always run |
| `slow` | Requires pandoc binary or real ML model |
| `integration` | Full end-to-end with all services |

---

## Project structure

```
sdd-semantic-pipeline/
├── src/
│   ├── sdd_pipeline/         ← the shipped package (flow A indexing + flow B convert)
│   │   ├── __init__.py       ← public API exports
│   │   ├── config.py         ← PipelineConfig (pydantic-settings)
│   │   ├── models.py         ← data types only (no external deps)
│   │   ├── ast_parser.py     ← pandoc subprocess wrapper
│   │   ├── structural.py     ← AST → DocumentModel (panflute)
│   │   ├── enrichment.py     ← rule-based semantic enrichment
│   │   ├── chunking.py       ← DocumentModel → SemanticChunk[]
│   │   ├── embeddings.py     ← sentence-transformers wrapper
│   │   ├── vector_store.py   ← vector-store backends (memory | chroma)
│   │   ├── vocabulary.py     ← cross-corpus entity vocabulary I/O
│   │   ├── convert/          ← HTML → GitLab Markdown converter (flow B)
│   │   ├── pipeline.py       ← stage orchestrator
│   │   └── cli.py            ← typer CLI (index | search | convert | export | scan | scan-taxonomy | lint | check)
│   └── tools/                ← dev tooling — NOT shipped (excluded from packaging + ruff/mypy gates)
│       ├── scripts/          ← eval_retrieval.py, fetch_e2e_corpus.py, dump helpers, convert-docs.ps1
│       └── eval/             ← retrieval-eval harness: corpus/ + frozen golden queries + RETRIEVAL_LOG
├── tests/                    ← pytest suite (unit · slow · integration · e2e; convert/ subdir for flow B)
├── inbox/                    ← pipeline INPUT zone (workspace contract); skeleton tracked, contents gitignored
│   └── sample/               ← drop a sample corpus here (HTML for convert, .md for index)
├── outbox/                   ← pipeline OUTPUT zone (index/ md/ chunks/ reports/ vocab/ taxonomy/ dump/); gitignored
├── config/                   ← committed configuration: field_directions.yaml, taxonomy.json, entity-vocab.json (seeds)
├── docs/
│   ├── guides/               ← how-to / navigation pages (formerly wiki/)
│   ├── learn/                ← C#→Python learning curriculum (bridge, tours, walkthroughs, exercises)
│   ├── adr/ · notes/ · inbox/ · template/ · archive/
│   └── confluence-conversion-rules.md  ← the converter spec
├── build/                    ← setuptools build output, gitignored (build/lib, build/bdist)
├── .vscode/ · .github/ · .devcontainer/   ← IDE / Copilot / dev-container config (tracked)
├── devfile.yaml              ← OpenShift Dev Spaces / Eclipse Che
├── environment.yml           ← conda / micromamba environment
├── pyproject.toml            ← project metadata, pytest, ruff, mypy
└── .env.example              ← environment variable template
```

---

## GitHub Copilot integration

The `.github/copilot-instructions.md` file configures **Copilot Chat** to understand
this project's architecture.

Use `@workspace` in the chat panel for cross-file questions:

```
@workspace how does the breadcrumb get from the Section to the SemanticChunk?
@workspace write a test for the case where a CodeBlock has no language specified
@workspace what section types does the enrichment module recognise?
```

The `.vscode/settings.json` sets `github.copilot.advanced.workspaceContext` to index
`src/**` and `tests/**` for inline suggestions.

---

## Requirements

- Python ≥ 3.11
- pandoc ≥ 3.0 (installed via conda-forge or apt)
- Docker (for Dev Container option only)
