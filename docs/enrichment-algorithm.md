---
title: "Enrichment Algorithm — Design Rationale & Defense"
status: "Defense"
date: "2026-06-15"
companion_to:
  - "docs/processing-mode-and-structural.md"
  - "docs/technology-selection.md"
  - "docs/adr/adr-0001-modular-semantic-pipeline.md"
---

# Enrichment Algorithm — Design Rationale & Defense

This document defends the **structural base of the enrichment stage**
([`enrichment.py`](../src/sdd_pipeline/enrichment.py)) — the data structures and
algorithms that turn a parsed `DocumentModel` into a *labelled* one. It explains
*what* the algorithm produces, *how* it works (with diagrams, pseudocode, and
worked string examples), *why* it is built this way, and *which conclusions* drove
the design.

It continues the defense series: [technology-selection.md](technology-selection.md)
(which libraries), [processing-mode-and-structural.md](processing-mode-and-structural.md)
(deterministic mode + structural stage). Enrichment is where that deterministic
mode does its most interesting work.

---

## 1. What enrichment produces (the contract)

For **every section** in the document tree, enrichment fills four labels:

| Output | Question it answers | Example |
|---|---|---|
| `section_type` | *What engineering role?* | `decision`, `security`, `api`, `data_model` |
| `genre` | *What prose shape?* | `glossary`, `faq`, `howto`, `policy`, `narrative` |
| `entities` | *Which named things are mentioned?* | `AuthService`, `Redis`, `gRPC`, `XCom` |
| `tags` | *Extra machine signals* | `lang:python`, the section-type tag |

These labels are later folded into the chunk's embed-text header and become
**filterable metadata** for retrieval (`search --section-type decision`). So the
quality of enrichment directly determines how precisely a user can narrow a search.

```
DocumentModel (sections + blocks)          DocumentModel (now labelled)
        │                                          ▲
        │   ┌──────────────────────────────────┐   │
        └──▶│  ENRICHMENT  (pure, deterministic)│───┘
            │  per section:                     │
            │   1. classify_section_type(title) │
            │   2. classify_genre(section)      │
            │   3. extract_entities(text)       │
            │   4. extract_tags(...)            │
            └──────────────────────────────────┘
```

---

## 2. The structure base: ordered keyword tables compiled to regex

The heart of the stage is a **single declarative data structure** — an *ordered*
map from each `SectionType` to the keywords that signal it:

```python
_SECTION_RULES: dict[SectionType, list[str]] = {
    SectionType.DECISION:    ["decision", "adr", "rationale", "propose", "chosen", "why", ...],
    SectionType.ALTERNATIVE: ["alternative", "options considered", "rejected", ...],
    SectionType.TRADEOFF:    ["pro argument", "pros and cons", "trade-off", ...],
    SectionType.CONSEQUENCE: ["consequence", "downside", "impact", "risk", ...],
    SectionType.SECURITY:    ["security", "auth", "jwt", "oauth", "encryption", ...],
    SectionType.DATA_MODEL:  ["data model", "entity schema", "database", "table", ...],
    SectionType.OVERVIEW:    ["overview", "purpose", "scope", "context", ...],
    SectionType.ARCHITECTURE:["architecture", "components", "structure", "topology", ...],
    SectionType.API:         ["api", "endpoint", "contract", "schema", "rest", ...],
    SectionType.DEPLOYMENT:  ["deployment", "infrastructure", "config", "docker", ...],
}
```

This table is **compiled once** into an ordered list of `(SectionType, regex)`
pairs (`_SECTION_PATTERNS`). Three deliberate properties:

1. **It is data, not control flow.** Adding a keyword or a whole new type is a
   one-line table edit — no `if/elif` ladder to refactor, no risk of reordering
   branches by accident. A reviewer reads the taxonomy top-to-bottom.
2. **Order encodes priority** (first match wins, §3). Specific/collision-prone
   types are listed *before* general ones, with the reason documented inline:
   `DECISION` before `ARCHITECTURE` so *"Design Decision"* is a decision, not an
   architecture section; `SECURITY` before `DEPLOYMENT` so *"JWT Configuration"*
   is security, not config.
3. **Keywords match at a word start** — each keyword is compiled with a *leading*
   word boundary (`\b` before, none after). This is the key correctness choice
   (§2.1).

### 2.1 Why a *leading* word boundary, and not plain substring or full `\b…\b`

| Strategy | Problem |
|---|---|
| plain substring (`kw in title`) | **false positives**: `"structure"` matches `"infra**structure**"`; `"contra"` matches `"**contra**ct"`; `"api"` matches `"r**api**d"`. |
| full word boundary (`\bkw\b`) | **false negatives**: drops the inflections the rules rely on — `"config"` would no longer match `"**config**uration"`, `"consideration"` would miss `"**consideration**s"`. |
| **leading boundary (`\bkw`)** ✅ | matches at a word *start* but tolerates suffixes: `\bconfig` ✓ `configuration`, `\bconsideration` ✓ `considerations`, while `\bstructure` ✗ `infrastructure`. |

