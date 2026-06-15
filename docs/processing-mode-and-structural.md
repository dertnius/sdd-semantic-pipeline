---
title: "Processing Mode & Structural Design Rationale"
status: "Defense"
date: "2026-06-15"
companion_to:
  - "docs/technology-selection.md"
  - "docs/adr/adr-0001-modular-semantic-pipeline.md"
---

# Processing Mode & Structural Design Rationale

This document defends two linked design decisions:

1. **The processing *mode*** — the pipeline's preprocessing (structural modelling,
   enrichment, chunking, quality) is **deterministic and rule-based**, *not*
   LLM/ML-driven.
2. **The structural stage** ([`structural.py`](../src/sdd_pipeline/structural.py)) —
   *how* the raw document AST is turned into a typed section tree, and why each
   choice there follows from the mode in (1).

It complements [technology-selection.md](technology-selection.md) (which library)
and [ADR-0001](adr/adr-0001-modular-semantic-pipeline.md) (which architecture);
this one is about *method*.

---

## Part 1 — The mode: deterministic, rule-based preprocessing

### 1.1 The decision

Everything between "raw document" and "vector" — AST parsing, structural
modelling, semantic enrichment, chunking, and the quality gate — is implemented
as **pure, deterministic functions over typed data**. The same input always
produces byte-identical output. The *only* learned/statistical component in the
whole pipeline is the embedding step itself, and even that is isolated behind a
protocol (see [technology-selection.md §3.6](technology-selection.md)).

> The line is drawn deliberately: **deterministic where the output is a
> contract, statistical only where the task is inherently semantic
> (embedding).**

### 1.2 Why this mode (decision drivers)

| # | Property the mode buys | Why it matters here |
|---|---|---|
| M1 | **Reproducibility** | Re-running the pipeline on the same corpus yields the same chunks and the same index — required for a defensible, auditable retrieval system. |
| M2 | **Unit-testability without a model** | Deterministic functions are asserted with plain `==` in milliseconds; the default test lane needs no model download and no GPU (the fast/`slow` split). |
| M3 | **Auditability / explainability** | Every section type, entity, and chunk boundary can be traced to a *specific rule* a reviewer can read — not to opaque model weights. |
| M4 | **Zero inference cost & latency** | No per-document LLM calls means indexing a corpus is cheap, fast, and runs offline / air-gapped. |
| M5 | **No hallucination surface** | A rule cannot invent a section type, fabricate an entity, or silently rewrite content. Failure modes are *misses*, not *fabrications* — which are detectable and fixable. |
| M6 | **Stable provenance** | Deterministic IDs (`md5`-derived block/section IDs) mean a chunk's identity is reproducible across runs, which provenance and re-indexing depend on. |

### 1.3 Why not an LLM/ML pipeline for these stages

| Rejected approach | Why rejected |
|---|---|
| **LLM extracts sections/entities/chunks** | Non-deterministic (same input → different output across runs/versions), incurs per-document cost and latency, requires network/SaaS (breaks offline reproducibility), and can hallucinate structure that isn't in the source. Untestable by equality. |
| **ML sequence model for section classification** | Needs labelled SDD training data we don't have, adds a model artifact to version and host, and is *less* explainable than a keyword rule for a domain whose section names are highly conventional ("Decision", "Alternatives Considered", "Quality Attributes"). |
| **NER model for entity extraction** | Heavyweight and imprecise for this domain; the entities that matter are project identifiers (`XCom`, `triggerer`, `KPO`) better caught by precise patterns + an injectable vocabulary than a general-purpose NER. |

The SDD/ADR domain is the key enabler: section names follow templates and
entities are largely identifiers and ALL-CAPS acronyms. That regularity is
exactly what makes **rules competitive with — and more auditable than — a model**
for these stages.

### 1.4 How the mode is realised (concrete, not aspirational)

- **Enrichment** is an **ordered rule table**, `_SECTION_RULES` — first match
  wins, matched as plain substrings. Ordering encodes priority deliberately
  (`DECISION` before architecture `design`; `SECURITY` before deployment
  `config`), with documented guards against substring collisions (`contra` ⊂
  `contract`). A reviewer can read and amend the taxonomy directly.
- **Entity extraction** is precise regex (`_ALLCAPS_PATTERN`, `_BACKTICK_PATTERN`)
  plus an **injectable vocabulary** (`PIPELINE_ENTITY_TERMS` / the two-pass
  `scan_corpus`), so domain terms are added as *data*, never code changes.
- **Chunking** is a deterministic split with an explicit char budget
  (`embed_char_budget`) and a header-reserve estimate, so chunk boundaries are a
  pure function of the section and the configured budget.
