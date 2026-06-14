# Convert HTML GitLab Markdown Windows

**Last Updated:** 2026-06-06
**Sources:** `docs/inbox/Convert.Windows.Readme.md`
**Related:** [confluence-storage-format-gitlab-markdown](confluence-storage-format-gitlab-markdown.md), [convert-html-gitlab-markdown-linux](convert-html-gitlab-markdown-linux.md)

---

## Summary
This page explains how to run the HTML-to-GitLab Markdown converter on Windows. It captures the Windows-specific console encoding requirement, sample commands, batch conversion workflow, and the expected verification results.

## Key Facts
- The Windows environment is expected to already have pandoc installed at `C:\Program Files\Pandoc\pandoc` and the project dependencies available in `.venv` (source: `docs/inbox/Convert.Windows.Readme.md`)
- Windows console output must use UTF-8 because the script prints emoji and the default cp1252 encoding can raise `UnicodeEncodeError` (source: `docs/inbox/Convert.Windows.Readme.md`)
- The recommended fix is to set `$env:PYTHONUTF8 = "1"` before running the converter (source: `docs/inbox/Convert.Windows.Readme.md`)
- Single-file and batch conversion commands use the inner project root and the `.venv\Scripts\python.exe` interpreter (source: `docs/inbox/Convert.Windows.Readme.md`)
- Batch conversion scans `docs\**\*.html`, mirrors the source tree under the output directory, and writes a JSON report with totals and per-file status (source: `docs/inbox/Convert.Windows.Readme.md`)
- Verification focuses on exit status `0`, the `✅ Done` message, and Markdown output that includes front matter, `[[_TOC_]]`, fenced code blocks, and pipe tables (source: `docs/inbox/Convert.Windows.Readme.md`)

## Decisions and Constraints
> **Decision [2026-06-06]:** Require `PYTHONUTF8=1` in Windows PowerShell sessions before running the converter. Source: `docs/inbox/Convert.Windows.Readme.md`
> **Decision [2026-06-06]:** Use the project `.venv` interpreter directly instead of relying on the global Python installation. Source: `docs/inbox/Convert.Windows.Readme.md`
> **Decision [2026-06-06]:** Treat batch conversion reports as the primary way to audit large conversion runs. Source: `docs/inbox/Convert.Windows.Readme.md`

## Open Questions
- No open questions.

## Contradictions
No contradictions.

## Detail
The Windows guide mirrors the Linux workflow but adds a platform-specific prerequisite: the console must emit UTF-8 because the script prints emoji in status messages. Without that setting, default Windows code page handling can fail before or during the conversion run. The recommended operational step is to set `PYTHONUTF8=1` in the active PowerShell session and then invoke the converter through the project `.venv`.

The document provides concrete command examples for single-file conversion, explicit output paths, and batch conversion over a directory tree. Batch mode preserves the input structure under the output directory and generates a JSON report with both aggregate totals and per-file metrics, including success or failure status and any error message. Verification is based on the command’s exit code and the presence of expected Markdown structures in the output file.
