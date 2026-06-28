---
mode: agent
description: Convert Word .docx files to clean GitLab-flavoured Markdown via the sdd-pipeline CLI (inbox -> outbox/md).
---

# /doc-to-md — Word .docx → Markdown

Port of the Claude `doc-to-md` skill. Drive the project's
`sdd-pipeline convert-docx` command — the CLI does the real work (pandoc-native
docx→md, frontmatter, image extraction, a JSON report); your job is to stage the
inputs, run the command, and report results.

## The inbox / outbox contract

The pipeline enforces a two-zone workspace, so inputs and outputs have fixed
default homes — no path flags are needed for the common case:

| Zone | Default path | Holds |
|---|---|---|
| **Inbox** | `inbox/` | the `.docx` source files (subfolders allowed) |
| **Outbox** | `outbox/md/` | the converted `.md` (mirrors the inbox tree) |
| Report | `outbox/reports/docx-conversion-report.json` | per-file + aggregate metrics |
| Media | `outbox/md/**/media/` | images pandoc extracts from the docx |

Out-of-zone paths are **rejected** (exit 2) unless the guard is off. To convert
files elsewhere, either point the zones at them (`PIPELINE_INBOX_DIR` /
`PIPELINE_OUTBOX_DIR`) or bypass the guard for one run
(`PIPELINE_ENFORCE_WORKSPACE=false`, then pass an explicit input dir and
`--output`).

## Steps

1. **Stage the docx** under `inbox/` (create it if missing; copy in any files the
   user names outside the inbox).
2. **Run the converter** from the repo root with the project venv. Set
   `PYTHONPATH=src` so `sdd_pipeline` imports without an editable install (the
   convention `.vscode/mcp.json` uses); after `pip install -e ".[dev]"` you can
   call the installed `sdd-pipeline convert-docx` entry point instead.

   ```powershell
   $env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe -m sdd_pipeline.cli convert-docx
   ```

   Useful flags: `<input_dir>` (positional, scan a different dir), `-o/--output`,
   `-g/--glob`, `--no-media` (drop images — cleaner for an embedding corpus),
   `--toc`, `--no-frontmatter`, `--space`/`--source-url`/`--labels` (provenance),
   `-v/--verbose`. Run `sdd-pipeline convert-docx --help` for the full list.

3. **Report back.** Read `outbox/reports/docx-conversion-report.json` and
   summarise: how many converted / failed, where the `.md` landed, any per-file
   `error`s. The command **exits non-zero if any file failed** — surface those
   errors, never report success blindly.

## Notes

- **pandoc must be on PATH.** "pandoc not found" → tell the user to install it
  (`conda install -c conda-forge pandoc` or <https://pandoc.org/installing.html>).
- `.doc` (legacy binary Word) is **not** supported — ask the user to re-save as
  `.docx`. For Confluence/HTML exports use `/convert-confluence` instead.
