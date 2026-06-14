# Tour 11 — `quality.py` & the `lint` command

**Read with open:** [`src/sdd_pipeline/quality.py`](../../../src/sdd_pipeline/quality.py),
the `lint` command in [`src/sdd_pipeline/cli.py`](../../../src/sdd_pipeline/cli.py),
and [`tests/test_quality.py`](../../../tests/test_quality.py).

## What it is

A **read-only linter** over *raw source `.md`* — the C# analogy is a **Roslyn
analyzer**: it inspects source text and *reports* diagnostics, it never rewrites
or blocks anything. It exists because the corpus is produced by an imperfect
HTML→Markdown converter (flow B), and conversion residue (leaked `<table>`/`<span>`
tags, untranslated `{panel}`/`<ac:>` macros, TOC link-dumps, near-empty stubs,
empty section headings) degrades embedding quality once it reaches the vector.
`convert` records what it *handled*; `lint` audits what *survived* into the file.

It is the only check that runs **before** pandoc — every other stage works on the
parsed AST, by which point the evidence of these source defects is gone.

## Reading order

1. **The data contracts** (top of the file): `QualityIssue` (rule / severity /
   detail) and `MarkdownQualityReport` (a list of issues + two `@property`
   computed views, `is_embeddable` and `issue_summary`). Same `@dataclass` +
   `@property` idiom you met in `models.py` — properties are C# computed
   properties; the regexes/thresholds are module-level constants ≈ `static
   readonly`, compiled once at import.

2. **`check_markdown(source_id, markdown)`** — the public entry. Note the shape:
   it is a plain **module function**, not a `Checker` class. Python prefers free
   functions when there's no state to hold; a class here would just wrap
   stateless methods. It returns the report; it does no I/O (the CLI reads files).

3. **`_strip_code_preserving_lines`** — the key design move. Prose checks run on a
   *de-fenced* copy where fenced (```` ``` ````/`~~~`), indented, and inline code
   are blanked to **empty lines** (not deleted). Two reasons: (a) an HTML/macro
   *example shown in a code block* must not be mistaken for leaked residue, and
   (b) blanking-not-deleting keeps line numbers aligned, so a regex match's line
   maps back to the source. Read this next to the fence-regression test.

4. **The six `_check_*` helpers** — each returns *one* `QualityIssue` or `None`.
   `code_ratio` is the one that runs on the **raw** text (it needs the code it
   measures); the rest run on de-fenced text. Watch the two-tier severity:
   `block` (leaked HTML > 3, any Confluence macro, near-empty stub) vs `warn`
   (code dump, link-heavy, empty section heading). `is_embeddable` = "no block".

5. **`_check_orphaned_headings`** — the subtle one. It detects *headings* on the
   de-fenced text (so a `#` comment inside a code block isn't a false heading) but
   judges *body presence* on the **raw** text (so a section whose only content is
   a code block is **not** "empty"). It only flags a heading with no body before
   the next heading of *equal-or-higher* level — opening a section with a
   subsection (`## A` → `### B`) is allowed. This split is a real bug fix; the
   `test_section_with_only_a_code_block_is_not_orphaned` test pins it.

6. **The `lint` command** (`cli.py`) — mirrors `export`: glob → per-file
   `read_text(encoding="utf-8-sig")` (BOM-tolerant) inside a `try/except` so one
   unreadable file doesn't abort the run → `check_markdown` → an **issues-only**
   JSON report (clean files are counted, not listed) + a Rich summary + an
   ASCII-only final line (cp1252-redirect safety). Exit code: `0` normally, `1`
   on any read failure, `1` under `--strict` when any `block` issue exists.

## Why these choices (the interview/grilling trail)

- **Whole-file verdicts on raw markdown**, not per-chunk — `lint`/`check_markdown`
  answers "which *documents* need cleaning," a per-file question, **before** pandoc.
  Its sibling in the same module, `check_chunk`, is the complementary *per-chunk*,
  *post-pipeline* gate: it runs on the produced `SemanticChunk.to_embed_text()` inside
  `index` and **blocks** a file when a chunk is poisoned (markup/macro residue, or
  empty). So `quality.py` now hosts both the advisory raw-source linter and the
  binding chunk gate — see [tour 10](10-pipeline-orchestrator-and-cli.md) for the wiring.
- **No new dependency** — every check is plain `re`; an early plan to add
  `markdown-it-py` was dropped once fence-stripping made a real parser redundant.
- **Thresholds are guesses to calibrate** — run `lint` on your corpus, eyeball
  the report, tune the constants so `block` is genuinely "must fix."
- **Corpus scoping is the caller's job** — point it at the real embedding corpus,
  *not* a docs tree containing meta-documentation *about* Confluence syntax (those
  files legitimately contain the flagged tokens and would self-report).

## Try it

```powershell
sdd-pipeline lint src/tools/eval/corpus -v      # report -> src/tools/eval/corpus/quality-report.json
```
On the sample corpus this flags two files with leaked `<table>` residue (block)
and leaves the clean docs untouched — a concrete before/after for the converter.

## Tests as the spec

`tests/test_quality.py` is the readable spec: one test per check, plus the three
regressions that guard the design — code examples don't false-positive
(fence-awareness), leading frontmatter is clean, and a code-only section isn't
orphaned. The `lint` CLI smoke tests live in `tests/test_cli.py::TestLint`.
