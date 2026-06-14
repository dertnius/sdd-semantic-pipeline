# Exercise 08 — Use the pipeline as a library

**Goal.** Everything so far went through existing entry points. Now write your
own standalone script, `scratch/section_tree.py`, that imports `SemanticPipeline`
like any consumer would (think: referencing a NuGet package, not editing it),
parses one corpus document, and prints an indented tree of
`title [section_type] (n blocks)`. No CLI plumbing, no embedding model —
`parse_file` runs only pandoc → structural, and enrichment is pure Python.

**Difficulty:** medium

**You will learn**
- Importing from an installed package (`pip install -e .` made `sdd_pipeline`
  importable everywhere — [bridge 05](../bridge/05-modules-imports-and-lazy-patterns.md)).
- Recursion over a dataclass tree (`Section.subsections`) with f-strings and
  `pathlib` — see [tour 01](../tours/01-models-and-config.md) for the
  `Section` shape and [bridge 02](../bridge/02-dataclasses-vs-csharp-records.md).

## Before you start

```powershell
git checkout learn-exercises
mkdir scratch -Force
```

(`scratch/` is **not** in `.gitignore` — it lives on your branch, which is fine.)

## Files

- `scratch/section_tree.py` — new, yours

## Steps

1. Sketch the program before typing: construct a `SemanticPipeline()` (the
   embedder is lazy — nothing model-related runs unless you touch `.embedder`),
   call `pipeline.parse_file(Path("src/tools/eval/corpus/impala-vscode.md"))`, then walk
   `doc.root_sections`.
2. `parse_file` deliberately stops *before* enrichment (its docstring says why),
   so every `section_type` would print as `content`. Add the one extra call
   yourself: `enrichment.enrich_document(doc, entity_terms=pipeline.config.entity_terms)`
   — pure, in-place, returns the same object.
3. Write a recursive `walk(section, depth=0)`: print
   `f"{'  ' * depth}{section.title} [{section.section_type.value}] ({len(section.blocks)} blocks)"`,
   then recurse into `section.subsections` with `depth + 1`. The fields you
   need are all on `models.py::Section` (`title`, `section_type`, `blocks`,
   `subsections`). One real-data wrinkle: the first root section has an empty
   `title` (frontmatter preamble before the first heading) — decide how to
   render it.
4. Run it with the project venv from the inner project root:

   ```powershell
   $env:PYTHONUTF8 = "1"
   .\.venv\Scripts\python.exe scratch\section_tree.py
   ```

5. Stretch: take the markdown path as `sys.argv[1]` with your hardcoded path as
   the default, and try it on `src/tools/eval/corpus/sad-retailnexus-oms.md`.

<details>
<summary>Hint — expected output (verified against the current tree)</summary>

The full output for `impala-vscode.md` is 8 lines; the first 6:

```
(untitled) [content] (0 blocks)
Introduction [overview] (2 blocks)
Setup [content] (3 blocks)
Front-end Development using VSCode [content] (0 blocks)
  Setup [content] (1 blocks)
  Run/Debug Unit Tests [content] (1 blocks)
```

(then `Remote Debug Frontend [content] (3 blocks)` indented, and
`Using Dev Container (Developing Inside Docker Container) [deployment] (2 blocks)`
at root level — here `(untitled)` is this author's choice for the empty title.)
If your `enum` prints as `SectionType.OVERVIEW` instead of `overview`, you
printed the member, not its `.value` — `SectionType` is a `StrEnum`, so plain
f-string interpolation of `.value` (or the member itself) gives `overview`.
</details>

## Verification

Your output must match the section structure in `outbox/dump/impala/enriched.json`
(from exercise 01): same titles in the same nesting, `Introduction` typed
`overview`, the Dev Container section typed `deployment`, everything else
`content`. Spot-check the JSON side:

```powershell
Select-String -Path "outbox\dump\impala\enriched.json" -Pattern '"section_type": "(overview|deployment)"'
```

Success: one `overview` and one `deployment` hit — the same two non-`content`
sections your tree shows.

## Cleanup

```powershell
git add scratch\section_tree.py && git commit -m "learn: section-tree library consumer (exercise 08)"
# or just delete it: Remove-Item scratch\section_tree.py
```
