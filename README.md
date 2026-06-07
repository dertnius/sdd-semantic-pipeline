# SDD Semantic Pipeline

A 7-stage pipeline that turns **Confluence-exported markdown files** into a
**semantic vector search index** optimised for Software Design Documents.

```
Confluence MD → pandoc AST → Structural model → Semantic enrichment
             → Chunking → Embeddings → ChromaDB vector search
```

---

## Quick start

```bash
# 0 – Convert Confluence HTML exports → GitLab Markdown + a JSON report
#     (per-file section/picture/code/list/table/URL counts)
sdd-pipeline convert docs/ --output build/md --report build/conversion-report.json

# 1 – Install and index sample docs
sdd-pipeline index docs/sample/ --model all-MiniLM-L6-v2

# 2 – Search
sdd-pipeline search "how does token refresh work?"
sdd-pipeline search "rate limiting algorithm" --section-type architecture

# 3 – Verify environment
sdd-pipeline check

# Model-free extras (pandoc only, no embedding model loaded):
# export chunks for reuse by another pipeline …
sdd-pipeline export docs/sample/ --output build/chunks --merge-prose
# … or discover the cross-corpus entity vocabulary for review before indexing
sdd-pipeline scan docs/sample/ --vocab docs/entity-vocab.json
```

> `convert` scans the input directory recursively for `*.html`, writes a `.md`
> per file, and emits a JSON report with per-file and aggregate metrics. See
> [docs/Convert.Linux.Readme.md](docs/Convert.Linux.Readme.md) /
> [docs/Convert.Windows.Readme.md](docs/Convert.Windows.Readme.md) for details.

