# Tour 03 — enrichment.py: deterministic classification & entities

**Role in the pipeline.** Stage 5 ([enrichment.py](../../src/sdd_pipeline/enrichment.py))
takes the bare `Section` tree from [tour 02](02-ast-parser-and-structural.md)
and fills in the semantic fields: each section gets a `SectionType`, a list of
`entities`, and `tags`. There is **no ML here** — everything is ordered keyword
rules and a handful of precision regexes, which is exactly why this stage can
stay in the fast, deterministic test tier (see [CLAUDE.md](../../CLAUDE.md)
guardrails).

## Reading order

1. **`enrichment.py::_SECTION_RULES`** (module constant, ~line 25). A
   `dict[SectionType, list[str]]` of keyword lists. The dict is **ordered and
   order matters** — first matching type wins (Python dicts preserve insertion
   order, unlike C# `Dictionary`; think of it as an ordered list of
   `(type, keywords)` rules). Read the inline comments: each early entry
   exists to *beat* a later one ("Design Decision" must hit DECISION before
   "design" hits ARCHITECTURE; "JWT Configuration" must hit SECURITY before
   "config" hits DEPLOYMENT). *Guiding question:* what would break if you
   alphabetized this dict?
2. **The comment block above `enrichment.py::_SECTION_PATTERNS`** (~line 165).
   Read it word by word — it explains the matching compromise: each keyword is
   compiled with a *leading-only* word boundary (`\b` before, none after). So
   "structure" no longer matches inside "infrastructure" and "api" not inside
   "rapid" (no word start there), while "consideration" still matches
   "considerations". The rules themselves also stay multi-word where needed:
   bare "contra" would match "contract", "cons" would match "considerations".
3. **`enrichment.py::classify_section_type`** — four lines of logic: first
   pattern that `search`es the title wins, else `SectionType.CONTENT`.
4. **The three precision patterns** (entity extraction):
   - `enrichment.py::_SERVICE_PATTERN` — PascalCase + a known suffix
     (`...Service|Controller|Manager|...`). *Why is the middle group
     `(?:[A-Z][a-z]+)*` zero-or-more?* (The comment above it answers.)
   - `enrichment.py::_TECH_PATTERN` — a fixed vocabulary of infrastructure
     names (PostgreSQL, Kafka, Kubernetes...), case-insensitive, re-canonicalized
     on match.
   - `enrichment.py::_PROTOCOL_PATTERN` — protocol acronyms (REST, gRPC, JWT...),
     case-sensitive.
5. **`enrichment.py::extract_entities`** — runs all three plus optional
   `extra_terms` (a project vocabulary injected via `PIPELINE_ENTITY_TERMS` or
   the corpus scan, [tour 04](04-vocabulary-and-two-pass-scan.md)). Note the
   `canonical` dict: hits are mapped back to the *supplied* spelling.
6. **`enrichment.py::enrich_section` / `enrich_document`** — classic recursive
   tree mutation (`enrich_section` calls itself on `subsections`). Note that
   entities are extracted from `title + all block texts` of *this section
   only* — subsection text is not folded upward.
7. **Skim the discovery block** at the bottom: `_ALLCAPS_PATTERN`,
   `_BACKTICK_PATTERN`, `_ALLCAPS_STOPLIST` (module constants, ~line 214 on)
   and `enrichment.py::scan_corpus`. **Important asymmetry:** these
   recall-oriented patterns are used *only* by the corpus scan, never by
   `extract_entities` — the comment above them says so explicitly. Precision
   for per-section tagging, recall for vocabulary discovery.

## The optional `inventory` parameter (stage 3.5)

`enrich_section` and `enrich_document` accept a keyword-only
`inventory: EntityInventory | None`. When supplied (built by
`pipeline.py::SemanticPipeline._build_inventory` from table and prose
extractors), each section's `EntityRecord`s are routed by
`enrichment.py::_apply_inventory` → `_write_to_field`: directional field names
go to `depends_on`/`exposes` (resolved by name via
`config/field_directions.yaml`, never guessed), named non-directional fields go
to `Section.metadata`, below-threshold records to the audit-only
`raw_entities` bucket. The path is strictly **additive** — legacy enrichment
always runs first, so callers without an inventory behave exactly as before.
The extractors themselves are covered in
[tour 06](06-inventory-extraction-modules.md).

## Executable documentation

- [tests/test_enrichment.py](../../tests/test_enrichment.py) — read
  `test_no_substring_collisions` (parametrized: "Infrastructure" must be
  DEPLOYMENT, not ARCHITECTURE via "structure"; "Rapid Prototyping" must not
  match "api") and `test_extra_terms_use_canonical_spelling`.
- [tests/test_enrichment_inventory.py](../../tests/test_enrichment_inventory.py)
  — read `test_directional_fields_route_to_depends_on_and_exposes` and
  `test_below_threshold_goes_to_raw_entities`.

## Self-check

1. A section is titled "Miscellaneous Notes". What `section_type` does it get,
   and what does that mean for its embed text?
   <details><summary>Answer</summary>
   No pattern matches, so <code>classify_section_type</code> returns
   <code>SectionType.CONTENT</code> — the explicit fallback on its last line.
   Downstream, <code>SemanticChunk.to_embed_text</code> treats CONTENT as the
   null type and omits the <code>[content]</code> prefix entirely
   (<a href="01-models-and-config.md">tour 01</a>).
   </details>
2. The word `CQRS` appears in one section of one document. Under what
   conditions does it end up in that section's `entities` list?
   <details><summary>Answer</summary>
   Only via <code>extra_terms</code>. <code>extract_entities</code> runs just
   the three precision patterns, and CQRS is neither a known suffix, tech
   name, nor listed protocol. It <em>is</em> caught by
   <code>_ALLCAPS_PATTERN</code> — but that runs only in
   <code>scan_corpus</code>. So you need the two-pass scan (or
   <code>PIPELINE_ENTITY_TERMS</code>) to feed it back in as a term
   (<a href="04-vocabulary-and-two-pass-scan.md">tour 04</a>).
   </details>
3. Why does `_compile_terms` sort literals longest-first before joining them
   into one alternation?
   <details><summary>Answer</summary>
   Python's regex alternation is first-match, not longest-match: with
   <code>"Pod"|"Pod Operator"</code> the engine would stop at "Pod" and never
   try the longer term. Sorting longest-first makes multi-word terms win over
   their own prefixes — the comment in <code>_compile_terms</code> says
   exactly this.
   </details>
