# Convert HTML GitLab Markdown Linux

**Last Updated:** 2026-06-06
**Sources:** `docs/inbox/Convert.Linux.Readme.md`
**Related:** [confluence-conversion-rules](../confluence-conversion-rules.md), [convert-html-gitlab-markdown-windows](convert-html-gitlab-markdown-windows.md)

---

## Summary
This page explains how to run the HTML-to-GitLab Markdown converter on Linux. It documents prerequisites, command examples, batch conversion, verification steps, and the UTF-8 handling note for non-UTF-8 locales.

## Key Facts
- The Linux path expects pandoc on `PATH` and Python 3.10+ with `beautifulsoup4` and `lxml` available, preferably through the project `.venv` (source: `docs/inbox/Convert.Linux.Readme.md`)
- The converter runs a three-stage flow: BeautifulSoup pre-clean, pandoc conversion, and markdown post-processing (source: `docs/inbox/Convert.Linux.Readme.md`)
- The script auto-detects pandoc with `shutil.which("pandoc")` (source: `docs/inbox/Convert.Linux.Readme.md`)
- Batch conversion scans the inbox for `**/*.html` (default `inbox/`), mirrors the source tree under the output directory (default `outbox/md/`), and produces a JSON report with per-file metrics (source: `docs/inbox/Convert.Linux.Readme.md`)
- The Linux instructions recommend setting `PYTHONUTF8=1` if a minimal or `C` locale causes `UnicodeEncodeError` during console output (source: `docs/inbox/Convert.Linux.Readme.md`)
- Verification requires checking for YAML front matter, `[[_TOC_]]`, fenced code blocks, pipe tables, and the absence of raw `<div class=...>` output (source: `docs/inbox/Convert.Linux.Readme.md`)

## Decisions and Constraints
> **Decision [2026-06-06]:** Run the converter from the project root so the project `.venv` interpreter and dependencies are used; place input HTML under `inbox/` and read converted output from `outbox/md/`. Source: `docs/inbox/Convert.Linux.Readme.md`
> **Decision [2026-06-06]:** Use the `convert` CLI subcommand for batch processing and emit a machine-readable JSON report. Source: `docs/inbox/Convert.Linux.Readme.md`
> **Decision [2026-06-06]:** Treat UTF-8 locale configuration as an operational requirement when console encoding is not already UTF-8. Source: `docs/inbox/Convert.Linux.Readme.md`

## Open Questions
- No open questions.

## Contradictions
No contradictions.

## Detail
The Linux guide assumes a Unix-like environment with pandoc installed, a working Python 3.10+ interpreter, and the project dependencies installed in the local virtual environment. The recommended execution pattern is to activate or directly invoke the `.venv` interpreter from the project root and then run `src/sdd_pipeline/convert/html_to_gitlab_md.py` or the installed CLI entry point.

The guide distinguishes single-file conversion from batch conversion. Single-file runs (via the legacy script) write a Markdown file next to the input or to a specified output path; the `convert` CLI command instead reads HTML from the **inbox** and writes the mirrored `.md` tree under the **outbox** (`outbox/md/`) — the workspace contract. Batch runs recurse through HTML files, mirror the tree into the output directory, and produce a JSON summary with totals and per-file status. The report records successes and failures separately so one conversion failure does not stop the full batch run.

Verification is explicit: the converter should exit with status `0`, print a completion message, and produce Markdown with front matter, a TOC directive, fenced code blocks, pipe tables, and no raw Confluence HTML wrappers. The notes section also records pandoc installation references and the option to use a system Python if the dependencies are installed manually.
