# Configuration reference

All settings load from environment variables (prefix `PIPELINE_`) or a `.env` file
via `PipelineConfig` (pydantic-settings), defined in
[`src/sdd_pipeline/config.py`](../../src/sdd_pipeline/config.py). The CI doc-health
check ([`check_docs.py`](../../src/tools/scripts/check_docs.py)) asserts this page
documents exactly the fields `PipelineConfig` defines, so an added/renamed setting
fails the build until it is documented here.

> **Dual-branch note.** `config.py` defines `PipelineConfig` twice: a
> pydantic-settings v2 class and a pydantic-v1 fallback (chosen at import by a
> `try/except ImportError`). **Every new field must be added to both branches** or
> the fallback path silently drops it.

The env var name is `PIPELINE_` + the upper-cased field name (e.g. the field
`embedding_model` ← `PIPELINE_EMBEDDING_MODEL`). Secrets (`PIPELINE_AZURE_OPENAI_API_KEY`,
the `PIPELINE_DOWNLOAD_*` credentials) must come from the environment, never CLI flags.

## Install extras

Optional dependency groups in [`pyproject.toml`](../../pyproject.toml). Install with
`pip install -e ".[<extra>]"` (combine: `".[dev,docs]"`).

| Extra | Pulls in | Enables |
|---|---|---|
| `dev` | pytest, pytest-cov, pytest-mock, ruff, mypy, chromadb, textual, mcp, langdetect, snowballstemmer, cairosvg, pillow | Full test + lint + type-check toolchain. |
| `docs` | mkdocs-material, mkdocs-include-markdown-plugin | The local MkDocs documentation site (`mkdocs serve`, or `mkdocs build` → offline-searchable `./site`). |
| `azure` | openai | Azure OpenAI embedding provider (`--provider azure`). |
| `chroma` | chromadb | Chroma vector-store backend (`--backend chroma`). |
| `tui` | textual | Interactive search TUI (`sdd-pipeline tui`). |
| `mcp` | mcp | MCP stdio server (`sdd-pipeline mcp`). |
| `lang` | langdetect | Per-document language auto-detection (`--lang auto`). |
| `stem` | snowballstemmer | Snowball stemming for BM25 lexical recall. |
| `download` | requests | SiteMinder-aware ingestion (`sdd-pipeline download`). |
| `raster` | cairosvg, pillow | SVG→PNG pixel-diff regression (Gliffy fidelity). |

## Settings

### Pandoc

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_PANDOC_FROM_FORMAT` | `gfm` | Input format passed to `pandoc --from` (gfm, markdown, commonmark). |

### Embedding

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_EMBEDDING_MODEL` | `BAAI/bge-large-en-v1.5` | sentence-transformers model name or HuggingFace ID. |
| `PIPELINE_EMBEDDING_BATCH_SIZE` | `32` | Encoding batch size. |
| `PIPELINE_EMBEDDING_PROVIDER` | `local` | Embedding backend: `local` (sentence-transformers) \| `azure`. |
| `PIPELINE_AZURE_OPENAI_ENDPOINT` | "" | Azure OpenAI endpoint. |
| `PIPELINE_AZURE_OPENAI_API_KEY` | "" | **Secret** — Azure OpenAI API key. |
| `PIPELINE_AZURE_OPENAI_DEPLOYMENT` | "" | Azure embeddings deployment name (used as the model arg). |
| `PIPELINE_AZURE_OPENAI_API_VERSION` | `2024-10-21` | Azure OpenAI API version. |

### Language & lexical

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_LANGUAGE` | `en` | Enrichment language: `en\|de\|fr\|it`, or `auto` (needs `[lang]`). Unsupported codes fall back to English. |
| `PIPELINE_LEXICAL_ONLY` | `false` | Model-free search: skip dense embedding, rank by BM25 only. |
| `PIPELINE_LEXICAL_STEMMING` | `false` | Snowball stemming (en/de/fr/it) during BM25 tokenization (needs `[stem]`; single-language index only). |

### Downloader (optional SiteMinder ingestion)

Used only by `download`. Credentials are **secrets** — env only; the deterministic
core never reads these.

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_DOWNLOAD_AUTH` | `cookie` | Auth strategy: `cookie` \| `form` \| `bearer` \| `none`. |
| `PIPELINE_DOWNLOAD_COOKIE` | "" | **Secret** — pre-issued SMSESSION cookie value. |
| `PIPELINE_DOWNLOAD_COOKIE_NAME` | `SMSESSION` | Session cookie name. |
| `PIPELINE_DOWNLOAD_BEARER` | "" | **Secret** — bearer token (`auth=bearer`). |
| `PIPELINE_DOWNLOAD_LOGIN_URL` | "" | Form-login POST URL (`auth=form`). |
| `PIPELINE_DOWNLOAD_USERNAME` | "" | Service-account username (`auth=form`). |
| `PIPELINE_DOWNLOAD_PASSWORD` | "" | **Secret** — service-account password. |
| `PIPELINE_DOWNLOAD_USER_FIELD` | `USER` | Login-form field carrying the username. |
| `PIPELINE_DOWNLOAD_PASS_FIELD` | `PASSWORD` | Login-form field carrying the password. |
| `PIPELINE_DOWNLOAD_TIMEOUT` | `60` | Per-request timeout (seconds). |
| `PIPELINE_DOWNLOAD_VERIFY_TLS` | `true` | Verify TLS certs (`--insecure` sets false). |

