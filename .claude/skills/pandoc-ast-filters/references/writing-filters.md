# Writing a panflute filter

A pandoc filter is a function that walks the document AST and returns replacement
elements. [panflute](https://scorphus.github.io/panflute/) wraps pandoc's JSON AST in
typed Python classes (`pf.Para`, `pf.Div`, `pf.Table`, `pf.CodeBlock`, `pf.Str`, …).

## The shape of a filter

```python
import panflute as pf

def action(elem, doc):
    # Return None to keep elem unchanged.
    # Return a (list of) element(s) to replace it.
    # Return [] to delete it.
    if isinstance(elem, pf.Strikeout):
        return list(elem.content)        # unwrap ~~text~~ to plain text
    if isinstance(elem, pf.CodeBlock) and "py" in elem.classes:
        elem.classes = ["python"]         # normalise a fence language
        return None

if __name__ == "__main__":
    pf.toJSONFilter(action)               # runs as: pandoc in.html --filter thisfile.py -o out.md
```

Two ways to run it:

- **In-process** (this skill's `pandoc_ast.apply_filter`): `pf.load` the AST string →
  `pf.run_filter` with your `action` → `pf.dump` it back. One Python process, no extra
  subprocess. Best when you already hold the AST string.
- **Classic CLI filter**: `pandoc in.html --filter ./myfilter.py -o out.md`, where the
  script ends in `pf.toJSONFilter(action)` reading the AST on stdin. Best when you want
  a drop-in for an existing pandoc command line.

## The `data-` attribute gotcha

When pandoc reads HTML with `+native_divs`/`+native_spans`, a `<div data-macro="info">`
becomes a `pf.Div` whose `attributes` map sometimes **keeps** the `data-` prefix and
sometimes **drops** it — `data-macro` arrives as key `macro`, but `data-title` stays
`data-title` because bare `title` collides with a known HTML attribute. Always check
both spellings:

```python
def attr(elem, name):
    a = getattr(elem, "attributes", {}) or {}
    return a.get(name) or a.get(f"data-{name}") or ""
```

The bundled `confluence_pf_filter.py` (`pfi_attr`) does exactly this.

## Patterns worth copying from `confluence_pf_filter.py`

- **Dispatch by type** with `isinstance` against `pf.Div` / `pf.Span` / `pf.Table` /
  `pf.CodeBlock` / `pf.Para`, classifying on `elem.classes`.
- **Never let a rule kill the document**: wrap each rule in `try/except` and degrade to
  an unwrap (`return list(elem.content)`) so a bug can't drop content silently.
- **Table simplification**: flatten every cell to a single `pf.Plain` of inlines so the
  GFM writer always emits a valid pipe table instead of falling back to raw `<table>`
  HTML. Escape `|` inside code spans as `\|`, and turn `pf.LineBreak` into a `<br />`
  raw inline (the only line break a pipe-table cell can carry).
- **Fold tiered/merged header rows into the body** — GFM tables allow at most one header
  row; extra header rows must become ordinary data rows or the whole table degrades.

## Designing a filter

Start by dumping the AST so you can see exactly what element types and attributes you
are dealing with:

```bash
python scripts/pandoc_ast.py dump sample.html --from html | less
```

Then write rules against those element types, and verify with the `filter` subcommand.
