# Demo runbook — SDD Semantic Pipeline

A step-by-step live demo to accompany `sdd-pipeline-overview.md`. Every command
here was **run against this repo** while writing the deck; the "Expected output"
blocks are the real results. Steps 0–3 are **model-free** (pandoc only — seconds,
no GPU, no download). Steps 4–6 need a one-time model install.

> Run everything from the repo root, using the project venv.
> On Windows, prefix once per shell so output is UTF-8 and the package resolves:
> ```powershell
> $env:PYTHONUTF8 = "1"; $env:PYTHONPATH = "src"
> $py = ".\.venv\Scripts\python.exe"        # or: sdd-pipeline (if pip-installed)
> ```
> POSIX: `export PYTHONUTF8=1 PYTHONPATH=src` and use `.venv/bin/python`.
> Invoke the CLI as `& $py -m sdd_pipeline.cli <command>` (shown below as
> `sdd-pipeline <command>` for brevity).

---

## 0 · Verify the environment  (model-free, instant)

```powershell
sdd-pipeline check
```

**Expected:** a table — `Python 3.13`, `pandoc 3.9.0.2`, `panflute`,
`langchain_core`, `pydantic`, `typer` all ✓. (`sentence_transformers` shows
NOT INSTALLED until step 4 — that's expected; the demo through step 3 doesn't
need it.)

**Talking point:** the whole front half of the pipeline runs with nothing but
pandoc. That's deliberate — fast CI, cheap iteration.

---

## 1 · Convert a real Confluence HTML export → clean Markdown  (model-free)

```powershell
# Put a rendered Confluence "Export to HTML" file under inbox/ first, then:
sdd-pipeline convert            # inbox/**/*.html  →  outbox/md/
```

**Expected output (real, from the demo corpus):**

```text
    Conversion totals
┌───────────────┬───────┐
│ Metric        │ Count │
├───────────────┼───────┤
│ sections      │     9 │
│ pictures      │     1 │
│ code_snippets │     5 │
│ lists         │     9 │
│ tables        │     4 │
│ urls          │     4 │
└───────────────┴───────┘
Done. 1/1 files converted (0 quarantined, 0 failed, 2 warning(s)).
```

The produced Markdown carries **provenance frontmatter** harvested from the page
chrome — open `outbox/md/...md` and show:

```yaml
---
title: Order Management Service — SAD
author: Jane Smith
space: ARCH
date: Mar 02, 2024
page_id: '98765'
source_file: order-management-sad.html
---
```

**Talking point:** macros, lozenges, and layout cruft are gone; `author`/`space`/
`page_id` survive as structured metadata that search can filter on later.

---

## 2 · Convert a Word .docx → Markdown  (model-free, the path we're finishing)

```powershell
# inbox/demo-with-image.docx is committed sample input
sdd-pipeline convert-docx -v
```

**Expected output (real):**

```text
Found 1 .docx files in inbox
  ok   demo-with-image.docx -> 1 sections, 0 pictures, 0 code_snippets, ...
Done. 1/1 files converted (0 failed, 0 warning(s)).
Report -> outbox\reports\docx-conversion-report.json
```

Open `outbox/md/demo-with-image.md` to show the YAML frontmatter (`title`, `date`,
`source_file`) and the `<figure>` referencing the embedded image, which was
extracted to `outbox/md/media/rId9.png`.

**Talking point:** a dedicated `convert-docx` command, same base layer and
provenance frontmatter as the HTML path — one converter contract, two source
formats. This is the active branch (`feat/docx-to-md`).

---

## 3 · The "smart" middle with NO model — enrich + chunk 5 real SAD docs

```powershell
sdd-pipeline export src/tools/eval/corpus --merge-prose -f jsonl -o outbox/chunks/demo
```
> (`src/tools/eval/corpus/` holds 5 real SDD/ADR documents — uses
> `PIPELINE_ENFORCE_WORKSPACE=false` since it reads from the eval folder, not `inbox/`.)

**Expected output (real):**

```text
Found 5 markdown files in src\tools\eval\corpus
Exporting... 100%
Done. 5/5 files exported (107 chunks, 0 failed).
Report -> outbox\chunks\demo\export-report.json
```

Now show **one enriched chunk** — this is the demo's money shot:

```json
{
  "breadcrumb":   ["Introduction", "Purpose"],
  "section_type": "overview",
  "genre":        "narrative",
  "entities":     ["retailnexus order management system",
                   "enable architecture review board", "..."],
  "depends_on":   [],
  "exposes":      [],
  "space":        "ARCH",
  "embed_text":   "[overview] Introduction > Purpose | genre: narrative | keywords: ...\n\n<the actual prose>"
}
```

**Talking point:** a generic vector DB would embed raw text. We embed **typed,
located, entity-tagged** context. `section_type` + `breadcrumb` are what let a
query say *"only search the decisions"* — and `depends_on`/`exposes` are what make
"which services consume `order.created`?" answerable. **No model was loaded to
produce any of this.**

---

## 4 · Build the vector index  (needs the model — one-time install)

```powershell
pip install ".[dev]"            # one time: pulls sentence-transformers + torch
sdd-pipeline index inbox/ --model all-MiniLM-L6-v2     # ~80 MB dev model
```

**Expected:** per-file chunk counts, then the index persisted under
`outbox/index/` with a `.provenance.json` sidecar recording the embedder identity.

**Talking point:** the index remembers *which* embedder built it. Search with a
different one is refused — no silently-wrong results (robustness gate #3).

---

## 5 · Search — semantic, filtered, hybrid

```powershell
sdd-pipeline search "Which services consume the order.created event?" --hybrid
sdd-pipeline search "how are external users signed in?" --section-type security
```

**Expected:** a ranked table (score · breadcrumb · section type · preview). The
first query is a **cross-reference** question (paraphrased, no keyword overlap) —
the case enrichment + hybrid (dense + BM25 via Reciprocal Rank Fusion) is built to
win. The second shows a **filter** narrowing to one section type.

**Talking point:** these exact queries live in the frozen golden set
(`src/tools/eval/queries.yaml`) — so retrieval quality is *measured*, not asserted.

---

## 6 · Ground GitHub Copilot  (the payoff)

```powershell
sdd-pipeline mcp               # stdio MCP server; Copilot's ADR agent connects to it
```

In VS Code, Copilot's **ADR-generator agent** (`.github/agents/adr-generator.agent.md`)
calls `find_decision_context(topic)` as its step 0, gets snippets pre-grouped onto
the ADR template (context / decision / alternatives / trade-offs / consequences),
and drafts an ADR **cited to our own documents**.

**Talking point:** this closes the loop the deck opened with — the AI now writes
from *our* architecture instead of guessing.

---

## If something fails in the room

| Symptom | Fix |
|---|---|
| `No module named 'sdd_pipeline'` | `$env:PYTHONPATH = "src"` (or `pip install -e ".[dev]"`) |
| Emoji / encoding crash on Windows | `$env:PYTHONUTF8 = "1"` |
| `convert` exits non-zero | a page was **quarantined** (low confidence) — that's the gate working; show `outbox/md/_quarantine/` |
| Step 4 too slow / offline | skip it — steps 0–3 are the model-free demo and stand on their own |
| Input "outside inbox" rejected | expected (workspace contract); `export` above sets `PIPELINE_ENFORCE_WORKSPACE=false` |
