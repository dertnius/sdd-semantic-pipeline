---
marp: true
theme: default
paginate: true
size: 16:9
header: 'SDD Semantic Pipeline · POC review'
style: |
  section { font-size: 26px; }
  h1 { color: #1f6feb; }
  h2 { color: #1f6feb; border-bottom: 2px solid #d0d7de; padding-bottom: 4px; }
  code { font-size: 0.78em; }
  pre { font-size: 0.62em; line-height: 1.25; }
  table { font-size: 0.78em; }
  strong { color: #0a3069; }
  section.lead { text-align: center; }
  section.lead h1 { font-size: 1.6em; }
  .small { font-size: 0.75em; color: #57606a; }
  .ok { color: #1a7f37; font-weight: 600; }
  .pending { color: #9a6700; font-weight: 600; }
---

<!-- _class: lead -->
<!-- _paginate: false -->
<!-- _header: '' -->

# SDD Semantic Pipeline

### Turning our architecture docs into something an AI can actually use

**Proof-of-concept review** — engineering deep-dive

<span class="small">Confluence / Word → clean Markdown → semantic search → grounded Copilot</span>

<!-- Audience: technical management. Goal of this deck: show the bet, the architecture, a live demo, and an honest status. -->

---

## The problem we set out to solve

Our Software Design Documents (SADs, ADRs, runbooks) hold the architecture knowledge that matters most — and it is **trapped**:

- Locked in **Confluence HTML exports** and **Word `.docx`** — not machine-readable, full of macros, lozenges, layout cruft.
- **AI coding assistants can't see it.** GitHub Copilot writing an ADR has no grounding in *our* decisions → it guesses, or it hallucinates.
- Authoring a new ADR means a human re-reading five old documents first. **Slow, and it doesn't scale.**

> **The bet:** if we can turn that messy corpus into a clean, *searchable* knowledge base, we can ground AI on our own architecture — and stop re-deriving context by hand.

<!-- Frame it as a knowledge-access problem, not a "build a search engine" problem. -->

---

## The solution in one picture

Two cooperating flows. **Documents in → grounded answers out.**

```text
  SOURCES                 FLOW B · CONVERT             FLOW A · INDEX + SEARCH  (7 stages)
  ───────                 ────────────────             ───────────────────────────────────
  Confluence HTML ─┐                                   pandoc AST  →  structural model
                   ├──►   clean GitLab Markdown   ──►   →  semantic enrichment
  Word .docx      ─┘      + YAML provenance            →  chunking
                         (quarantine low-confidence)   →  embeddings (local | Azure)
                                                        →  vector store (memory | Chroma)
                                                        →  hybrid search (dense + BM25 · RRF)
                                                                      │
                                                                      ▼
                                                        MCP server → Copilot ADR agent (RAG)
```

- **One module per stage.** The core is **deterministic** (no model, no network) — so it's fast to run and trivial to unit-test.
- **Pluggable at the edges:** embedder = local `sentence-transformers` *or* Azure OpenAI; store = in-memory *or* ChromaDB.

<!-- Stress: the "smart" parts (embedder/store) are swappable; the value is in the deterministic enrichment in the middle. -->

---

## What's actually built — engineering rigor

This is a POC, but it's built like a product. Numbers from this repo, today:

| Signal | Value |
|---|---|
| Fast test suite | **664 passing**, 2 skipped (`~11s`, no model/pandoc needed) |
| Code / test size | 11.5k LOC shipped · **8.6k LOC of tests** |
| CLI surface | 12 commands (`convert · convert-docx · index · search · export · lint · mcp · …`) |
| Robustness gates | **3** — chunk-hygiene · converter-quarantine · index-provenance |

**The gates are the interesting part** (they keep a RAG index trustworthy):

- **Chunk-hygiene gate** — a chunk with leaked markup/macro residue *blocks the whole file* from the index instead of poisoning search.
- **Converter quarantine** — a low-confidence conversion is routed aside (non-zero exit), never into the corpus.
- **Index provenance** — the index records `(provider, model, dim)`; a mismatched embedder is **refused**, not silently wrong.

<!-- For a technical audience the gates land harder than the feature list — they show we thought about garbage-in. -->

---

## What's actually built — reach & integration

The pipeline isn't a script; it has a front door for every consumer:

- **Grounds GitHub Copilot** — a stdio **MCP server** exposes semantic search to Copilot's *ADR-generator agent*. `find_decision_context(topic)` maps retrieved snippets straight onto the ADR template (context / decision / alternatives / trade-offs / consequences). **This is the payoff slide-3 promised.**
- **Interactive search TUI** — keep the model warm, query live, filter by section type / space, toggle hybrid.
- **Ships as a container** — production `Containerfile`, Podman Compose, **AKS batch Job**, plus devcontainer / DevPod / Dev Spaces for reproducible dev.
- **Model-free fast lane** — `convert · export · scan · lint` need **only pandoc**, no 1.3 GB model download. CI and iteration stay cheap.
- **Quality instrument** — a **frozen golden query set** (22 queries · cross-reference / paraphrase / lexical-control) + an append-only retrieval log, so any ranking change is measured, not vibes.

<!-- The model-free lane is why we can demo most of this live with zero GPU and zero downloads. -->

---

<!-- _class: lead -->

# Demo

### Real commands, real documents, run from this repo

<span class="small">Two parts: a live script you can run now (model-free), and the real captured output</span>

---

## Demo · part 1 — the live script

Model-free path — runs in seconds, no GPU, no model download:

```powershell
# 0 · verify the environment (pandoc + deps)
sdd-pipeline check

# 1 · Confluence HTML export  →  clean GitLab Markdown (+ provenance frontmatter)
sdd-pipeline convert            # inbox/*.html  →  outbox/md/

# 2 · Word .docx  →  Markdown   (the path we're finishing now)
sdd-pipeline convert-docx       # inbox/*.docx →  outbox/md/  (image → media/)

# 3 · the "smart" middle, with NO model: enrich + chunk 5 real SAD docs
sdd-pipeline export src/tools/eval/corpus --merge-prose   # → 107 enriched chunks
```

Then the **grounded** path (one-time `pip install ".[dev]"` for the local model):

```powershell
sdd-pipeline index  inbox/ --model all-MiniLM-L6-v2        # build the vector index
sdd-pipeline search "Which services consume the order.created event?" --hybrid
sdd-pipeline mcp                                            # serve RAG to Copilot
```

<span class="small">Full runbook with expected output: <code>docs/presentation/demo-script.md</code></span>

---

## Demo · part 2 — real captured output

**Convert** — one real Confluence export, deterministically structured:

```text
sections 9 · pictures 1 · code 5 · lists 9 · tables 4 · urls 4
frontmatter: title / author: Jane Smith / space: ARCH / page_id: 98765
```

**Export** — 5 real SAD docs → **107 enriched chunks, model-free, ~1s**. Every chunk knows what it *is*:

```json
"breadcrumb":   ["Introduction", "Purpose"],
"section_type": "overview",
"entities":     ["retailnexus order management system", "architecture review board", ...],
"embed_text":   "[overview] Introduction > Purpose | keywords: ... \n\n<content>"
```

<span class="ok">✓ 664 tests green</span> &nbsp;·&nbsp; that `section_type` + `breadcrumb` is what lets search filter to *just the decisions* — the part a generic vector DB can't do.

<!-- Walk them through the JSON: the enrichment is the moat. A plain chunker gives you text; we give you typed, located, entity-tagged context. -->

---

## Results & honest status

<span class="ok">**Done and proven**</span>

- End-to-end deterministic pipeline + converter, **664 tests**, 3 robustness gates.
- HTML→MD and **docx→MD** (finishing on `feat/docx-to-md`), with provenance frontmatter.
- Copilot/MCP grounding, TUI, full containerization (Podman / AKS).
- Retrieval **instrument validated** as sensitive on the frozen golden set.

<span class="pending">**Open — needs a decision, not more code**</span>

- **Production embedder:** local `bge-large` (free, ~1.3 GB, self-hosted) **vs** Azure OpenAI (no download, per-call cost, data leaves the box).
- The real retrieval **quality baseline** is intentionally *pending* that choice — the harness records it the moment we pick.

---

## Next steps

1. **Pick the embedder** (local vs Azure) → unblocks everything downstream.
2. **Record the baseline** — run the eval harness over the full corpus; lock the recall@k / MRR number we improve against.
3. **Point Copilot's ADR agent at the live index** — measure: does grounded drafting beat blank-page drafting?
4. **Scale the store** to ChromaDB if/when the corpus outgrows in-memory.

> **Ask:** a decision on the embedder + access to the full SDD corpus. The pipeline is ready to ingest it.

<span class="small">Repo: this branch · `feat/docx-to-md` · `sdd-pipeline --help` for the full CLI</span>

<!-- Close on a concrete ask so the meeting produces a decision, not just nods. -->
