---
name: docx-to-markdown
description: Convert Word .docx documents to clean GitLab-flavoured Markdown with pandoc — batch a whole folder, extract embedded images to a media/ folder, and harvest title/author/date into YAML frontmatter. Use when someone wants to turn .docx / Word files into .md, convert a docx export, or asks to "convert this doc to markdown". Self-contained vendored scripts — needs only pandoc + PyYAML, not the parent pipeline.
---

# docx-to-markdown — Word .docx → clean Markdown

A portable, **pandoc-native** Word→Markdown converter. Unlike the HTML path it needs
no BeautifulSoup and no AST filter: pandoc's docx reader handles headings, lists,
tables, code, and footnotes natively. The flow is three short stages:

1. **Harvest** — read `docProps/core.xml` for title/author/date (stdlib `zipfile` +
   `xml`, never raises).
2. **Read + Write** — one `pandoc docx → gfm` process; `--extract-media` pulls
   embedded images out so links resolve on disk.
3. **Post** — fence-aware GFM cleanup + YAML-safe frontmatter.

This skill is self-contained: the scripts under `scripts/` are vendored copies with
no dependency on any parent project.

## Requirements

- **pandoc** on PATH — <https://pandoc.org/installing.html> (Conda: `conda install -c conda-forge pandoc`).
- **PyYAML** — `pip install pyyaml`.

## Usage

Run the CLI directly (it puts its own folder on `sys.path`, so the vendored modules
resolve with no install):

```bash
# One file → demo.md next to it
python scripts/convert_docx.py path/to/demo.docx

# A whole folder → mirror the tree under out/, extracting images to media/
python scripts/convert_docx.py ./inbox -o ./out

# Drop images (keep alt text), no TOC, override author
python scripts/convert_docx.py report.docx --no-media --author "Jane Smith"
```

Key flags: `-o/--out-dir`, `--no-frontmatter`, `--toc` (default OFF — a `[[_TOC_]]`
paragraph is junk in an embedding corpus), `--no-media`, `--title`, `--author`,
`--pandoc-path`.

## Files

| Path | Role |
|---|---|
| [scripts/convert_docx.py](scripts/convert_docx.py) | the CLI (single file or directory) |
| [scripts/docx_to_md.py](scripts/docx_to_md.py) | `convert_docx_file` + `harvest_docx_metadata` |
| [scripts/base.py](scripts/base.py) | shared pandoc wrapper, fence-aware post-process, YAML-safe frontmatter, metrics |

## Notes

- **Programmatic use**: `from docx_to_md import convert_docx_file` returns the tuple
  `out_path`, `markdown`, `metrics`, `notes` so a caller can collect results without the CLI.
- **Frontmatter**: explicit `--title`/`--author` win over harvested core properties.
  The `author:` key is singular (the convention the parent pipeline reads back).
- **Media**: with extraction on, images land in `media/` beside the `.md` and links
  are rewritten relative to the output. `--no-media` replaces each image with its alt
  text instead of shipping a dead link.
- **In-repo equivalent**: inside this project the same converter is exposed as
  `sdd-pipeline convert-docx`; these vendored scripts are the standalone counterpart
  for sharing the capability without the pipeline.