### Chunking

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_MAX_CHUNK_CHARS` | `2000` | Max characters per semantic chunk before splitting. |
| `PIPELINE_CHUNK_MERGE_PROSE` | `false` | Pack a section's prose blocks into one chunk. |
| `PIPELINE_CHUNK_MERGE_DEFINITIONS` | `false` | Pack a section's prose **and** code into one chunk (overrides merge_prose). |
| `PIPELINE_EMBED_CHAR_BUDGET` | `1800` | Soft target chars for the rendered embed_text (header + content). |
| `PIPELINE_CHUNK_OVERLAP_SENTENCES` | `0` | When > 0, a split prose block carries its trailing N sentences into the next chunk. |

### Document profile routing (advisory)

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_DOC_PROFILE_ENABLED` | `false` | Auto-detect a coarse profile (technical/prose/mixed) to pick a default merge strategy. |
| `PIPELINE_DOC_PROFILE_CODE_RATIO` | `0.5` | Code-char fraction at/above which a doc is profiled technical. |
| `PIPELINE_DOC_PROFILE_TABLE_RATIO` | `0.4` | Table-char fraction at/above which a doc is profiled technical. |
| `PIPELINE_PROSE_KEYPHRASES` | `true` | Merge deterministic RAKE keyphrases into prose-genre embed keywords. |
| `PIPELINE_PROSE_NER` | `true` | Extract named entities from prose via the optional spaCy layer into `ner:*` metadata facets (display/filter only). |

### Chunk hygiene gate (Arm 1)

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_CHUNK_GATE` | `true` | Run the chunk-level hygiene invariant during indexing; a poisoned chunk blocks the whole file. |
| `PIPELINE_EMBED_CHAR_HARD_CAP` | `2048` | Hard ceiling (chars) for embed_text; above it the gate warns of likely truncation. |

### Converter confidence gate (Arm 2)

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_CONVERT_QUARANTINE` | `true` | Quarantine low-confidence conversions and exit non-zero. |
| `PIPELINE_CONVERT_MAX_UNRECOGNIZED` | `8` | Quarantine when the dropped/unrecognised-construct count exceeds this. |

### Enrichment

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_ENTITY_TERMS` | `[]` | JSON array of project domain vocabulary folded into entity extraction. |
| `PIPELINE_ENTITY_VOCAB_PATH` | "" | JSON vocabulary file; when set, `index`/`export` run a two-pass cross-corpus scan. |
| `PIPELINE_INVENTORY_ENRICHMENT` | `true` | Route structural (table) + prose entity records into depends_on/exposes/metadata. |

### Vector store

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_VECTOR_STORE_BACKEND` | `memory` | Backend: `memory` (langchain-core, JSON-persisted) \| `chroma` (needs `[chroma]`). |
| `PIPELINE_CHROMA_PERSIST_DIR` | `./outbox/index` | Index persist dir (Chroma files, or `<collection>.json` for memory). Must stay under the outbox. |
| `PIPELINE_COLLECTION_NAME` | `sdd_docs` | Vector store collection name. |

### Workspace contract

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_INBOX_DIR` | `./inbox` | Root for all pipeline INPUT files. |
| `PIPELINE_OUTBOX_DIR` | `./outbox` | Root for all pipeline OUTPUTS (index, md, chunks, reports, vocab, taxonomy, dump). |
| `PIPELINE_ENFORCE_WORKSPACE` | `true` | Enforce the inbox/outbox containment contract (set false in tests/ad-hoc runs). |

### Hybrid retrieval

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_HYBRID_SEARCH` | `false` | Fuse dense (vector) and lexical (BM25) rankings via RRF. |
| `PIPELINE_HYBRID_CANDIDATE_POOL` | `50` | Per-scorer candidate depth fused before taking top-k. |
| `PIPELINE_RRF_K` | `60` | Reciprocal Rank Fusion constant (higher = flatter weighting). |

### Shell tooling

| Env var | Default | Description |
|---|---|---|
| `PIPELINE_PWSH_PATH` | "" | Explicit PowerShell 7 path; sticky when set, never edits PATH. Empty = auto-discover. |

## Index provenance

`index_file` records `(provider, model, dimension)` and the `EMBED_FORMAT_VERSION`
with the index (Chroma collection metadata, or a `<collection>.provenance.json`
sidecar for the memory backend). `search` verifies it and raises a clear error if the
configured embedder differs from the one that built the index. Re-index or align
`--provider`/`--model` to fix.
