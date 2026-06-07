# Convert HTML → GitLab Markdown on Windows

How to run the `html_to_gitlab_md.py` converter on Windows to turn a Confluence (or
generic) HTML export into a clean GitLab-flavoured `.md` file.

## Prerequisites

The environment in this repo is already set up:

- **pandoc** installed at `C:\Program Files\Pandoc\pandoc` (on PATH).
- **beautifulsoup4** + **lxml** present in the project `.venv`.
- Sample input: `docs/sample/SAD_RetailNexus_OMS_Confluence.html`.

The script (`src/sdd_pipeline/html_to_gitlab_md.py`) runs a 3-stage pipeline:
BeautifulSoup pre-clean → pandoc convert → markdown post-process. It auto-detects
pandoc via `shutil.which("pandoc")`.

## Important: UTF-8 on Windows

The script prints emoji (📄 📝 🔧 ✅) to the console. The default Windows console
encoding is cp1252, which **crashes** with:

```
UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f4c4'
```

Force UTF-8 output before running (this only affects console messages, not the
conversion itself):

```powershell
$env:PYTHONUTF8 = "1"
```

Set it once per PowerShell session and run the script as many times as you like.

## How to run

Run from the inner project root so the `.venv` interpreter (with bs4/lxml) is used.

### Basic — output `.md` next to the input

```powershell
cd c:\Users\midgard\dev\poc\sdd-semantic-pipeline\sdd-semantic-pipeline
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe src\sdd_pipeline\html_to_gitlab_md.py `
  docs\sample\SAD_RetailNexus_OMS_Confluence.html
```

→ writes `docs\sample\SAD_RetailNexus_OMS_Confluence.md`

### Choose an explicit output path

```powershell
.\.venv\Scripts\python.exe src\sdd_pipeline\html_to_gitlab_md.py `
  docs\sample\SAD_RetailNexus_OMS_Confluence.html `
  -o docs\architecture.md
```

### Convert your own file

```powershell
.\.venv\Scripts\python.exe src\sdd_pipeline\html_to_gitlab_md.py `
  path\to\your.html -o docs\your-output.md -v
```

## Batch conversion + JSON report (recommended)

To convert **every** HTML file under a directory and emit a machine-readable
report (per-file section / picture / code-snippet / list / table / URL counts),
use the `convert` sub-command of the installed CLI:

```powershell
cd c:\Users\midgard\dev\poc\sdd-semantic-pipeline\sdd-semantic-pipeline
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m sdd_pipeline.cli convert docs `
  --output build\md `
  --report build\conversion-report.json `
  -v
```

This scans `docs\**\*.html` recursively, writes a `.md` for each input (mirroring
the source tree under `--output`), and writes a JSON report. Omit `--output` to
write each `.md` next to its source HTML.

The report looks like:

```json
{
  "generated_at": "2026-06-05T18:14:11+00:00",
  "input_dir": "docs",
  "glob": "**/*.html",
  "total_files": 1,
  "succeeded": 1,
  "failed": 0,
  "totals": { "sections": 35, "pictures": 0, "code_snippets": 3, "lists": 35, "tables": 10, "urls": 17 },
  "files": [
    {
      "source": "docs\\sample\\SAD_RetailNexus_OMS_Confluence.html",
      "output": "build\\md\\sample\\SAD_RetailNexus_OMS_Confluence.md",
      "status": "ok",
      "metrics": { "sections": 35, "pictures": 0, "code_snippets": 3, "lists": 35, "tables": 10, "urls": 17 },
      "error": null
    }
  ]
}
```

A file that fails to convert is recorded with `"status": "error"` and the message
in `"error"` — the run continues and the command exits non-zero if any file failed.

### Batch options

| Option | Effect |
|--------|--------|
| `--output` / `-o` | Directory for generated `.md` (mirrors input tree). Default: next to each HTML |
| `--glob` / `-g` | HTML glob pattern (default `**/*.html`) |
| `--report` / `-r` | JSON report path (default `conversion-report.json`) |
| `--selector`, `--no-frontmatter`, `--no-toc`, `--keep-diagrams`, `--pandoc-path` | Same as the single-file converter |
| `-v` / `--verbose` | Print a per-file metric summary line |

## Single-file options

| Option | Effect |
|--------|--------|
| `--title "My Doc"` | Override the YAML front-matter title |
| `--author "Name"` | Add author(s) to front matter |
| `--no-frontmatter` | Skip the YAML front-matter block |
| `--no-toc` | Skip the `[[_TOC_]]` GitLab directive |
| `--selector "article.main"` | Pin the content root if auto-detect picks the wrong region |
| `--keep-diagrams` | Keep SVG diagram HTML instead of a placeholder |
| `--pandoc-path "C:\path\to\pandoc.exe"` | Use a specific pandoc binary |
| `-v` / `--verbose` | Print per-stage details + validation checks |
| `-h` | Show full help |

## Verification

- The command exits `0` and prints `✅ Done` with line/word/heading/table stats.
- Open the generated `.md` and confirm: YAML front matter at the top, `[[_TOC_]]`,
  fenced code blocks with language labels, pipe tables, and no raw `<div class=...>`.
- The script self-validates (`validate()`). Exit code `1` means a check failed —
  rerun with `-v` to see which one.

### Example successful run

```
📄  Input   : ...\docs\sample\SAD_RetailNexus_OMS_Confluence.html
📝  Output  : ...\docs\sample\SAD_RetailNexus_OMS_Confluence.md
🔧  Pandoc  : C:\Program Files\Pandoc\pandoc.EXE

Converting (pre-process -> pandoc -> post-process)...

  ✅ No raw <div class= attrs
  ✅ No base64 data URIs
  ✅ No Confluence CSS class refs
  ✅ Pipe tables present
  ✅ Headings present
  ✅ No 3+ consecutive blank lines

✅ Done
   408 lines · 2948 words · 20,250 chars · 35 headings · 44 tables · 3 code blocks · 8 blockquotes
```

## Notes

- If you prefer the global Python instead of the venv, install deps first:
  `pip install beautifulsoup4 lxml` (pandoc is already on PATH).
- pandoc install reference: <https://pandoc.org/installing.html> (or
  `conda install -c conda-forge pandoc`).