See **[CLI reference](#cli-reference)** below for every command and flag. The
full, always-current option list is `sdd-pipeline <command> --help`.

---

## CLI reference

Six commands: `index`, `search`, `convert`, `export`, `scan`, `check`. Only
`index` and `search` load an embedding model; `convert`, `export`, and `scan`
are **pandoc-only** (no model download).

### `index` — build the vector index

```bash
sdd-pipeline index <input_dir> [options]
```

| Option | Default | Description |
|---|---|---|
| `--output` / `-o` | `./data/chroma` | ChromaDB persistence path |
| `--model` / `-m` | `BAAI/bge-large-en-v1.5` | Local embedding model (ignored when `--provider azure`) |
| `--provider` | `local` | Embedding backend: `local` \| `azure` |
| `--glob` / `-g` | `**/*.md` | File glob pattern |
| `--merge-prose` | off | Pack each section's prose into one chunk (code/tables stay separate) |
| `--merge-definitions` | off | Pack prose **and** code into one chunk (tables separate); overrides `--merge-prose` |
| `--dry-run` | off | Parse + chunk without indexing (no model loaded) |
| `--verbose` / `-v` | off | Per-file chunk counts |

> When `PIPELINE_ENTITY_VOCAB_PATH` is set, `index` runs a two-pass cross-corpus
> scan first (discover + persist the entity vocabulary, then enrich every doc
> with it). See [Configuration](#configuration).

### `search` — query the index

```bash
sdd-pipeline search "<query>" [options]
```

| Option | Default | Description |
|---|---|---|
| `--index` / `-i` | `./data/chroma` | ChromaDB persistence path to query |
| `--model` / `-m` | `BAAI/bge-large-en-v1.5` | Embedding model (**must match the index**) |
| `--provider` | `local` | Embedding backend: `local` \| `azure` (must match the index) |
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
sdd-pipeline convert <input_dir> [options]
```

| Option | Default | Description |
|---|---|---|
| `--output` / `-o` | next to each HTML | Output directory for `.md` (mirrors input tree) |
| `--glob` / `-g` | `**/*.html` | HTML glob pattern |
| `--report` / `-r` | `conversion-report.json` | JSON report path |
| `--selector` | auto-detect | CSS selector for the main content region |
| `--space` | — | Confluence space key → frontmatter (provenance) |
| `--source-url` | — | Canonical source URL → frontmatter (provenance) |
| `--labels` | — | Comma-separated labels → frontmatter (provenance) |
| `--no-frontmatter` | off | Skip the YAML frontmatter block |
| `--no-toc` | off | Skip the `[[_TOC_]]` directive |
| `--keep-diagrams` | off | Keep SVG diagram HTML instead of a placeholder |
| `--pandoc-path` | auto (`PATH`) | Path to a specific pandoc binary |
| `--verbose` / `-v` | off | Per-file metric summary line |

### `export` — chunks to JSON/JSONL (model-free)

Runs the deterministic stages only (pandoc → structural → enrich → chunk); **no
embedding model is loaded**. Writes a `.chunks.json`/`.jsonl` per file plus an
`export-report.json`, for reuse by another pipeline.

```bash
sdd-pipeline export <input_dir> --output <dir> [options]
```

| Option | Default | Description |
|---|---|---|
| `--output` / `-o` | *(required)* | Directory for `.chunks.json`/`.jsonl` (mirrors input tree) |
| `--format` / `-f` | `json` | Output format: `json` \| `jsonl` |
| `--glob` / `-g` | `**/*.md` | Markdown glob pattern |
| `--merge-prose` | off | Pack each section's prose into one chunk (code/tables separate) |
| `--merge-definitions` | off | Pack prose **and** code into one chunk; overrides `--merge-prose` |
| `--report` / `-r` | `<output>/export-report.json` | JSON report path |
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
sdd-pipeline scan <input_dir> [options]
```

| Option | Default | Description |
|---|---|---|
| `--vocab` | `PIPELINE_ENTITY_VOCAB_PATH` | Output JSON vocabulary file (overrides the env var) |
| `--glob` / `-g` | `**/*.md` | Markdown glob pattern |
| `--verbose` / `-v` | off | Print the discovered term list |

### `check` — verify the environment

```bash
sdd-pipeline check
```

Reports Python, pandoc, and each Python dependency, plus optional `openai`
availability and whether the Azure env vars are set (the API key value is never
printed). Exits non-zero if a required dependency is missing.

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
sdd-pipeline index docs/sample/ --provider azure
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
   sdd-pipeline index docs/sample/ --model all-MiniLM-L6-v2
   ```

#### Available devfile commands (Command Palette → *Run Task*)

| Command | What it does |
|---|---|
| `bootstrap` | Install pandoc + pip deps (runs on postStart) |
| `check` | Verify all dependencies |
| `test` | Unit tests (no pandoc / ML required) |
| `test-all` | All tests including slow integration |
| `index-samples` | Index `docs/sample/` |
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
| 7b | `vector_store` | chunks + embeddings → ChromaDB index |

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
    chroma_persist_dir="./data/chroma",
)
pipeline = SemanticPipeline(config=config)

# Index a directory
counts = pipeline.index_directory(Path("docs/"))
print(counts)   # {'docs/auth-service.md': 34, 'docs/api-gateway.md': 28}

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
| `PIPELINE_EMBED_CHAR_BUDGET` | `1800` | Target max chars for rendered `embed_text` (avoids silent truncation) |
| `PIPELINE_CHUNK_MERGE_PROSE` | `false` | Pack a section's prose into one chunk |
| `PIPELINE_CHUNK_MERGE_DEFINITIONS` | `false` | Pack prose + code into one chunk (overrides merge-prose) |
| `PIPELINE_ENTITY_TERMS` | `[]` | JSON array of domain vocabulary folded into entity extraction |
| `PIPELINE_ENTITY_VOCAB_PATH` | `""` | JSON vocab file; when set, enables the two-pass cross-corpus scan in `index`/`export` |
| `PIPELINE_CHROMA_PERSIST_DIR` | `./data/chroma` | ChromaDB persistence path |
| `PIPELINE_COLLECTION_NAME` | `sdd_docs` | ChromaDB collection |
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
│   └── sdd_pipeline/
│       ├── __init__.py       ← public API exports
│       ├── config.py         ← PipelineConfig (pydantic-settings)
│       ├── models.py         ← data types only (no external deps)
│       ├── ast_parser.py     ← pandoc subprocess wrapper
│       ├── structural.py     ← AST → DocumentModel (panflute)
│       ├── enrichment.py     ← rule-based semantic enrichment
│       ├── chunking.py       ← DocumentModel → SemanticChunk[]
│       ├── embeddings.py     ← sentence-transformers wrapper
│       ├── vector_store.py   ← ChromaDB operations
│       ├── vocabulary.py     ← cross-corpus entity vocabulary I/O
│       ├── html_to_gitlab_md.py ← HTML → GitLab Markdown converter
│       ├── pipeline.py       ← stage orchestrator
│       └── cli.py            ← typer CLI (index | search | convert | export | scan | check)
├── tests/
│   ├── conftest.py           ← shared fixtures + sample data
│   ├── test_models.py
│   ├── test_structural.py
│   ├── test_enrichment.py
│   ├── test_chunking.py
│   ├── test_ast_parser.py    ← pandoc tests (skipped without pandoc)
│   ├── test_vector_store.py  ← mocked ChromaDB
│   └── test_pipeline.py      ← mocked orchestration + slow integration
├── docs/
│   └── sample/
│       ├── auth-service.md   ← sample SDD (Auth Service)
│       └── api-gateway.md    ← sample SDD (API Gateway)
├── .vscode/                  ← settings, extensions, launch, tasks
├── .github/
│   └── copilot-instructions.md   ← Copilot custom instructions
├── .devcontainer/
│   └── devcontainer.json     ← VS Code Dev Containers
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