- **The quality gate** is a stdlib-`re`, structural-absence check — it asserts
  *invariants* (no markup shape survives into embed text), which only a
  deterministic check can guarantee.

The boundary is enforced architecturally: `structural.py`, `enrichment.py`, and
`chunking.py` import **no** service, no network, no model — verifiable by reading
their imports.

---

## Part 2 — The structural stage: why it's built this way

`structural.py` turns the pandoc JSON AST into a typed `DocumentModel` (a tree of
`Section` → `ContentBlock`). Every decision below is a consequence of the mode in
Part 1: be faithful, be deterministic, lose no content.

### 2.1 Walk a real AST with panflute — never re-parse Markdown by hand

The module consumes the pandoc AST through **panflute** and dispatches on real
node types (`pf.Header`, `pf.Para`, `pf.Table`, …). It does **not** regex over
Markdown text. This is what makes the structural output *faithful* (it reflects
the document pandoc actually parsed) and *deterministic* (a typed tree walk, no
heuristic text matching). It also keeps the architectural rule intact: pandoc is
invoked only in `ast_parser.py`; `structural.py` only ever sees the AST.

### 2.2 Structure-preserving serializers, not `pf.stringify`

The obvious shortcut — flatten every node with `pf.stringify` — is **rejected on
purpose**. Flattening destroys the signal embeddings rely on. Instead each block
type has a dedicated serializer that **keeps semantic markers**:

- inline `code` keeps its backticks, so identifiers survive entity regexes;
- links render as `text (host)` — the human-readable anchor plus a compact target
  hint, dropping asset-URL noise;
- lists preserve numbering and nesting (continuation lines under the marker), so
  item boundaries like `- Pro arguments` vs `- Contra arguments` survive;
- tables render as GitHub pipe tables with the header row kept (and `|` escaped),
  so column semantics are recoverable downstream;
- definition lists render as `term — definition` (previously dropped entirely by
  pandoc's default handling — a real content-loss bug this design closes);
- code blocks keep their fence + language marker, which is what later activates
  enrichment's `lang:` tag rule.

Each serializer choice is made *for the downstream embedding and enrichment
stages* — structure is preserved precisely where it carries retrieval signal.

### 2.3 Faithful hierarchy via a level-tracking stack

Heading nesting is reconstructed with an explicit ancestor **stack**: on each
`Header`, pop until a valid parent (lower level) remains, attach, and push. This
yields the correct `subsections` tree and a `breadcrumb` for every section — the
breadcrumb that later becomes the embed-text context prefix. It is a standard,
deterministic, O(n) algorithm with no ambiguity.

### 2.4 The synthesized preamble root — no page silently yields zero chunks

This is the most important *robustness* decision in the module. Content that
appears **before the first heading** (or in a heading-less page) would otherwise
be attached to nothing and dropped. Because a Confluence page's title is
harvested into *metadata* and is **not guaranteed** to be re-emitted as a body
H1, a real page could silently produce **zero chunks** — an invisible
data-loss failure. So such blocks are buffered and, if any exist, attached to a
**synthesized title-derived root section** (and a warning is logged). The
invariant "a non-empty page always produces at least one chunk" is guaranteed
*structurally*, which only a deterministic stage can promise.

### 2.5 Deterministic, reproducible IDs

Block and section IDs are short `md5` hashes of stable inputs (`doc_id`, title,
level, index). They are reproducible across runs and processes — which is what
provenance, re-indexing, and stable chunk identity (M6) depend on. A
non-deterministic mode could not offer this.

### 2.6 Pure, dependency-light, testable

`structural.py` depends only on panflute and the pure `models.py` dataclasses —
no network, no model, no service. The whole stage is exercised by fast unit
tests asserting exact tree shape and serialized text, which is only possible
*because* of the deterministic mode (M2).

---

## Summary

The pipeline runs in a **deterministic, rule-based mode** for everything that is
a *contract* (structure, taxonomy, chunk boundaries, hygiene), reserving
statistical/learned behaviour for the one stage that is inherently semantic
(embedding). That choice buys reproducibility, model-free testing, auditability,
zero inference cost, and — crucially — **no hallucination surface**: the failure
mode is a detectable miss, never a fabrication.

`structural.py` is the mode made concrete: a faithful, typed AST walk with
structure-preserving serializers, an explicit hierarchy stack, reproducible IDs,
and a synthesized-root safeguard so no page is ever silently lost. Every choice
there exists to keep the boundary between "raw document" and "vector"
**faithful, reproducible, and inspectable**.
