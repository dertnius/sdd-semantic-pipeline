# CLI command reference

The single source of truth for the `sdd-pipeline` command surface. Every command
below maps 1:1 to a Typer command in
[`src/sdd_pipeline/cli.py`](../../src/sdd_pipeline/cli.py); the CI doc-health check
([`check_docs.py`](../../src/tools/scripts/check_docs.py)) asserts that this page
documents exactly the commands and flags the code exposes, so a drifted flag fails
the build.

Run `sdd-pipeline help` for the grouped overview, or `sdd-pipeline help <command>`
(equivalently `sdd-pipeline <command> --help`) for a command's full options.

## Workspace zones

Every command honours the **inbox / outbox** workspace contract (see
[Configuration](configuration.md#workspace-contract)). Inputs default to `inbox/`
and outputs to `outbox/<sub>/`, so the bare command needs no path flags. Out-of-zone
paths are rejected with **exit 2** unless `PIPELINE_ENFORCE_WORKSPACE=false`. The
standard outbox sub-layout: `index/`, `md/`, `chunks/`, `reports/`, `vocab/`,
`taxonomy/`, `media/`, `drawio/`, `dump/`.

**Model-free commands** (pandoc-only, no embedding model downloaded): `convert`,
`convert-docx`, `resolve-gliffy`, `convert-drawio`, `export`, `lint`, `scan`,
`scan-taxonomy`, `report`, `download`, `check`, `pwsh-path`, `help`. The `--lexical`
flag makes `index`/`search`/`tui`/`mcp` model-free too.

---

## index

Embed and index `.md` files into the vector store (the full 7-stage flow A:
pandoc → structural → enrich → chunk → embed → store). **Needs an embedding model**
unless `--lexical`. Input: inbox. Output: `outbox/index/`.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory of `.md` files. |
| `--output`, `-o` | `outbox/index` | Vector index persistence path. |
| `--model`, `-m` | `BAAI/bge-large-en-v1.5` | Local embedding model (ignored when `--provider azure`). |
| `--provider` | `local` | Embedding backend: `local` \| `azure`. |
| `--lang` | `en` | Enrichment language: `en\|de\|fr\|it`, or `auto` (needs `[lang]`). |
| `--lexical`, `-L` | off | Build a model-free BM25 index (no embeddings stored). |
| `--backend` | env / `memory` | Vector store backend: `memory` \| `chroma`. |
| `--glob`, `-g` | `**/*.md` | File glob pattern. |
| `--merge-prose` | off | Pack each section's prose into one chunk (code/tables stay separate). |
| `--merge-definitions` | off | Pack prose **and** code into one chunk (overrides `--merge-prose`). |
| `--chunk-gate` / `--no-chunk-gate` | env / on | Block a file whose chunks are poisoned. |
| `--dry-run` | off | Parse without indexing. |
| `--verbose`, `-v` | off | Per-file progress. |

```powershell
sdd-pipeline index --model all-MiniLM-L6-v2 --merge-prose -v
```

## reindex

Re-index a **single** `.md` file in place: drop its existing chunks, then index it.
The incremental refresh the SAD-sync flow uses after a human applies a SAD patch, so the
next coverage check sees the change without a full corpus rebuild. The
`--provider`/`--model`/`--backend` **must match** the existing index's provenance. Input:
a file under the inbox. Output: `outbox/index/`.

| Flag | Default | Description |
|---|---|---|
| `file` (arg) | — | Path to the single `.md` file to re-index. |
| `--output`, `-o` | `outbox/index` | Vector index persistence path. |
| `--model`, `-m` | `BAAI/bge-large-en-v1.5` | Local embedding model (ignored when `--provider azure`). |
| `--provider` | `local` | Embedding backend: `local` \| `azure`. |
| `--lang` | `en` | Enrichment language: `en\|de\|fr\|it`, or `auto` (needs `[lang]`). |
| `--lexical`, `-L` | off | Model-free BM25 index (no embeddings stored). |
| `--backend` | env / `memory` | Vector store backend: `memory` \| `chroma`. |

```powershell
sdd-pipeline reindex inbox/sad-retailnexus-oms.md --provider azure
```

## download

Download manifest-listed files (Confluence HTML / SharePoint docx) into the inbox.
Optional ingestion behind SiteMinder SSO; **credentials are secrets set via env only**
(`PIPELINE_DOWNLOAD_COOKIE` / `_BEARER` / `_USERNAME` / `_PASSWORD` / `_LOGIN_URL`),
never flags. Needs the `[download]` extra. Exits non-zero if any file fails.
Input: a manifest. Output: files into inbox; report to `outbox/reports/`.

| Flag | Default | Description |
|---|---|---|
| `manifest` (arg) | — | YAML/JSON manifest of `{url, dest}` entries. |
| `--auth` | env / `cookie` | SiteMinder auth: `cookie` \| `form` \| `bearer` \| `none`. |
| `--insecure` | off | Skip TLS verification (corporate interception). |
| `--timeout` | env / `60` | Per-request timeout (seconds). |
| `--report`, `-r` | `outbox/reports/download-report.json` | JSON report path. |

```powershell
$env:PIPELINE_DOWNLOAD_COOKIE = "<SMSESSION value>"
sdd-pipeline download inbox/manifest.yaml --auth cookie
```

## convert

Convert Confluence-**rendered** HTML to GitLab Markdown + a JSON report (flow B,
independent of flow A). Storage-format HTML is refused. Low-confidence pages are
quarantined (Arm 2). Input: inbox `*.html`. Output: `outbox/md/`; report to
`outbox/reports/`.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory scanned recursively for HTML. |
| `--output`, `-o` | `outbox/md` | Where to write `.md` (mirrors input tree). |
| `--glob`, `-g` | `**/*.html` | HTML glob pattern. |
| `--report`, `-r` | `outbox/reports/conversion-report.json` | JSON report path. |
| `--selector` | none | CSS selector for main content. |
| `--space` | "" | Confluence space key → frontmatter provenance. |
| `--source-url` | "" | Canonical source URL → frontmatter provenance. |
| `--labels` | "" | Comma-separated labels → frontmatter provenance. |
| `--no-frontmatter` | off | Skip YAML frontmatter. |
| `--toc` | off | Inject `[[_TOC_]]` (human-docs profile). |
| `--keep-diagrams` | off | Keep SVG diagram HTML as-is. |
| `--quarantine` / `--no-quarantine` | env / on | Route low-confidence conversions to `_quarantine/` and exit non-zero. |
| `--max-unrecognized` | env / `8` | Quarantine when dropped-construct count exceeds this. |
| `--pandoc-path` | discovered | Path to pandoc binary. |
| `--verbose`, `-v` | off | Per-file metrics. |

```powershell
sdd-pipeline convert --space PLAT --source-url https://wiki/... -v
```

## convert-docx

Convert Word `.docx` files to Markdown + a JSON report (pandoc-native, with media
extraction and frontmatter harvested from docx core properties). Driven by the
`docToMd` skill. Input: inbox `*.docx`. Output: `outbox/md/`; report to
`outbox/reports/`.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory scanned recursively for `.docx`. |
| `--output`, `-o` | `outbox/md` | Where to write `.md` (mirrors input tree). |
| `--glob`, `-g` | `**/*.docx` | docx glob pattern. |
| `--report`, `-r` | `outbox/reports/docx-conversion-report.json` | JSON report path. |
| `--space` | "" | Space/project key → frontmatter provenance. |
| `--source-url` | "" | Canonical source URL → frontmatter provenance. |
| `--labels` | "" | Comma-separated labels → frontmatter provenance. |
| `--no-frontmatter` | off | Skip YAML frontmatter. |
| `--toc` | off | Inject `[[_TOC_]]` (human-docs profile). |
| `--no-media` | off | Drop embedded images (keep alt text) instead of extracting to `media/`. |
| `--pandoc-path` | discovered | Path to pandoc binary. |
| `--verbose`, `-v` | off | Per-file metrics. |

```powershell
sdd-pipeline convert-docx inbox/specs --no-media -v
```

## resolve-gliffy

Resolve Confluence-embedded Gliffy diagrams to editable SVG + a manifest (prefers a
sibling `<name>.svg` export, else renders the JSON; best-effort basic shapes).
Input: inbox `*.gliffy`. Output: `outbox/media/`; report to `outbox/reports/`.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory scanned recursively for `.gliffy`. |
| `--output`, `-o` | `outbox/media` | Where to write `.svg` (mirrors input tree). |
| `--glob`, `-g` | `**/*.gliffy` | Gliffy glob pattern. |
| `--report`, `-r` | `outbox/reports/gliffy-report.json` | JSON manifest/report path. |
| `--prefer-existing-svg` / `--always-render` | prefer-existing | Copy a sibling `.svg` when present vs. force the built-in renderer. |
| `--verbose`, `-v` | off | Per-file detail. |

## convert-drawio

Convert Gliffy diagrams to draw.io (`.drawio` mxGraph XML) via the shared semantic
model. `--check` runs the round-trip fidelity oracle. Input: inbox `*.gliffy`.
Output: `outbox/drawio/`; report to `outbox/reports/`.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory scanned recursively for `.gliffy`. |
| `--output`, `-o` | `outbox/drawio` | Where to write `.drawio` (mirrors input tree). |
| `--glob`, `-g` | `**/*.gliffy` | Gliffy glob pattern. |
| `--report`, `-r` | `outbox/reports/drawio-report.json` | JSON report path. |
| `--check` / `--no-check` | off | Round-trip fidelity oracle (emit → re-parse → compare); exits non-zero on any mismatch. |
| `--verbose`, `-v` | off | Per-file detail. |

```powershell
sdd-pipeline convert-drawio --check
```

## export

Write each markdown file's `SemanticChunk`s to `.chunks.json`/`.jsonl` for other
pipelines. Deterministic stages only (pandoc → structural → enrich → chunk); **no
embedding model**. Input: inbox `*.md`. Output: `outbox/chunks/`; report co-located.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory of `.md` files. |
| `--output`, `-o` | `outbox/chunks` | Directory for chunk artifacts (mirrors input tree). |
| `--format`, `-f` | `json` | Output format: `json` \| `jsonl`. |
| `--glob`, `-g` | `**/*.md` | Markdown glob pattern. |
| `--lang` | `en` | Enrichment language: `en\|de\|fr\|it`, or `auto` (needs `[lang]`). |
| `--jobs`, `-j` | `1` | Parallel worker threads (0 = all CPUs); output is byte-identical to `-j1`. |
| `--merge-prose` | off | Pack each section's prose into one chunk. |
| `--merge-definitions` | off | Pack prose **and** code into one chunk (overrides `--merge-prose`). |
| `--report`, `-r` | `<output>/export-report.json` | JSON report path. |
| `--verbose`, `-v` | off | Per-file progress. |

```powershell
sdd-pipeline export --merge-prose --format jsonl
```

## lint

Lint raw source `.md` for embedding-harmful syntax/structure — **report only**, runs
before pandoc, never rewrites. Flags leaked HTML, untranslated Confluence macros,
whole-doc code dumps, TOC/nav link-dumps, near-empty stubs, empty headings. Input:
inbox `*.md`. Output: report to `outbox/reports/`.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory of `.md` (your embedding corpus). |
| `--glob`, `-g` | `**/*.md` | Markdown glob pattern. |
| `--report`, `-r` | `outbox/reports/quality-report.json` | JSON report path. |
| `--strict` | off | Exit non-zero if any file has a block-severity issue. |
| `--verbose`, `-v` | off | Per-file results. |

## scan

Discover and persist the cross-corpus **entity** vocabulary (no embedding model).
Parses every file, scans for entity candidates across the whole set, merges the
persisted vocabulary + `PIPELINE_ENTITY_TERMS`, writes sorted JSON for review.
Input: inbox `*.md`. Output: `outbox/vocab/`.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory of `.md` files. |
| `--vocab` | `outbox/vocab/entity-vocab.json` | Output JSON vocabulary (overrides `PIPELINE_ENTITY_VOCAB_PATH`). |
| `--glob`, `-g` | `**/*.md` | Markdown glob pattern. |
| `--verbose`, `-v` | off | Print the discovered terms. |

## scan-taxonomy

Derive a data-aligned **section → field** taxonomy by scanning the corpus's tables
by document-frequency (no embedding model). Writes a canonical `taxonomy.json` plus
a frequency-ranked field vocabulary for review. Input: inbox `*.md`. Output:
`outbox/taxonomy/`.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | inbox | Directory of `.md` files. |
| `--out`, `-o` | `outbox/taxonomy/taxonomy.json` | Output taxonomy JSON. |
| `--vocab-out` | `outbox/taxonomy/field_vocabulary.json` | Output field-frequency vocabulary JSON. |
| `--min-docs`, `-n` | `2` | Keep a field only if seen in ≥ this many documents. |
| `--glob`, `-g` | `**/*.md` | Markdown glob pattern. |

## search

Query the indexed corpus. **Needs the matching embedding model** unless `--lexical`.
Provider/backend must match the index that was built. Reads `outbox/index/`.

| Flag | Default | Description |
|---|---|---|
| `query` (arg) | — | Natural-language search query. |
| `--index`, `-i` | `outbox/index` | Vector index path. |
| `--model`, `-m` | `BAAI/bge-large-en-v1.5` | Embedding model (must match the index). |
| `--provider` | `local` | Embedding backend: `local` \| `azure` (must match the index). |
| `--backend` | env / `memory` | Vector store backend: `memory` \| `chroma` (must match the index). |
| `--top-k`, `-k` | `5` | Number of results. |
| `--section-type`, `-s` | none | Filter: `overview\|architecture\|api\|decision\|alternative\|tradeoff\|consequence\|done_criteria\|deployment\|data_model\|security`. |
| `--space` | none | Confluence space key filter. |
| `--genre`, `-g` | none | Prose-genre filter: `glossary\|faq\|howto\|policy\|narrative`. |
| `--hybrid`, `-H` | off | Fuse dense + lexical (BM25) rankings via RRF. |
| `--lexical`, `-L` | off | Model-free BM25-only ranking (overrides `--hybrid`). |
| `--lang` | `en` | Language for lexical tokenization/stemming: `en\|de\|fr\|it`. |

```powershell
sdd-pipeline search "how does token refresh work" -k 8 --hybrid -s decision
```

## tui

Launch an interactive search browser (TUI). Needs the `[tui]` extra and a real
terminal. Keeps the model + index warm across queries. Reads `outbox/index/`.

| Flag | Default | Description |
|---|---|---|
| `--index`, `-i` | `outbox/index` | Vector index path. |
| `--model`, `-m` | `BAAI/bge-large-en-v1.5` | Embedding model (must match the index). |
| `--provider` | `local` | Embedding backend: `local` \| `azure`. |
| `--backend` | env / `memory` | Vector store backend: `memory` \| `chroma`. |
| `--hybrid`, `-H` | off | Start with hybrid (dense + BM25) retrieval enabled. |
| `--lexical`, `-L` | off | Model-free BM25-only mode (auto-enabled for a lexical index). |
| `--lang` | `en` | Language for lexical tokenization/stemming: `en\|de\|fr\|it`. |

## mcp

Run a local MCP server (stdio) exposing semantic search over the index — designed
for GitHub Copilot (register in `.vscode/mcp.json`). Needs the `[mcp]` extra. Speaks
JSON-RPC on stdout. Reads `outbox/index/`.

| Flag | Default | Description |
|---|---|---|
| `--index`, `-i` | `outbox/index` | Vector index path. |
| `--model`, `-m` | `BAAI/bge-large-en-v1.5` | Embedding model (must match the index). |
| `--provider` | `local` | Embedding backend: `local` \| `azure`. |
| `--backend` | env / `memory` | Vector store backend: `memory` \| `chroma`. |
| `--hybrid`, `-H` | off | Default tools to hybrid (dense + BM25) retrieval. |
| `--lexical`, `-L` | off | Model-free BM25-only mode (auto-enabled for a lexical index). |
| `--lang` | `en` | Language for lexical tokenization/stemming: `en\|de\|fr\|it`. |

## report

Run the full pipeline per HTML file and emit a self-contained HTML report (every
stage's artifact, chunk quality, information loss vs. the original HTML, an SVG
relationship graph, the adapted taxonomy/vocabulary). Model-free. Defaults to the
converter regression fixtures.

| Flag | Default | Description |
|---|---|---|
| `input_dir` (arg) | `tests/convert/examples` | Directory of HTML files to run the pipeline over. |
| `--output`, `-o` | `outbox/reports` | Where to write the per-file reports + `index.html`. |
| `--glob`, `-g` | `*.html` | HTML glob (non-recursive). |
| `--pandoc-path` | discovered | Path to pandoc binary. |
| `--verbose`, `-v` | off | Per-file status line. |

## check

Verify all runtime dependencies are installed (Python, pandoc, core packages, plus
informational rows for the optional extras, Azure env vars, and PowerShell 7).
Exits non-zero only if a **required** dependency is missing. No flags.

## pwsh-path

Print the absolute resolved PowerShell 7 path for scripts to capture
(`$env:PWSH = (sdd-pipeline pwsh-path)`). Honors `PIPELINE_PWSH_PATH`; non-intrusive
(never edits PATH). On failure: diagnostic on stderr, empty stdout, exit 1.

| Flag | Default | Description |
|---|---|---|
| `--allow-any` | off | Print any usable PowerShell (e.g. 5.1), not just v7+. |

## help

List the available commands and what each is for. With no argument, prints a grouped
overview; pass a command name for that command's full options.

| Flag | Default | Description |
|---|---|---|
| `command` (arg) | none | Show full options for one command, e.g. `help search`. |
