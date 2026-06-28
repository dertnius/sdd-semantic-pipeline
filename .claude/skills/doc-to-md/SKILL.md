---
name: doc-to-md
description: Convert Word .docx documents to clean Markdown using the sdd-pipeline CLI. Use when the user wants to turn .docx / Word files into .md, batch-convert a folder of docx, or asks to "convert this doc to markdown". Reads from an inbox directory and writes Markdown to an outbox directory.
---

# doc-to-md — Word .docx → Markdown

Convert one or many Word `.docx` documents into clean GitLab-flavoured Markdown
by driving the project's `sdd-pipeline convert-docx` CLI command. The CLI does
the real work (pandoc-native docx→md, frontmatter, image extraction, a JSON
report); this skill defines the **inbox** (where docx go in) and **outbox**
(where `.md` comes out) and runs the command for the user.

## Locations (the inbox / outbox contract)

The pipeline enforces a two-zone workspace, so inputs and outputs have fixed
default homes — no path flags are needed for the common case:

| Zone | Default path | Holds |
|---|---|---|
| **Inbox** | `inbox/` | the `.docx` source files (subfolders allowed) |
| **Outbox** | `outbox/md/` | the converted `.md` (mirrors the inbox tree) |
| Report | `outbox/reports/docx-conversion-report.json` | per-file + aggregate metrics |
| Media | `outbox/md/**/media/` | images pandoc extracts from the docx |

Out-of-zone paths are **rejected** (exit 2) unless the workspace guard is off.
To convert files that live elsewhere, either:

- point the zones at them via env vars —
  `PIPELINE_INBOX_DIR=<dir>` and `PIPELINE_OUTBOX_DIR=<dir>`; or
- bypass the guard for an ad-hoc run — `PIPELINE_ENFORCE_WORKSPACE=false`, then
  pass an explicit input dir and `--output`.

## Workflow

1. **Stage the docx.** Make sure the `.docx` files are under the inbox.
   - If the user names files outside `inbox/`, copy them in (or use the env-var
     override above). Create `inbox/` if it does not exist.
2. **Run the converter** from the project root, using the project venv. Set
   `PYTHONPATH=src` so `sdd_pipeline` imports without an editable install (the
   same convention `.vscode/mcp.json` uses); if you have run
   `pip install -e ".[dev]"`, you can drop the `PYTHONPATH` and call the
   installed `sdd-pipeline convert-docx` entry point instead.

   ```powershell
   $env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe -m sdd_pipeline.cli convert-docx
   ```

   That bare form converts `inbox/**/*.docx` → `outbox/md/` and writes the
   report. Useful flags:

   | Flag | Effect |
   |---|---|
   | `<input_dir>` (positional) | scan this dir instead of the inbox |
   | `-o, --output <dir>` | write `.md` somewhere other than `outbox/md/` |
   | `-g, --glob "<pat>"` | match a different pattern (default `**/*.docx`) |
   | `--no-media` | drop embedded images (keep their alt text) — cleaner for an embedding corpus |
   | `--toc` | inject a `[[_TOC_]]` directive (human-docs only) |
   | `--no-frontmatter` | omit the YAML frontmatter block |
   | `--space` / `--source-url` / `--labels` | provenance written into frontmatter |
   | `-v, --verbose` | print a per-file metrics line |

   Example — convert a single subfolder, image-free, for the search index:

   ```powershell
   $env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe -m sdd_pipeline.cli convert-docx inbox/specs --no-media -v
   ```

3. **Report back.** Read `outbox/reports/docx-conversion-report.json` (or the
   `--report` path) and summarise: how many converted / failed, where the `.md`
   landed, and any per-file `error`s. List the produced files under the outbox.

## Notes

- **pandoc must be on PATH** (the converter shells out to it). If the command
  errors with "pandoc not found", tell the user to install pandoc
  (`conda install -c conda-forge pandoc` or https://pandoc.org/installing.html).
- The command exits **non-zero if any file failed** — surface those errors, do
  not report success blindly.
- `.doc` (legacy binary Word) is **not** supported — ask the user to re-save as
  `.docx`. For HTML exports use the sibling `convert` command instead.
- Each converted file gets a YAML frontmatter block (`title`, `author`, `date`
  harvested from the docx core properties, plus any provenance flags), so the
  output is ready to feed the rest of the pipeline (`index` / `export`).
