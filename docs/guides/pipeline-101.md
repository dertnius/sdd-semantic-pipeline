# Pipeline 101 — an operator's step-by-step guide

_Last updated: 2026-06-15_

A task-oriented runbook for the six things you actually do with this pipeline:
onboard a document, update one without rebuilding everything, give a document (or a
connected set) the right vocabulary and taxonomy, measure the quality of what comes
out, and work the loop when something looks wrong.

This guide explains the **mechanism** behind each task before the commands, so you
know *why* a step is needed — not just what to type. For deeper code-level reading,
follow the links into [`docs/learn/`](../learn/README.md).

> **Conventions.** Examples use **dev defaults** — the small `all-MiniLM-L6-v2`
> model (~80 MB) and the default `memory` backend — so nothing downloads the 1.3 GB
> production model and no extra services are needed. Production notes are called out
> inline. Commands are PowerShell (Windows); on Linux/macOS swap `$env:VAR = "x"`
> for `VAR=x` and `.\.venv\Scripts\python.exe` for `.venv/bin/python`. Run
> everything from the **project root** (the folder with `pyproject.toml`, `src/`,
> `docs/`), using the project venv.

---

## Quick reference

| Command | What it does | Loads model? | Needs pandoc? | Ends on |
|---|---|---|---|---|
| `convert` | Confluence HTML → GitLab Markdown | no | yes | `.md` files + report |
| `lint` | Report embedding-harmful syntax in **raw** `.md` | no | no | `quality-report.json` |
| `export` | Parse + enrich + **chunk** (no embedding) | **no** | yes | `.chunks.json` + `export-report.json` |
| `python -m sdd_pipeline.dump` | Dump AST + enriched model + chunks for **one** file | no | yes | `ast/enriched/chunks.json` |
| `scan` | Discover + persist the cross-corpus entity vocabulary | no | yes | vocabulary JSON |
| `scan-taxonomy` | Derive the section→field taxonomy from corpus tables | no | yes | `taxonomy.json` + field vocab |
| `index` | Full pipeline: chunk + **embed** + store | yes | yes | vector index |
| `search` | Query the index (dense, or `--hybrid`) | yes | no | ranked results |
| `tui` | Interactive search browser | yes | no | — |
| `check` | Report dependency / env availability | no | no | — |
| `eval_retrieval.py` | recall@k + MRR over a golden set | yes* | yes | scores + `RETRIEVAL_LOG.md` |

\* `eval_retrieval.py --mock` swaps in a deterministic hashing embedder, so it runs
with **no** model download (wiring check only — not a quality number).

The split that matters: **`export`, `dump`, `scan`, `scan-taxonomy`, `lint`, and
`convert` never load an embedding model.** You can do almost all onboarding,
vocabulary, taxonomy, and quality work model-free and fast, then `index` only when
you're ready to embed.

---

## Section 0 — Setup & mental model

### One-time setup

```powershell
# From the project root, in the project venv
.\.venv\Scripts\Activate.ps1            # or call .\.venv\Scripts\python.exe directly
pip install -e ".[dev]"                 # editable install + dev tools (incl. chroma)
sdd-pipeline check                       # confirm pandoc + deps are visible
```

`pandoc` must be on `PATH` for every command that parses Markdown (everything except
`lint`). On Windows, set `$env:PYTHONUTF8 = "1"` before commands that print emoji
(`index`, `check`) or process non-ASCII pages, to avoid a cp1252 console crash.

### The seven stages

A document flows through the same stages every time; commands just stop at different
points.

```
1 read .md
2 pandoc → JSON AST          (ast_parser)
3+4 AST → DocumentModel      (structural: section tree)
5 enrich                     (enrichment: section type, entities, tags, depends_on/exposes)
6 chunk                      (chunking: DocumentModel → list[SemanticChunk])
   └── export / dump STOP HERE  ← "chunk results"
7 embed + store              (embeddings + vector_store)
   └── index STOPS HERE         ← searchable
```

- **`export` / `dump`** run stages 2–6 → you get chunks, no vectors.
- **`index`** runs stages 2–7 → searchable.
- **`search`** runs stage 7's query side only.

