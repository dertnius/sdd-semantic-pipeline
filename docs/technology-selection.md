---
title: "Technology Selection Rationale"
status: "Defense"
date: "2026-06-15"
companion_to: "docs/adr/adr-0001-modular-semantic-pipeline.md"
---

# Technology Selection Rationale

This document defends the **technology choices** of the SDD semantic pipeline.
It is a companion to [ADR-0001](adr/adr-0001-modular-semantic-pipeline.md),
which justifies the *architecture* (a modular, 7-stage, protocol-driven design).
Here the question is narrower: *given that architecture, why these specific
languages, libraries, and tools?*

## 1. Decision drivers

Every choice below is measured against the constraints the project actually has,
not against generic "best tool" opinions:

| # | Driver | What it demands of the stack |
|---|---|---|
| D1 | **Deterministic preprocessing** | Parsing, structural modelling, enrichment, and chunking must produce identical output for identical input — no hidden state, no network. |
| D2 | **Fast, model-free unit tests** | The default test lane must run with no ML model download and no external service, so iteration stays in seconds. |
| D3 | **Substitution safety** | Embedding provider (local ↔ Azure) and vector store (memory ↔ Chroma) must be swappable behind a protocol without touching orchestration. |
| D4 | **Offline reproducibility** | The pipeline must run on a developer laptop or air-gapped CI with no SaaS dependency for the core path. |
| D5 | **Domain fit (Confluence/SDD)** | Inputs are Confluence-exported Markdown/HTML with macros, tables, and code; the tooling must handle that document shape faithfully. |
| D6 | **Single-maintainer maintainability** | A small team must own the whole stack; prefer well-documented, mainstream, typed libraries over bespoke or niche ones. |

## 2. The stack at a glance

| Layer | Chosen technology | Primary driver(s) |
|---|---|---|
| Language / runtime | **Python ≥ 3.11** | D5, D6 — the NLP/embedding ecosystem is Python-native |
| Document AST | **pandoc** + **panflute** | D1, D5 — universal, deterministic Markdown→AST |
| HTML pre-clean | **BeautifulSoup4** + **lxml** | D5 — robust, lenient HTML parsing for Confluence exports |
| Config & data contracts | **pydantic v2** + **pydantic-settings** | D3, D6 — validated, typed, env-driven config |
| CLI | **Typer** + **Rich** | D6 — typed CLI with minimal boilerplate |
| Embeddings | **sentence-transformers** (local) / **openai** (Azure) behind `EmbedderProtocol` | D2, D3, D4 |
| Vector store | **langchain-core** `InMemoryVectorStore` (default) / **ChromaDB** (optional) behind `VectorStoreProtocol` | D2, D3, D4 |
| Retrieval | dense vectors + **BM25** lexical, fused with **RRF** (in-house) | D5 |
| Tooling | **pytest**, **ruff**, **mypy** | D1, D2, D6 |

## 3. Per-choice defense

### 3.1 Python 3.11+

The embedding, NLP, and document-tooling ecosystem (sentence-transformers,
panflute, langchain, chromadb) is Python-first; any other language would mean
re-implementing or shelling out to these libraries. Python 3.11 specifically
buys typed `Self`, faster interpreter, and mature `dataclasses`/`typing` that the
pure-data `models.py` layer relies on. **Rejected:** Node/TypeScript (weaker
embedding/NLP ecosystem) and Go/Rust (fast, but would force FFI to the same
Python ML libraries — complexity with no offsetting gain at this scale).

### 3.2 pandoc + panflute for the document AST

Confluence exports are Markdown with non-trivial structure (nested headings,
tables, code, macros). Re-parsing Markdown by hand with regex is the classic
source of silent corruption. **pandoc** is the de-facto universal document
converter and produces a stable JSON AST; **panflute** gives a typed,
in-process walk over that AST. The combination is **deterministic** (D1) and
**faithful to the real document shape** (D5). The boundary is enforced:
`ast_parser.py` is the *only* pandoc caller, so the subprocess dependency is
isolated and mockable. **Rejected:** `markdown-it`/`mistune` (Markdown-only, less
faithful on tables/macros) and regex extraction (non-deterministic at the edges,
unmaintainable).

> Trade-off acknowledged: pandoc is an external binary on `PATH`. This is the
> reason model/pandoc-dependent tests are marked `slow` and excluded from the
> default lane (D2) — the cost is contained rather than spread across the suite.

### 3.3 BeautifulSoup4 + lxml for HTML pre-clean

The HTML→GitLab-Markdown converter must ingest *rendered* Confluence HTML, which
is messy and frequently non-well-formed. **BeautifulSoup** is lenient (it repairs
broken markup instead of failing) and **lxml** gives it a fast, C-backed parser.
This is exactly the resilience profile needed for real-world export HTML (D5).
**Rejected:** strict XML parsers (`ElementTree`) that reject malformed input —
unacceptable for scraped HTML.

### 3.4 pydantic v2 + pydantic-settings for config and contracts

