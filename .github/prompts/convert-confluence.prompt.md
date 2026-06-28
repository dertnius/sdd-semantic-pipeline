---
mode: agent
description: Convert Confluence/rendered-HTML exports to GitLab-flavoured Markdown via sdd-pipeline convert (inbox/**/*.html -> outbox/md).
---

# /convert-confluence — Confluence HTML → GitLab Markdown

Drive the project's `sdd-pipeline convert` command — the 4-stage HTML→GitLab-MD
converter (BeautifulSoup pre-clean → pandoc → panflute filter → post-process).
This is the flagship ingestion path; `/doc-to-md` is the sibling for `.docx`.

## Scope — rendered HTML only

The converter accepts **rendered** Confluence/HTML exports. Literal storage-format
input (`<ac:`/`<ri:`/`<at:` tags) is **refused** with a `ConversionError` by design
(its CDATA macro bodies are dropped by the parser). If a file is rejected for that
reason, tell the user to export the **rendered** page, not the storage format.

## Steps

1. **Stage the HTML** under `inbox/` (subfolders allowed). The default input is the
   inbox; `.md` is written under `outbox/md/`, mirroring the tree.
2. **Run the converter** from the repo root with the project venv:

   ```powershell
   $env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe -m sdd_pipeline.cli convert
   ```

   Useful flags (see `sdd-pipeline convert --help`): `--toc` (opt-in TOC; OFF by
   default — a TOC paragraph is a junk chunk), `--space`/`--source-url`/`--labels`
   (provenance into frontmatter), `--quarantine/--no-quarantine` +
   `--max-unrecognized N` (the confidence gate — low-confidence pages go to
   `outbox/md/_quarantine/` and the command exits non-zero).

3. **Lint the converted corpus** before indexing:

   ```powershell
   .\.venv\Scripts\python.exe -m sdd_pipeline.cli lint outbox/md --strict
   ```

4. **Report back** from `outbox/reports/conversion-report.json`: per-file + aggregate
   metrics (`sections`, `pictures`, `code_snippets`, `lists`, `tables`, `urls`), any
   quarantined files, and the lint verdict. Quarantine or a failed file → **exit
   non-zero**; surface it, don't report blind success.

## Notes

- **pandoc must be on PATH** (the converter shells out to it).
- Diagrams (Gliffy) are dropped to a caption by the converter; resolve them
  out-of-band with `sdd-pipeline resolve-gliffy` / `sdd-pipeline convert-drawio` if
  the user needs the vector art.
- Windows console: the `convert` output is ASCII-only by design; for the legacy
  emoji-printing paths set `$env:PYTHONUTF8 = "1"`.