A **chunk** (`SemanticChunk`) is the unit that gets embedded. It is not raw text — it
carries a structural header that is prepended at embed time
(`[section_type] breadcrumb | keywords: … | tags: …\n\n<content>`). Inspecting that
rendered `embed_text` is how you judge quality (Section 5).

### Dev vs production defaults

| | Dev (this guide) | Production |
|---|---|---|
| Model | `--model all-MiniLM-L6-v2` (~80 MB) | default `BAAI/bge-large-en-v1.5` (~1.3 GB) |
| Backend | `memory` (default; a JSON file) | `--backend chroma` (`pip install ".[chroma]"`) |
| Index dir | `./outbox/index` (default) | a persisted Chroma dir |

The `memory` backend stores the whole index in one `<persist_dir>/sdd_docs.json`
file and rewrites it after every indexed file — perfect at SDD-corpus scale, wrong
for very large corpora (use `chroma` there).

---

## Section 1 — Add a new document (ending on chunk results)

**Goal:** take a source document all the way to inspectable **chunks**, without
embedding. This is the right first pass for any new doc: it's fast, model-free, and
shows you exactly what will be embedded before you commit vectors.

### Concept

Chunks are produced deterministically (stages 2–6). The same input always yields the
same chunks, so you can iterate on the source and re-run instantly. The **chunk
hygiene gate** (Section 5) runs at `index` time and will *block* a file whose chunks
carry markup/macro residue — so catching problems now, at chunk stage, saves a failed
index later.

### Workspace note