Configuration loads from env vars (`PIPELINE_*`) or `.env`, with validation and
typed defaults — **pydantic-settings** does this declaratively, which keeps the
many tunables (chunk budgets, gate toggles, hybrid params, provider creds) honest
and self-documenting (D3, D6). pydantic v2's Rust core makes validation cheap.
Secrets stay env-only by design. **Rejected:** hand-rolled `os.environ` parsing
(error-prone, untyped) and `dynaconf`/`configparser` (heavier or less typed).

### 3.5 Typer + Rich for the CLI

The pipeline is operated through one CLI (`sdd-pipeline`) with many subcommands
(`index`, `search`, `export`, `scan`, `convert`, `lint`, `tui`). **Typer** derives
the CLI from type-annotated functions — the same typing discipline as the rest of
the codebase, minimal boilerplate (D6) — and **Rich** gives readable tables and
progress without manual ANSI handling. **Rejected:** `argparse` (verbose,
untyped) and `click` (Typer is a typed layer over click, so we get click's
robustness with less code).

### 3.6 sentence-transformers + Azure OpenAI, behind a protocol

Semantic retrieval needs embeddings. **sentence-transformers** runs *locally*
with no SaaS dependency, which satisfies offline reproducibility (D4) and lets
the default dev model be tiny (`all-MiniLM-L6-v2`, ~80 MB) while production can
use a stronger model (`BAAI/bge-large-en-v1.5`). For teams that prefer managed
inference, **Azure OpenAI** is available behind the *same* `EmbedderProtocol`, so
swapping providers never touches orchestration (D3). Provenance `(provider,
model, dimension)` is recorded with the index and checked at query time so
incompatible vector spaces fail loudly. **Rejected:** a hard dependency on any
single hosted embedding API (breaks D4 and vendor-locks the core path).

### 3.7 langchain-core InMemoryVectorStore + ChromaDB, behind a protocol

The default vector store is **langchain-core's `InMemoryVectorStore`**, persisted
as a JSON file. This means the core index→search path has **zero heavyweight
dependencies and no service to stand up** — unit tests exercise the real search
contract with an injected hashing embedder (D2), and a laptop run "just works"
(D4). For corpora that outgrow RAM, **ChromaDB** is an optional extra behind the
same `VectorStoreProtocol`, selected by config. Choosing langchain-*core* (not
full `langchain`) is deliberate: we take the small, stable vector-store interface
without pulling in the large, fast-moving framework (D6). **Rejected:** making
Chroma/FAISS/pgvector mandatory (forces infra onto every dev and every test) and
adopting full LangChain (dependency weight and churn we don't need).

### 3.8 In-house BM25 + Reciprocal Rank Fusion for hybrid retrieval

SDD queries mix conceptual intent ("how do we handle retries") with exact tokens
(`XCom`, `triggerer`, error codes). Pure dense retrieval misses rare exact terms;
pure lexical misses paraphrase. We fuse a dense ranking with a **BM25** lexical
ranking via **Reciprocal Rank Fusion** — a small, well-understood, dependency-free
algorithm that needs no score calibration between the two rankers (D5). Keeping
it in-house avoids another framework dependency for ~100 lines of well-tested
code. **Rejected:** a re-ranking model (latency + another model to host) and
relying on a backend's proprietary hybrid mode (vendor lock, breaks D3).

### 3.9 pytest + ruff + mypy for the toolchain

- **pytest** — the determinism of D1 is only valuable if it is *verified* cheaply;
  pytest's fixtures and markers implement the fast/`slow`/`integration` split that
  keeps the default lane model-free (D2).
- **ruff** — one fast tool for both lint and format, replacing the
  flake8+isort+black trio with a single config and a single pass (D6).
- **mypy** — the codebase leans on types (dataclasses, protocols, pydantic);
  static checking enforces the very boundaries the architecture depends on (D3).

## 4. How the choices reinforce each other

The stack is coherent, not a pile of independent picks:

- **Determinism is layered, not assumed.** pandoc/panflute give a stable AST,
  the deterministic stages transform it, and pytest *proves* the result is stable
  in milliseconds — D1 and D2 are the same design seen from two sides.
- **The protocol seam is the load-bearing idea.** `EmbedderProtocol` and
  `VectorStoreProtocol` mean the two "expensive/external" choices (embeddings,
  vector store) are the *only* swappable ones, and everything else stays pure and
  offline. That is what makes "memory default, Chroma optional" and "local
  default, Azure optional" possible without conditionals leaking through the code.
- **Defaults are zero-infrastructure.** Local model + in-memory store + JSON
  persistence means the happy path needs no SaaS, no DB, and no GPU — the project
  is reproducible on any laptop and in plain CI (D4), with heavier options gated
  behind extras for when scale demands them.

## 5. Summary

The technologies were not chosen for novelty but for *fit*: each is the
mainstream, well-documented, typed option that satisfies a concrete project
driver, and the few external/heavy dependencies are quarantined behind protocols
and `slow`-marked tests so the default experience stays deterministic, fast, and
offline. Where a heavier or hosted alternative exists, it is supported as an
*optional* swap rather than a baseline requirement — preserving reproducibility
without sacrificing scale.
