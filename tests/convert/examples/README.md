# Confluence → GitLab-Markdown conversion examples

Hand-authored mock Confluence pages that exercise the HTML→Markdown converter
(the `sdd_pipeline/convert/` subpackage — `base` + `html_to_gitlab_md` +
`confluence_pf_filter`) end-to-end, so a human can
confirm the output is **clean and loses no information**. The spec
[`docs/confluence-conversion-rules.md`](../../../docs/confluence-conversion-rules.md)
is the rule authority; **this README documents the converter's _actual_ output**
(which occasionally differs from the spec's ideal — those cases are called out).

## Files

| File | What it covers |
|---|---|
| `order-management-sad.html` | **Clean** rendered-export mock — every supported construct on its happy path. The regression baseline. |
| `adversarial-edge-cases.html` | **Sanitized repros of real-export failure modes** (layout-via-table, colour-coded cells, tiered/merged headers, custom DSL, unsupported macro, draw.io/SVG). Drives the loss/noise checks. |
| `order-management-sad.storage.html` | Confluence **storage-format** (`ac:`/`ri:`/`at:`) — the best-effort legacy handlers; element-based constructs only. |

## Reproduce

```powershell
# from the inner project root, with pandoc on PATH
sdd-pipeline convert tests/convert/examples --output tests/convert/examples/out `
  --space ARCH --source-url "https://confluence.example.com/display/ARCH/OMS-SAD" `
  --report tests/convert/examples/out/conversion-report.json --verbose
sdd-pipeline lint tests/convert/examples/out        # expect no html_leakage / confluence_artifacts
```

The committed regression test is `tests/convert/test_html_to_gitlab_md_v3.py::TestConvertExamplesCorpus`
(slow / needs pandoc); AST-level table tests are in `tests/convert/test_confluence_pf_filter.py`.

## The bar: "no information loss" in three tiers

| Tier | Meaning | Bar |
|---|---|---|
| **1 — silent drop** | source text that ends up **nowhere** in the output | **zero** |
| **2 — degradation** | text kept but structure/label lost (GFM can't represent it) | allowed only if **flagged** in the report, or documented below |
| **3 — added noise** | junk not in the source (raw `<div>`/`<table>`, `ac:`/`ri:`, `\` lines, `[[_TOC_]]`) | **zero** |

GFM cannot represent nested tables, cell colour, layout columns, or tiered table
headers — so Tier-2 losses are inherent, not bugs. The only allowed raw HTML in
output is `<br />` inside a table cell.

## Scenario map (actual output, verified)

### `order-management-sad.html` — clean rendered export
| Construct | Output |
|---|---|
| Bold / italic / inline code | `**b**` / `*i*` / `` `c` `` |
| Strikethrough (`span[style*=line-through]`) | `~~old~~` |
| Super / sub / `<small>` / `<time>` | `n^2` / `CO2` / plain text / `2024-03-01` |
| Color span / `&nbsp;` / `&mdash;` | plain text / space / `—` |
| External link / same-page anchor | `[text](url)` / plain text |
| User mention / emoticon / inline-comment | display name / `yes` / plain text |
| Status lozenges / Jira | `**Approved**` / `[OMS-1234](url) summary (Done) (resolved)` |
| Info / Note / Warning / Tip | `> **Info — Title:**` … |
| Panel | `> **Panel — Title:**` *(note: macro prefix — differs from the spec's `> **Title:**`)* |
| Legacy `panelMacro` | `> **Warning:**` |
| Expand | `**Title**` + body prose (no `<details>`) |
| Layout (columns) | sequential paragraphs, no `<hr>` |
| Embedded image / gallery / view-file | `![alias](attachments/…)` / `*Image gallery (N images): …*` / `[file](…) (PDF Document)` |
| Data-URI image / SVG figure | alt text only / `*caption*` |
| Code macro (yaml/python/sql/bash/json) | titled bold + fenced block with trusted `lang` |
| Lists / nested / task list | `-` / `1.` / `- [x]` / `- [ ]` |
| Tables: header / row-header / merged / list-in-cell / pipe-in-code / `<br/>` | pipe table / bolded col-1 / spans reset / `a; b` / `` `a \| b` `` / `<br />` |
| ADR card | `#### ADR-007 — …` + `**Status:**` + bolded sections |
| TOC macro / attachments+comments / `<p><br/></p>` | deleted / dropped / dropped |

### `adversarial-edge-cases.html` — what survives, what degrades
| Case | Outcome |
|---|---|
| Layout-via-table + spacer columns (§1) | flattened to one wide pipe table — content kept, **grouping lost** (Tier-2, flagged `merged_table`) |
| Colour-coded "output" cell (§2) | pipe table; **colour meaning lost** (Tier-2, *currently silent* — `title` attr scrubbed) |
| Tiered / `rowspan` merged header (§3) | **now a valid pipe table** (header rows folded into the body, flagged `multi_header_collapsed`). *This used to leak a raw `<table>` and was dropped downstream — fixed.* |
| Custom DSL with `brush: java` (§4) | stays ` ```java ` (Tier-2, faithful to the author's brush) |
| `brush: java` block that is really SQL (§4) | re-labelled ` ```sql ` (java-distrust heuristic works) |
| Unsupported macro (§5) | body survives as prose, shell dropped — **not** a Tier-1 loss |
| draw.io/SVG with caption / without caption (§6) | `*caption*` / **dropped** (Tier-2, flagged `diagram` — diagram content is unrecoverable) |

## Known limitations (Tier-2 — inherent, document not fix)

- **Diagrams lose their content.** A draw.io/SVG/data-URI diagram keeps only its
  caption/alt text; boxes, arrows, and labels are gone (flagged via `diagram` /
  `data_uri_image`). Architecture diagrams in real SADs lose their node labels.
- **Layout-via-table is flattened.** Tables used purely for side-by-side layout
  become one wide pipe table; the visual grouping is not recoverable.
- **Cell colour/`title` meaning is dropped — silently.** GFM has no cell styling,
  and the scrub/pandoc drop the attribute. (Considered but not promoted to a fix.)
- **Tiered table headers are flattened to one row.** Multi-row / merged (`rowspan`)
  headers are folded into the body to keep a valid pipe table (flagged
  `multi_header_collapsed`); the header *tiering* is not preserved.
- **`<time>` display text → ISO date.** "March 1, 2024" becomes `2024-03-01`
  (the date is preserved; the prose form is not).

### Storage format (`order-management-sad.storage.html`)
- **lxml drops CDATA.** `ac:plain-text-body` code and `ac:plain-text-link-body`
  text do **not** round-trip — excluded from the mock by design. Use the
  rendered-export path for any page whose code matters.
- **`ac:structured-macro` admonitions/expand/status are not framed.** Only their
  inner prose survives; the macro title parameter and the `> **Type:**` /
  bold-title framing are dropped (the deferred SF-\* reality). Element-based
  constructs that **do** work: `ac:link`→`ri:page`/`ri:attachment`/anchor,
  `ac:image`→`ri:attachment`/`ri:url`, `at:var`→`{name}`, `ac:placeholder`,
  `ac:task`, `ac:emoticon`.
