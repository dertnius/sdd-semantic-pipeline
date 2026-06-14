# Exercise 01 — Trace a document through the pipeline

**Goal.** Run the model-free dump tool on two real corpus documents and read the
artifacts it produces (`ast.json`, `enriched.json`, `chunks.json`) until you can
answer five concrete questions about what the pipeline did. No code changes —
this exercise calibrates your mental model before you start modifying anything.
See [walkthrough 01](../walkthroughs/01-life-of-a-document.md) for the stage map.

**Difficulty:** trivial

**You will learn**
- What each dump artifact contains and which pipeline stage produced it
  ([tour 03](../tours/03-enrichment.md) covers the enrichment fields).
- How `depends_on` gets populated — and why most documents have none.
- How to read a Python `SyntaxWarning` ([bridge 05](../bridge/05-modules-imports-and-lazy-patterns.md)).

## Before you start

All exercises happen on one git branch (create it once, reuse it afterwards):

```powershell
git checkout -b learn-exercises    # or: git checkout learn-exercises
```

## Files

None to edit. You only read `build/dump/impala/*.json`, `build/dump/retailnexus/*.json`,
and `src/sdd_pipeline/dump.py`.

## Steps

1. Generate the artifacts (skip if `build/dump/impala/` and `build/dump/retailnexus/` already
   exist — they are pre-generated and deterministic):

   ```powershell
   $env:PYTHONUTF8 = "1"   # Windows cp1252 console crashes on the arrow glyphs otherwise
   .\.venv\Scripts\python.exe src\sdd_pipeline\dump.py src\tools\eval\corpus\impala-vscode.md build\dump\impala
   .\.venv\Scripts\python.exe src\sdd_pipeline\dump.py src\tools\eval\corpus\sad-retailnexus-oms.md build\dump\retailnexus
   ```

2. Answer these five questions **from the artifacts** (write your answers down
   before opening the answer key):

   1. How many chunks did each document produce? (dump.py prints it; also
      countable in each `chunks.json`.)
   2. What `section_type` did the retailnexus section
      "External Integration Contracts" get, and which keyword in
      `enrichment.py::_SECTION_RULES` caused it?
   3. Name one entity that appears in **both** documents' artifacts. Careful:
      compare `enriched.json` (section level) as well as `chunks.json`
      (chunk level) — they disagree for one of the docs. Why?
   4. Which document has chunks with a non-empty `depends_on`, and what is the
      **two-part** reason the other one has zero?
   5. Run `dump.py` with **no arguments** and look at the first line it prints.
      What is the `SyntaxWarning` about, and why does line 9 of
      `src/sdd_pipeline/dump.py` trigger it?

3. For question 4, read `enrichment.py::_write_to_field` — note that only
   records whose *field name* resolves to a direction land in `depends_on`,
   and prose records (no field) always land in `metadata.raw_entities`.

<details>
<summary>Hint</summary>

- Q3: chunk-level entities are recomputed from each chunk's own content
  (`chunking.chunk_document(entity_fn=…)`), so an entity that appears only in a
  *heading* shows up on the Section but on no chunk.
- Q4: structural records come from pipe tables (the inventory). Search
  `src/tools/eval/corpus/impala-vscode.md` for a `|` table row.
- Q5: Python docstrings are ordinary strings — `\.` is not a valid escape.
</details>

## Verification

```powershell
Select-String -Path "build\dump\retailnexus\chunks.json","build\dump\impala\chunks.json" -Pattern '"depends_on": \[$'
```

Success: **exactly one** match, in `build\dump\retailnexus\chunks.json` (around line
904) — the only chunk in either file whose `depends_on` array is non-empty.
(Empty arrays serialize as `"depends_on": []` on one line, so the
open-bracket-at-end-of-line pattern finds only populated ones.)

## Cleanup

Nothing was modified (`build/dump` is gitignored). `git status` should be clean apart
from `build/dump`; nothing to commit or revert.

<details>
<summary>Answer key (computed from the real artifacts)</summary>

1. **impala-vscode.md → 13 chunks; sad-retailnexus-oms.md → 47 chunks.**
2. **`api`.** The breadcrumb is `Integration Architecture > External Integration
   Contracts`; the title contains "contract**s**", which matches the API rule
   keyword `"contract"` in `_SECTION_RULES` (leading-word-boundary match allows
   the plural).
3. **Docker.** In `build/dump/impala/enriched.json` the section "Using Dev Container
   (Developing Inside Docker Container)" has `entities: ["Docker"]`; retailnexus
   has `"docker"` (lower case — `_TECH_PATTERN` is case-insensitive and keeps the
   matched casing from `docker build` in the CI YAML). At **chunk** level, every
   impala chunk has `entities: []`, because "Docker" appears only in the heading
   and chunk entities are recomputed from chunk *content* only.
4. **sad-retailnexus-oms.md** — exactly 1 chunk, breadcrumb
   `Integration Architecture > External Integration Contracts`, with values like
   `OMS → Carrier`, `OMS → ERP`, `OMS → Provider`, `Bidirectional`. Two-part why
   for impala: (a) `impala-vscode.md` contains **no pipe tables**, so the
   structural entity inventory is empty; (b) its prose-extracted records carry no
   field name, and `_write_to_field` routes unnamed records to
   `metadata.raw_entities` — never to `depends_on`/`exposes`.
5. The first line is
   `src\sdd_pipeline\dump.py:9: SyntaxWarning: invalid escape sequence '\.'`.
   Line 9 of the module **docstring** shows the usage
   `.\.venv\Scripts\python.exe dump.py path\to\your-file.md` — a docstring is a
   normal (non-raw) string literal, and `\.` is not a recognized escape sequence,
   so Python 3.12+ warns at compile time. A raw string (`r"""…"""`) would fix it.
</details>