This single decision removes an entire class of misclassification bugs while
preserving recall over plural/inflected headings — and it is provable by reading
the regex, not by trusting a model.

---

## 3. The classification algorithm (first-match-wins)

The algorithm is intentionally tiny — *that is a feature*:

```
function classify_section_type(title):
    for (section_type, pattern) in _SECTION_PATTERNS:   # ordered, priority high→low
        if pattern.search(title):
            return section_type                         # first match wins
    return CONTENT                                      # explicit, safe default
```

```
 title ──▶ DECISION? ─yes─▶ DECISION
            │no
            ▼
          ALTERNATIVE? ─yes─▶ ALTERNATIVE
            │no
            ▼
           …(each type in priority order)…
            │no
            ▼
          DEPLOYMENT? ─yes─▶ DEPLOYMENT
            │no
            ▼
          CONTENT  (nothing matched — safe, non-fabricating default)
```

### 3.1 Worked examples (plain-English strings)

| Heading string | Walks past | Matches | Result | Why it's right |
|---|---|---|---|---|
| `"Design Decision: Adopt Kafka"` | — | `\bdecision` | **DECISION** | `DECISION` is listed before `ARCHITECTURE`, so the chosen-decision meaning wins over the word *design*. |
| `"Options Considered"` | DECISION | `\bconsideration`…`considered` | **ALTERNATIVE** | inflection (`considered`) still matches via leading boundary. |
| `"JWT Configuration"` | DECISION…CONSEQUENCE | `\bjwt` | **SECURITY** | `SECURITY` precedes `DEPLOYMENT`, so this is security, not config. |
| `"Infrastructure"` | … | `\binfrastructure` (DEPLOYMENT) | **DEPLOYMENT** | `\bstructure` does **not** fire inside `infrastructure` — no word boundary before `structure`. |
| `"Release Notes"` | everything | — | **CONTENT** | nothing matched → safe default, no guess. |

The complexity is `O(types)` per heading with no backtracking — negligible, and
**deterministic**: the same title always yields the same type.

---

## 4. Two orthogonal axes: `SectionType` ⟂ `Genre`

A heading like *"Glossary"* tells you the **prose shape** (a term list) but a
heading like *"Security"* tells you the **engineering role**. These are
independent questions, so the design uses **two orthogonal classifiers** rather
than forcing one taxonomy to carry both meanings.

`classify_genre` is more than a title lookup — a title can lie ("Notes" over a
real FAQ), so the **body decides** and the title only confirms/promotes:

```
function classify_genre(section):
    if no blocks:                      return title_genre or GENERAL
    if prose_ratio < 0.5:              return title_genre or GENERAL   # code/table doc
    # body-shape detectors, first match wins:
    if definition_blocks ≥ 50% prose:  return GLOSSARY
    if ≥2 paragraphs end with "?":     return FAQ
    if ordered list w/ ≥2 imperative-led items:  return HOWTO   # "1. Install…  2. Run…"
    if ≥2 obligation modals (must/shall/required): return POLICY
    if title_genre is set:             return title_genre        # title promotes
    return NARRATIVE                                             # prose, no shape
```

**Defense of "body wins":** prose headings are frequently generic, so trusting
the title would mislabel. Measuring the body (definition density, question marks,
imperative verbs, obligation modals) is a **falsifiable, content-derived** signal.
The `prose_ratio < 0.5` gate first short-circuits code/table-dominant sections
where "prose shape" is meaningless.

*Example:* a section titled *"Setup"* whose body is `1. Install the CLI  2. Run
init  3. Configure the token` → the ordered-list-of-imperatives detector fires →
**HOWTO**, regardless of the title.

---

## 5. Entity extraction: layered patterns + injectable vocabulary

Entities are extracted by **four pattern families**, each capturing a different
naming convention, unioned and sorted:

```
text ─┬─▶ _SERVICE_PATTERN   PascalCase + role suffix   → AuthService, OrderRepository
      ├─▶ _TECH_PATTERN      fixed infra name set       → PostgreSQL, Redis, Kafka
      ├─▶ _PROTOCOL_PATTERN  protocol acronym set       → REST, gRPC, JWT, mTLS
      └─▶ extra_terms        injected project vocab      → XCom, triggerer, KPO
                              (PIPELINE_ENTITY_TERMS / corpus scan)
                                          │
                                          ▼
                              sorted, de-duplicated entities
```

*Example:* `"The AuthService persists orders in PostgreSQL and is called over
gRPC."` → `["AuthService", "PostgreSQL", "gRPC"]`.

**Defense of layering rather than one big regex / an NER model:**

