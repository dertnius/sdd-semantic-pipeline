# Spike findings — template-derived enrichment

Re-aimed spike (v4): verify the assumptions at the **pipeline layer** the
extraction actually consumes (`build_structural_model` output), not raw pandoc.
Run against [docs/template/template.md](../../docs/template/template.md).

## Finding 1 — tables are flattened to pipe-strings; two orientations exist

Every table in the template, run through `build_structural_model`, arrives as a
`ContentBlock(content_type=TABLE)` whose `text` is a GFM pipe-table **string** and
whose `raw` is **None**. The structured column→cell relationship is *not*
preserved — it is recoverable only by re-parsing the pipe string.
(`structural._serialize_table`, [structural.py:261-269](../../src/sdd_pipeline/structural.py#L261).)

Two distinct table orientations occur, and they need different handling:

- **Wide** (real header row, one entity per body row) — fields are the header
  cells:
  - `2.1 Definitions` → `Abbreviation or Acronym | Definition`
  - `2.2.1 Stakeholders` → `Stakeholder Side | Stakeholder Role | Stakeholder Name | Contacts…`
  - `3.1 Stakeholders` → `Stakeholder Side | … | Key concern | Requirement Area`
  - `4 Quality Attributes` → `Priority | Quality attribute | Measurable metric`
- **Key-value / transposed** (empty header `|  |  |`, field labels in **body
  column 0**, values in column 1) — fields are the col-0 cells:
  - `5.1.1 / 5.1.2 / 6.4.1 / 6.4.2 Solution Component` →
    `Description`, `Technology Stack`, `Related components`,
    `Covered functional requirements`, `Notes`

**Orientation rule (verified):** if **all header cells are empty/blank** → key-value
(fields = normalised col-0 of body); otherwise → wide (fields = normalised header).
Body cells in the component tables are `[Describe …]` placeholders and must be
stripped from the taxonomy.

## Finding 2 — headings are real

The `####`/`#####`/`######` ATX headings parse into proper `Section` nodes with
their numbered titles (e.g. `5.1.1 Solution Component 1`). No bold-paragraph
pseudo-headings. Section hierarchy/breadcrumb is intact.

## Finding 3 — pipeline alignment / corpus conformance

The template parses through the standard pipeline without issue. **But** the only
SAD currently in the eval corpus,
[src/tools/eval/corpus/sad-retailnexus-oms.md](../../src/tools/eval/corpus/sad-retailnexus-oms.md), does
**not** follow `template.md` — it uses a different section taxonomy
(*Microservices Inventory*, *Kafka Topic Registry*, …) with no Solution Component
key-value tables. No template-conforming *real* document is available in-repo yet
to confirm field-name alignment.

## DECISION: PATH A (conditional)

The structural core is **real**: orientation-aware re-parsing recovers the
template's section→field taxonomy deterministically. Proceed with the
template-derived plan (M1 onward).

**Conditional on a corpus prerequisite:** PATH A only produces *measurable*
retrieval value on **template-conforming documents**. The eval corpus must gain
real docs that follow `template.md` before the M3 retrieval gate can pass. If no
template-conforming documents become available, fall back to PATH B (heading-only
taxonomy + prose mining; the template still supplies section names).

This is the top risk flagged in the plan, now confirmed with evidence rather than
assumed.
