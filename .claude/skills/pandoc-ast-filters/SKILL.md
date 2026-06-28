---
name: pandoc-ast-filters
description: Use pandoc as a library instead of a one-shot CLI — read Markdown or HTML into pandoc's JSON AST, transform it in-process with a panflute filter (between read and write), then render it back. Use when someone wants to convert Markdown to a pandoc AST, write or apply a pandoc filter, programmatically rewrite document structure (admonitions, tables, code-fence languages, links) during conversion, or asks "how do I filter pandoc's AST". Includes a worked Confluence filter and a round-trip CLI. Needs pandoc (+ panflute for filtering).
---

# pandoc-ast-filters — read → filter → write with pandoc's JSON AST

Most conversions shell out to a single `pandoc in.md -o out.md`. When you need to
**change the document structure** during conversion, split it into three steps and
own the middle one:

```
READ            FILTER (you)             WRITE
in.(md|html) → pandoc --to json → panflute transform → pandoc --from json → out.(md|gfm|…)
```

`scripts/pandoc_ast.py` gives the three reusable helpers and a CLI; the bundled
`scripts/confluence_pf_filter.py` is a real, battle-tested filter you can read and adapt.

## Requirements

- **pandoc** on PATH — <https://pandoc.org/installing.html> (needed for every subcommand).
- **panflute** — `pip install panflute` (needed only for the `filter` subcommand).

## Usage

```bash
# Inspect the AST pandoc produces (great for designing a filter)
python scripts/pandoc_ast.py dump notes.md --from gfm

# Round-trip with no filter (read → AST → write) — proves the plumbing
python scripts/pandoc_ast.py roundtrip notes.md --from gfm --to gfm

# Apply the bundled Confluence filter: HTML → AST → transform → GFM
python scripts/pandoc_ast.py filter page.html --from html --to gfm
```

The `filter` subcommand prints macro/transform counts to **stderr** so stdout stays
clean for piping the converted document.

## The helpers (import them in your own code)

```python
from pandoc_ast import to_ast, from_ast, apply_filter
```

- `to_ast` — args `text`, `from_format` → a pandoc JSON AST string
- `from_ast` — args `ast_json`, `to_format` → rendered text
- `apply_filter` — arg `ast_json` → the filtered AST plus a notes object, running the
  bundled Confluence filter

## Files

| Path | Role |
|---|---|
| [scripts/pandoc_ast.py](scripts/pandoc_ast.py) | `to_ast` / `from_ast` / `apply_filter` + the CLI (UTF-8-safe stdout) |
| [scripts/confluence_pf_filter.py](scripts/confluence_pf_filter.py) | worked example: admonitions, lozenges, layouts, table simplification, code-fence language mapping |
| [references/writing-filters.md](references/writing-filters.md) | how to write your own panflute filter, and the pandoc `data-` attribute gotcha |

Read `references/writing-filters.md` before writing a new filter.

## Notes

- **Why panflute (in-process) over a stdin/stdout JSON filter?** Both work; panflute
  keeps everything in one Python process (no extra subprocess) and gives typed AST
  element classes (`pf.Div`, `pf.Table`, `pf.CodeBlock`, …). The same logic also runs
  as a classic `pandoc --filter` script via `panflute.toJSONFilter` — see the reference.
- **The `filter` subcommand reads raw HTML** with no pre-clean stage, so its output is
  rougher than a full converter's. For a production Confluence→Markdown path that adds
  the BeautifulSoup pre-clean around this exact filter, use the `html-to-markdown` skill.
- **UTF-8**: the CLI reconfigures stdout to UTF-8 so non-ASCII content does not crash on
  a redirected Windows (cp1252) console.