- Each family encodes a *known shape*, so a match is explainable ("matched the
  service-suffix rule") and the false-positive surface is small and reviewable.
- The **injectable vocabulary** (`extra_terms`) is the escape hatch: project
  terms that follow no convention (`triggerer`) are added as **data** —
  `PIPELINE_ENTITY_TERMS` or the corpus scan — never a code change. Injected
  matches are mapped back to their **canonical spelling**, so output is stable
  regardless of how the term is cased in the text.
- A general NER model would be heavier, non-deterministic, and *less* precise for
  identifier-shaped domain terms — and would need labelled training data we don't
  have.

### 5.1 Precision vs. recall — two pattern sets on purpose

There is a second, **broader** pattern set (`_ALLCAPS_PATTERN`,
`_BACKTICK_PATTERN`, filtered by a stoplist) used **only** for vocabulary
*discovery* (§6) — never for per-section tagging. The split is deliberate:

- **Tagging wants precision** → narrow patterns, so a section isn't polluted with
  noise.
- **Discovery wants recall** → cast a wide net to *find candidate* terms
  (`CQRS`, `BFF`, `settlement-engine`), which a human/seed list then ratifies.

Using the wide patterns for tagging would inject noise into every vector; using
the narrow ones for discovery would miss domain acronyms. Separating the two is
the conclusion that lets each job optimise its own metric.

---

## 6. The two-pass cross-corpus scan (why two passes)

**The problem:** `extract_entities` only knows the terms handed to it. If
document A defines `XCom` in backticks but document B mentions it in plain prose,
B's `XCom` is **invisible** during B's enrichment. Per-file extraction cannot
share knowledge across files.

**The solution:** a read-only **discovery pass** over the *whole* corpus first,
then enrich every doc with the union vocabulary:

```
        PASS 1 — DISCOVER (read-only, no mutation)
  ┌─────────────────────────────────────────────────┐
  │ for each doc:  walk sections, run WIDE patterns  │
  │ seed_terms ──▶ scan_corpus ──▶ vocabulary[]      │   (sorted, deduped,
  └─────────────────────────────────────────────────┘    len ≥ min_length)
                          │
                          ▼  vocabulary fed back as entity_terms
        PASS 2 — ENRICH (mutate, precise)
  ┌─────────────────────────────────────────────────┐
  │ for each doc:  enrich_document(doc, vocabulary)  │
  │   → every term seen anywhere is tagged everywhere│
  └─────────────────────────────────────────────────┘
```

```python
vocabulary = scan_corpus(all_docs, seed_terms=prior_vocabulary)  # pass 1
for doc in all_docs:
    enrich_document(doc, entity_terms=vocabulary)                 # pass 2
```

**Defense:**

- It makes entity recognition **corpus-consistent** — the same term is tagged the
  same way in every document, which is what makes entity filters trustworthy at
  search time.
- It is **opt-in and accumulative**: `seed_terms` carries a persisted vocabulary
  forward, so coverage grows over runs; with no vocab path set, the pipeline keeps
  cheap per-file behaviour.
- Pass 1 is strictly **read-only** (`_collect_section_terms` touches no Section
  attribute), so it is safe to run before enrichment and cannot corrupt state —
  again a property only a deterministic design can guarantee.

---

## 7. Conclusions that drove the algorithm

The design is the product of a few concrete conclusions about the problem:

| # | Conclusion (the finding) | Design consequence |
|---|---|---|
| C1 | SDD/ADR **headings are conventional** (template-driven), so a keyword vocabulary is competitive with a classifier. | Ordered keyword **rule table**, not an ML model. |
| C2 | Naive substring matching **collides** (`contra`⊂`contract`). | **Leading word-boundary** regex compilation. |
| C3 | Some types are **special cases of others** (`Design Decision` vs `design`). | **Order = priority**, first-match-wins. |
| C4 | A heading's **role** and its **prose shape** are different questions. | **Two orthogonal axes**: `SectionType` ⟂ `Genre`. |
| C5 | **Titles can mislead**; bodies are honest. | Genre detected from the **body**, title only promotes. |
| C6 | Domain entities follow **several naming shapes** + some follow none. | **Layered patterns** + **injectable vocabulary**. |
| C7 | Precision (tagging) and recall (discovery) are **different goals**. | **Two pattern sets**: narrow for tagging, wide for discovery. |
| C8 | Per-file extraction **can't share** terms across documents. | **Two-pass corpus scan** with accumulating seed vocabulary. |
| C9 | The output must be **auditable, reproducible, and free of fabrication**. | Everything **pure and deterministic**; `CONTENT`/`GENERAL` are safe non-guessing defaults. |

---

## 8. Benefits — why this is the right base

- **Explainable.** Every label traces to a specific rule a reviewer can read and
  amend — no opaque weights. (`section_type=security` *because* `\bjwt` matched.)
- **Extensible as data.** New section types, keywords, or entity terms are table
  edits, not code rewrites — the taxonomy evolves without touching control flow.
- **Reproducible & cheap.** Pure functions, no model, no network: identical input
  → identical labels → identical vectors, indexable offline at near-zero cost.
- **Precise where it matters, recall where it helps.** The precision/recall split
  (§5.1) and the two-pass scan (§6) let tagging stay clean while discovery stays
  broad.
- **No fabrication surface.** Unmatched input falls to an explicit safe default;
  the algorithm can *miss* a label (detectable, fixable) but never *invents* one.
- **Directly improves retrieval.** Because these labels become filterable metadata
  and embed-text signal, a better-enriched section is a more findable one — the
  whole point of the pipeline.
