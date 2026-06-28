---
name: html-to-markdown
description: Convert Confluence (Cloud or Data Center) and generic rendered HTML into clean GitLab-flavoured Markdown via a 4-stage pandoc pipeline — BeautifulSoup pre-clean, pandoc html→json, an in-process panflute filter (admonitions, expands, lozenges, layouts, table simplification), pandoc json→gfm, then fence-aware post-process with YAML-safe frontmatter. Use when someone wants to turn exported Confluence/HTML pages into Markdown, batch-convert an HTML export, or asks to "convert this HTML to md". Self-contained vendored scripts.
---

# html-to-markdown — Confluence / HTML → GitLab Markdown

A portable converter for **rendered** HTML exports (Confluence Space export or
"Export to HTML", or any generic HTML). It runs the 4-stage pipeline:

1. **Pre-clean** (BeautifulSoup) — strip UI chrome and rewrite Confluence constructs
   into a pandoc-friendly intermediate (`div`/`span` carriers with `data-*` attrs).
2. **Read** — `pandoc html → json` AST.
3. **Filter** (in-process panflute) — admonitions → blockquote labels, expands → bold
   paragraphs, lozenges → bold, layouts flattened, tables simplified to valid pipe
   tables.
4. **Write + Post** — `pandoc json → gfm`, then fence-aware regex fixes + YAML-safe
   frontmatter (title/author/space/date/page_id harvested from page chrome).

Storage-format input (`<ac:>`/`<ri:>`/`<at:>` tags) is **refused** — this path is for
rendered HTML only. The scripts under `scripts/` are vendored standalone copies.

## Requirements

- **pandoc** on PATH — <https://pandoc.org/installing.html>.
- Python deps: `pip install beautifulsoup4 lxml panflute pyyaml`.

## Usage

```bash
# Batch a folder of exported pages → mirror under out/
python scripts/convert_html.py ./export -o ./out

# One page, with a forced content selector and a space key for frontmatter
python scripts/convert_html.py page.html -o page.md --selector "div#main-content" --space ARCH

# Single file via the lower-level script (also has --confluence-version, -v)
python scripts/html_to_gitlab_md.py page.html -o page.md
```

Key flags (`convert_html.py`): `-o/--out-dir`, `--selector`, `--no-frontmatter`,
`--toc` (default OFF), `--keep-diagrams`, `--space`, `--source-url`, `--pandoc-path`.

## Files

| Path | Role |
|---|---|
| [scripts/convert_html.py](scripts/convert_html.py) | batch CLI (single file or directory) |
| [scripts/html_to_gitlab_md.py](scripts/html_to_gitlab_md.py) | the 4-stage engine + a single-file CLI |
| [scripts/confluence_pf_filter.py](scripts/confluence_pf_filter.py) | the Stage-C panflute filter |
| [scripts/base.py](scripts/base.py) | shared pandoc wrapper, post-process, frontmatter, metrics |

## Notes

- **Programmatic use**: `from html_to_gitlab_md import convert_file` returns the tuple
  `out_path`, `markdown`, `metrics`, `notes`. The `notes` dict's `warnings` list flags
  lossy spots (merged cells, nested tables) for review.
- **Auto root detection**: with no `--selector` it tries the common Confluence Cloud +
  Data Center containers, then `<main>`/`<article>`, then `<body>`. Point `--selector`
  at the real content div if a page has unusual chrome.
- **Diagrams**: by default a diagram becomes an italic caption (a base64 blob is pure
  noise downstream). To keep editable diagrams, see the sibling `gliffy-to-svg` /
  `gliffy-to-drawio` skills for the out-of-band `.gliffy` attachments.
- **In-repo equivalent**: inside this project the same converter is `sdd-pipeline convert`;
  these vendored scripts are the standalone counterpart.