Every command obeys the **inbox/outbox contract**: pipeline inputs live under
`inbox/` and outputs under `outbox/` (subfolders allowed). Drop your source files
in `inbox/` and let the defaults handle the rest. (See
[README → Workspace contract](../../README.md#workspace-contract).)

### Steps

**1. (If the source is Confluence HTML) convert it to Markdown, then promote the
clean files into the inbox corpus.** Place the raw HTML under the inbox
(e.g. `inbox\new-html\`):

```powershell
sdd-pipeline convert .\inbox\new-html --space ENG `
  --source-url "https://wiki/.../page" --labels "oms,architecture"
# → outbox\md\  (+ outbox\reports\conversion-report.json)
```

`convert` reads HTML from the inbox, writes Markdown with YAML frontmatter to
`outbox\md\`, and emits `outbox\reports\conversion-report.json`. Low-confidence
conversions are routed to a `_quarantine\` subdir (and the command exits
non-zero) — never index a quarantined file. Review the output, then **promote the
good Markdown into the inbox corpus** so the rest of the pipeline can consume it:

```powershell
Copy-Item .\outbox\md\* .\inbox\new\ -Recurse
```

If your source is already Markdown, skip convert and drop the `.md` straight into
`inbox\new\`.

**2. Lint the raw Markdown** (model-free, no pandoc) to catch embedding-harmful
residue before parsing:

```powershell
sdd-pipeline lint .\inbox\new        # → outbox\reports\quality-report.json
```

See Section 5 for what it flags. Fix `block`-severity issues at the source.

**3. Produce the chunks — model-free — with `export`:**

```powershell
sdd-pipeline export .\inbox\new --merge-prose      # → outbox\chunks\
```

This writes one `*.chunks.json` per input file (mirroring the tree) plus an
`export-report.json` (per-file + total chunk counts, success/failure). Open a
`.chunks.json` and read the `embed_text` field of each entry — that is the exact
string the model would embed.

- **`--merge-prose`** packs each section's consecutive prose into one chunk and drops
  context-free fragments (e.g. a lone *"The following options were considered:"*).
  **Recommended for most docs.**
- **`--merge-definitions`** also folds a section's *code* into the prose chunk (tables
  stay separate) so an instruction and its syntax share one vector. Use it for
  **reference/spec** docs; it overrides `--merge-prose`.
- **`--format jsonl`** if a downstream consumer wants line-delimited records.

**4. (Single file, deep inspection)** Dump all three model-free artifacts at once:

```powershell
python -m sdd_pipeline.dump .\inbox\new\my-page.md .\outbox\dump
```

Writes `ast.json` (raw pandoc), `enriched.json` (the `DocumentModel` with section
types / entities / tags applied), and `chunks.json`. This is the best way to see
*why* a chunk came out the way it did — the enriched model shows the section tree and
the tags before chunking.

**5. (Programmatic)** From a script or REPL:

```python
from pathlib import Path
from sdd_pipeline.pipeline import SemanticPipeline

pipe = SemanticPipeline()                      # embedder is lazy — never loaded here
chunks = pipe.process_file(Path("inbox/new/my-page.md"))   # stages 2–6
for c in chunks:
    print(c.section_type, c.breadcrumb, "->", len(c.to_embed_text()), "chars")
    print(c.to_embed_text())
```

### When you're ready to embed

```powershell
$env:PYTHONUTF8 = "1"
sdd-pipeline index .\inbox\new --model all-MiniLM-L6-v2 --merge-prose
# index lives in ./outbox/index (memory backend, default)
```

Then confirm it's searchable:

```powershell
sdd-pipeline search "your query here" --model all-MiniLM-L6-v2
```

> The `--model` and `--merge-*` flags you use at `index` time must be the ones you
> intend to keep — they affect the vectors and the chunking. Changing the model later
> forces a full re-index (Section 2).

---

## Section 2 — Update an onboarded document, avoiding a full re-index

**Goal:** re-process a document that's already in the index, touching only what
changed.

### Concept — read this first

Three facts govern everything here:

1. **A document's identity is its file path.** The internal `doc_id` is a hash of the
   absolute path, so editing a file's *content* keeps the same `doc_id`. Each chunk's
   id is `{doc_id}_{section_id}_{block_id}_{idx}`.
2. **Re-indexing is an upsert keyed by `chunk_id` — there is no document-level
   replace.** When you re-index a file, the pipeline embeds the new chunks and writes
   them by id; chunks whose ids are unchanged are overwritten in place.
3. **There is no change-detection.** Nothing tracks mtimes or hashes; every file the
   glob matches is fully reprocessed. "Avoid a full re-index" therefore means **scope
   the glob to the files that changed** — not "the tool skips unchanged files."

The consequence to internalize: re-indexing the **same path with the same heading
structure** is safe — ids are stable, so chunks are replaced cleanly. But if the
**structure changes** (a heading added, removed, renamed, or reordered), the new
chunks get *new* ids and the old ones are **orphaned** — nothing deletes them, so
stale/duplicate chunks linger in the index.

### Procedure A — content-only edit (same headings)

Re-index just that one file by pointing the glob at it:

```powershell
$env:PYTHONUTF8 = "1"
sdd-pipeline index .\inbox --glob "new\my-page.md" --model all-MiniLM-L6-v2 --merge-prose
```

The glob is evaluated under the input dir, so `--glob "new\my-page.md"` matches a
single file. Its chunks upsert in place; every other document is untouched. (The
`memory` backend still rewrites its one JSON file, but only this doc's chunks change.)

### Procedure B — structural change (headings added/removed/reordered)

Delete the document's old chunks first, then re-index the one file. There's no CLI
flag for the delete, so use a short snippet:

```python
from pathlib import Path
from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.vector_store import make_vector_store
from sdd_pipeline.pipeline import _stable_doc_id

config = PipelineConfig()          # reads PIPELINE_* env / .env
# If you indexed to a non-default location/backend, set these to match the index:
#   config.chroma_persist_dir = "./outbox/index"   (the --output / --index dir)
#   config.vector_store_backend = "memory"        (or "chroma")
store = make_vector_store(config)
removed = store.delete_document(_stable_doc_id(Path("inbox/new/my-page.md").resolve()))
print(f"removed {removed} old chunks")
```

Then run Procedure A. `delete_document` removes every chunk whose `doc_id` matches, so
no orphans survive the structural change.

> **Rule of thumb:** content tweak → Procedure A. Anything that moves or renames a
> heading → Procedure B. When unsure, Procedure B is always safe.

### Procedure C — a batch of changed files

Loop the per-file index over your changed set (e.g. from git):

```powershell
$env:PYTHONUTF8 = "1"
git diff --name-only HEAD~1 -- 'docs/**/*.md' | ForEach-Object {
    $rel = Resolve-Path $_ -Relative
    sdd-pipeline index .\inbox --glob ($_ -replace '^docs[\\/]', '') --model all-MiniLM-L6-v2 --merge-prose
}
```

For files that changed structurally, run the Procedure B delete for each first.

### What a full re-index *is* still required for

- **Changing the embedding model or provider.** The index records its embedder as
  *provenance*; `search` fails fast if your configured model/provider differs from the
  one that built the index (different models produce incompatible vector spaces).
  Re-index the whole corpus after any model/provider change.
- **A clean slate.** `make_vector_store(config).reset()` wipes the entire index (and
  its provenance) if you want to rebuild from scratch.

---

## Section 3 — Vocabulary & taxonomy for a new (single) document

Two independent things get attached during enrichment (stage 5): **entities** (the
domain terms a chunk mentions) and **taxonomy** (the `section_type`, plus structured
table fields). For a single doc, both are computed *per file*.

### 3a. Entities

**Concept.** `extract_entities` tags each section with terms it recognizes. It always
recognizes built-in patterns — services (PascalCase + `Service`/`Controller`/… ),
technologies (`PostgreSQL`, `Kafka`, `Kubernetes`, …), and protocols (`REST`, `gRPC`,
`JWT`, …). To recognize **your** project's terms (which no generic pattern catches),
inject them.

```powershell
# A JSON array of domain terms; merged into extract_entities for this run.
$env:PIPELINE_ENTITY_TERMS = '["XCom","triggerer","KPO","settlement-engine"]'
sdd-pipeline export .\inbox\new --output .\outbox\chunks --merge-prose
```

Then inspect a `.chunks.json` (or use `dump`) and read each chunk's `entities` and the
`keywords:` portion of its `embed_text` to confirm your terms now appear where they're
mentioned. Entities are recomputed **per chunk** from that chunk's own content, so a
term mentioned in one section won't bleed onto siblings.

### 3b. Taxonomy — section types

**Concept.** Every section gets a `SectionType` assigned automatically from its
**heading text**, by ordered first-match-wins substring rules. You don't configure
this per doc — you *steer* it by how you word headings. The full set:

`overview` · `architecture` · `api` · `decision` · `alternative` · `tradeoff` ·
`consequence` · `done_criteria` · `deployment` · `data_model` · `security` ·
`content` (the default when nothing matches).

A few representative triggers (first match wins, so more specific types are checked
first):

| Heading contains… | Becomes |
|---|---|
| "decision", "ADR", "rationale", "proposal", "why" | `decision` |
| "alternative", "options considered", "rejected" | `alternative` |
| "trade-off", "pros and cons" | `tradeoff` |
| "consequence", "impact", "risk", "drawback" | `consequence` |
| "acceptance criteria", "definition of done" | `done_criteria` |
| "security", "auth", "JWT", "RBAC", "encryption" | `security` |
| "entity", "database", "schema", "data model" | `data_model` |
| "overview", "introduction", "scope", "goals" | `overview` |
| "architecture", "components", "high-level", "diagram" | `architecture` |
| "API", "endpoint", "interface", "REST", "request" | `api` |
| "deployment", "infrastructure", "config", "CI/CD" | `deployment` |

So a heading **"Alternatives Considered"** yields `alternative`; renaming it to
**"Why we chose X"** yields `decision`. Verify the assignment in the `dump`
`enriched.json` (each section's `section_type`) or a chunk's `section_type` field.
These types are filterable at search time (`--section-type alternative`).

### 3c. Taxonomy — table fields (optional)

If the document has data tables and you want the field names treated as a taxonomy,
run `scan-taxonomy` over its folder (model-free):

```powershell
sdd-pipeline scan-taxonomy .\inbox\new --out .\outbox\taxonomy\taxonomy.json `
  --vocab-out .\outbox\taxonomy\field_vocabulary.json --min-docs 1
```

For a single doc, use `--min-docs 1` (a field need only appear once). This is more
relevant for a connected set — see Section 4c.

---

## Section 4 — Vocabulary & taxonomy for a connected set of documents

**Goal:** when several documents describe the same system, a term defined in one doc
should be recognized in **all** of them — even docs that only mention it in passing.

### Concept — the two-pass cross-corpus scan

Per-file enrichment can't do this: a term defined in doc A is invisible to doc B. The
fix is a shared vocabulary built in two passes:

1. **Pass 1 (discovery, model-free):** parse *every* doc, run `scan_corpus` to harvest
   entity candidates across the whole set (built-in patterns + ALLCAPS acronyms +
   backtick identifiers, minus a stoplist), seed it with your `PIPELINE_ENTITY_TERMS`
   and any previously saved vocabulary, and **persist** the result.
2. **Pass 2:** enrich/index every doc with that full vocabulary, so a term seen
   anywhere is tagged everywhere.

This is triggered by setting **`PIPELINE_ENTITY_VOCAB_PATH`**. When it's set,
`index`, `export`, and `scan` all run Pass 1 first.

### 4a. Build and review the vocabulary

Run discovery on its own so you can **review and edit** the term list before it drives
an index:

```powershell
$env:PIPELINE_ENTITY_TERMS = '["XCom","triggerer","KPO"]'   # optional seed terms
sdd-pipeline scan .\inbox\oms --vocab .\outbox\vocab\entity-vocab.json
```

This writes a sorted, deduplicated JSON array to `outbox/vocab/`. Open it, delete
noise, add terms the scan missed. The discovery is recall-broad on purpose, so
pruning is expected. To keep a reviewed vocabulary, **promote it into committed
config** — `outbox/` is gitignored, `config/` is not:

```powershell
Copy-Item .\outbox\vocab\entity-vocab.json .\config\entity-vocab.json   # then commit
```

(`config/entity-vocab.json` is a committed seed example with project terms like
`XCom`/`triggerer`/`KPO`.) Re-running `scan` **accumulates** — point `--vocab` at
the file you want to grow; it seeds from the existing file plus
`PIPELINE_ENTITY_TERMS`, so your edits and prior terms survive.

### 4b. Index (or export) with the shared vocabulary

Point the env var at your reviewed file; the scan now runs automatically first:

```powershell
$env:PIPELINE_ENTITY_VOCAB_PATH = ".\outbox\vocab\entity-vocab.json"
$env:PYTHONUTF8 = "1"
sdd-pipeline index .\inbox\oms --model all-MiniLM-L6-v2 --merge-prose
# or, model-free, to inspect chunks first:
sdd-pipeline export .\inbox\oms --output .\outbox\chunks --merge-prose
```

Every doc is now enriched with the corpus-wide vocabulary. (Leaving
`PIPELINE_ENTITY_VOCAB_PATH` unset reverts to per-file behavior from Section 3.)

### 4c. Cross-corpus field taxonomy

Derive a section→field taxonomy from the tables that recur across the set, keeping only
fields seen in at least N documents:

```powershell
sdd-pipeline scan-taxonomy .\inbox\oms --out .\outbox\taxonomy\taxonomy.json `
  --vocab-out .\outbox\taxonomy\field_vocabulary.json --min-docs 2
```

`taxonomy.json` holds `{section_key: {fields, orientation}}` (only fields with
document-frequency ≥ `--min-docs`); `field_vocabulary.json` lists every field with its
doc-frequency, so rare fields stay visible for human review. `--min-docs 2` is a good
default for "appears in more than one doc."

---

## Section 5 — Evaluating the quality of the generated semantics

Work three lenses, cheapest first. The first two are model-free.

### Lens 1 — source residue (`lint`)

**What:** a report-only linter over the **raw** `.md` (pure stdlib, no pandoc, no
model). It flags embedding-harmful residue but never blocks or rewrites anything.

```powershell
sdd-pipeline lint .\inbox\new --strict     # --strict → non-zero exit on any block issue
```

It writes `quality-report.json` and flags: `html_leakage` (leaked HTML tags),
`confluence_artifacts` (untranslated `{panel}`/`<ac:…>` macros — a **block**),
`code_ratio` (a doc that's mostly code), `link_density` (TOC/nav link-dumps),
`content_density` (near-empty stub — a **block**), and `orphaned_headings` (empty
sections). Prose checks run on a de-fenced copy, so code *examples* don't
false-positive. Point it at your real embedding corpus, not a docs tree that
*documents* Confluence syntax.

### Lens 2 — chunk hygiene (the binding gate)

**What:** the `lint` above is a pre-filter; it can't see the chunk transforms (merge,
table-summary, budget split) that happen *after* it. The **chunk hygiene gate** runs
on the produced `embed_text` and is the binding check wired into `index`. It is an
*invariant* check: after de-fencing, clean prose must contain no markup *shape* — no
HTML/`<ac:>` tag, no `{panel}` macro, no unrendered entity, no base64 blob, no
replacement char.

- **Poisoned** (residue or empty) → **blocks the file** (`index` raises
  `ChunkQualityError`).
- **Weak** (rendered `embed_text` over the ~1800-char budget, or over the 2048 hard
  cap) → **warns only** — truncation is model-dependent and not certifiable from a
  char count.

Inspect it **non-raising** before indexing via `export` (read `export-report.json`) or
programmatically:

```python
from pathlib import Path
from sdd_pipeline.pipeline import SemanticPipeline

pipe = SemanticPipeline()
chunks = pipe.process_file(Path("inbox/new/my-page.md"))
for rpt in pipe.gate_chunks(chunks):          # one report per chunk, never raises
    if rpt.issues:
        print(rpt.chunk_id, [(i.rule, i.severity, i.detail) for i in rpt.issues])
```

**What a healthy chunk looks like** (read the `embed_text`): a lean header (no markup
in the breadcrumb/keywords), the correct `section_type`, your domain entities present
in `keywords:`, data tables summarized rather than dumped, and total length within
budget.

### Lens 3 — retrieval quality (does it actually surface?)

**What:** the real test — can a query find the right section? The harness builds a
fresh index over a corpus and scores queries against a **frozen golden set**, reporting
`recall@k` and `MRR`.

```powershell
$env:PYTHONUTF8 = "1"
# Wiring smoke-test, no model download:
python src/tools/scripts/eval_retrieval.py --mock --no-log
# Real measurement with your configured embedder (set PipelineConfig to a real model):
python src/tools/scripts/eval_retrieval.py --corpus src/tools/eval/corpus `
  --queries src/tools/eval/queries.yaml
```

Results print per-category and append to `src/tools/eval/RETRIEVAL_LOG.md`. To measure
**your** new doc, add it to the corpus and add queries to `queries.yaml`:

```yaml
queries:
  - id: my-new-doc-q1
    text: "a real question a user would ask"
    category: paraphrase           # cross-reference | paraphrase | lexical-control
    expected:
      - { doc: my-page.md, section: "Heading Substring" }   # omit section for doc-level
```

`doc` is the path relative to the corpus root; `section` is a case-insensitive
substring of the chunk **breadcrumb**. Keep a balanced mix (cross-reference,
paraphrase, lexical-control) and **freeze** the golden set before recording a baseline
— never edit it to chase a score. See [`src/tools/eval/README.md`](../../src/tools/eval/README.md).

---

## Section 6 — Troubleshooting loop: doc added, something's wrong

Work the loop: **edit source → re-`export`/`dump` to inspect → `lint`/gate → eval →
re-index.** Match your symptom below.

### Symptom: `index` aborts with `ChunkQualityError`

A chunk is **poisoned** (markup/macro residue, or empty after de-fencing).

1. `sdd-pipeline lint <dir>` to spot source residue, and `gate_chunks` (Lens 2) to get
   the exact poisoned `chunk_id`s and reasons.
2. Fix at the **source** — re-run `convert` on the original HTML, or clean the `.md`
   (the residue usually came from a bad conversion, not from chunking).
3. `sdd-pipeline export` again and confirm the report is clean.
4. Re-index. *(Escape hatch for a one-off messy corpus you must index anyway:*
   `$env:PIPELINE_CHUNK_GATE = "false"` *— this disables the block; use sparingly.)*

### Symptom: too many tiny, context-free chunks

Fragments like a lone *"The following options were considered:"* are polluting the
index.

- Add **`--merge-prose`** (packs section prose, drops fragments). For reference/spec
  docs use **`--merge-definitions`** (also folds code into the prose chunk).
- If a doc yields **zero** chunks or one giant chunk, check the heading structure in
  `dump`'s `enriched.json`: content before the first heading (or a heading-less doc) is
  attached to a synthesized title-derived root section, so it shouldn't silently vanish
  — but a doc that's all one fenced code block can still lint as `code_ratio`.

### Symptom: wrong section types, or missing entities

- **Section type wrong:** reword the heading to hit the intended rule (Section 3b).
  Verify with `dump`'s `enriched.json`.
- **Entity missing:** add it to `PIPELINE_ENTITY_TERMS` (single doc) or to the
  cross-corpus vocabulary and re-`scan` (connected set, Section 4). Confirm via the
  chunk's `keywords:` in `embed_text`.

### Symptom: the doc is indexed but search won't surface it

1. **Provenance mismatch?** If `search` errors about embedder provenance, your
   `--model`/`--provider` differ from what built the index — align them or re-index.
2. **Try hybrid:** `sdd-pipeline search "…" --hybrid` (or `-H`) fuses dense + BM25,
   which rescues keyword-exact and short queries that pure dense ranking buries.
3. **Measure it:** add a golden query for the doc and run the harness (Lens 3) — a
   number tells you whether a change helped.
4. **Truncation warning?** If the gate warned a chunk's `embed_text` is over budget,
   the model may be truncating the tail — split the section or rely on `--merge-prose`
   to keep chunks lean.

### Symptom: stale or duplicate results after editing a doc

You edited headings (a structural change) and re-indexed without deleting — old chunks
were **orphaned**. Run Section 2 **Procedure B** (`delete_document` then re-index).

---

## Cheat-sheet: the full loop

```powershell
# 0. setup
.\.venv\Scripts\Activate.ps1; sdd-pipeline check

# 1. onboard → chunks (model-free, fast)
sdd-pipeline convert .\inbox\new-html                          # if HTML → outbox\md\
Copy-Item .\outbox\md\* .\inbox\new\ -Recurse                  # promote reviewed md to the corpus
sdd-pipeline lint .\inbox\new                                  # source residue → outbox\reports\
sdd-pipeline export .\inbox\new --merge-prose                  # inspect chunks → outbox\chunks\
python -m sdd_pipeline.dump .\inbox\new\page.md .\outbox\dump  # deep-dive one file

# 2. vocabulary / taxonomy
$env:PIPELINE_ENTITY_TERMS = '["XCom","triggerer"]'          # single-doc terms
sdd-pipeline scan .\inbox\new --vocab .\outbox\vocab\entity-vocab.json  # cross-corpus, then edit it
$env:PIPELINE_ENTITY_VOCAB_PATH = ".\outbox\vocab\entity-vocab.json"   # enable shared vocab

# 3. embed (only when chunks look right)
$env:PYTHONUTF8 = "1"
sdd-pipeline index .\inbox\new --model all-MiniLM-L6-v2 --merge-prose

# 4. verify & evaluate
sdd-pipeline search "a real user question" --model all-MiniLM-L6-v2 --hybrid
python src/tools/scripts/eval_retrieval.py --mock --no-log    # wiring; drop --mock for real

# 5. update one doc (content edit) — no full rebuild
sdd-pipeline index .\inbox --glob "new\page.md" --model all-MiniLM-L6-v2 --merge-prose
#   (structural edit? delete_document(doc_id) first — see Section 2B)
```

### Where to go deeper

- [`docs/learn/walkthroughs/01-life-of-a-document.md`](../learn/walkthroughs/01-life-of-a-document.md) — one doc traced through every stage with real `dump.py` JSON.
- [`docs/learn/tours/`](../learn/README.md) — per-module reading guides (enrichment, chunking, vocabulary, retrieval).
- [`src/tools/eval/README.md`](../../src/tools/eval/README.md) — the retrieval-evaluation harness in full.
- `CLAUDE.md` (repo root) — the authoritative architecture reference.
