# Convert HTML → GitLab Markdown on Linux

How to run the `html_to_gitlab_md.py` converter on Linux to turn a Confluence (or
generic) HTML export into a clean GitLab-flavoured `.md` file.

## Prerequisites

- **pandoc** installed and on `PATH`.
  - Debian/Ubuntu: `sudo apt install pandoc`
  - Fedora/RHEL: `sudo dnf install pandoc`
  - Arch: `sudo pacman -S pandoc`
  - Conda: `conda install -c conda-forge pandoc`
  - Verify: `pandoc --version`
- **Python 3.10+** with **beautifulsoup4** + **lxml**.
  - If the project ships a `.venv`, use it: `./.venv/bin/python`.
  - Otherwise create one:
    ```bash
    python3 -m venv .venv
    ./.venv/bin/pip install beautifulsoup4 lxml
    ```
- Sample input: `docs/sample/SAD_RetailNexus_OMS_Confluence.html`.

The script (`src/sdd_pipeline/html_to_gitlab_md.py`) runs a 3-stage pipeline:
BeautifulSoup pre-clean → pandoc convert → markdown post-process. It auto-detects
pandoc via `shutil.which("pandoc")`.

## UTF-8 note

The script prints emoji (📄 📝 🔧 ✅). Most Linux systems use a UTF-8 locale by
default, so this just works. If you run in a minimal/`C`-locale environment (some
containers, cron, CI) and hit a `UnicodeEncodeError`, force UTF-8:

```bash
export PYTHONUTF8=1
# or:  export LANG=C.UTF-8
```

## How to run

Run from the inner project root so the `.venv` interpreter (with bs4/lxml) is used.

### Basic — output `.md` next to the input

```bash
cd /path/to/sdd-semantic-pipeline/sdd-semantic-pipeline
./.venv/bin/python src/sdd_pipeline/html_to_gitlab_md.py \
  docs/sample/SAD_RetailNexus_OMS_Confluence.html
```

→ writes `docs/sample/SAD_RetailNexus_OMS_Confluence.md`

### Choose an explicit output path

```bash
./.venv/bin/python src/sdd_pipeline/html_to_gitlab_md.py \
  docs/sample/SAD_RetailNexus_OMS_Confluence.html \
  -o docs/architecture.md
```

### Convert your own file

```bash
./.venv/bin/python src/sdd_pipeline/html_to_gitlab_md.py \
  path/to/your.html -o docs/your-output.md -v
```

If you activate the venv first (`source ./.venv/bin/activate`), you can just call
`python src/sdd_pipeline/html_to_gitlab_md.py ...`.

## Batch conversion + JSON report (recommended)

To convert **every** HTML file under a directory and emit a machine-readable
report (per-file section / picture / code-snippet / list / table / URL counts),
use the `convert` sub-command of the installed CLI:

```bash
cd /path/to/sdd-semantic-pipeline/sdd-semantic-pipeline
./.venv/bin/python -m sdd_pipeline.cli convert docs \
  --output build/md \
  --report build/conversion-report.json \
  -v
```

This scans `docs/**/*.html` recursively, writes a `.md` for each input (mirroring
the source tree under `--output`), and writes a JSON report. Omit `--output` to
write each `.md` next to its source HTML.

The report contains run metadata, aggregate `totals`, and one `files[]` entry per
input:

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
      "source": "docs/sample/SAD_RetailNexus_OMS_Confluence.html",
      "output": "build/md/sample/SAD_RetailNexus_OMS_Confluence.md",
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
| `--pandoc-path /path/to/pandoc` | Use a specific pandoc binary |
| `-v` / `--verbose` | Print per-stage details + validation checks |
| `-h` | Show full help |

## Verification

- The command exits `0` and prints `✅ Done` with line/word/heading/table stats.
- Open the generated `.md` and confirm: YAML front matter at the top, `[[_TOC_]]`,
  fenced code blocks with language labels, pipe tables, and no raw `<div class=...>`.
- The script self-validates (`validate()`). Exit code `1` means a check failed —
  rerun with `-v` to see which one. Check it explicitly with `echo $?`.

### Example successful run

```
📄  Input   : .../docs/sample/SAD_RetailNexus_OMS_Confluence.html
📝  Output  : .../docs/sample/SAD_RetailNexus_OMS_Confluence.md
🔧  Pandoc  : /usr/bin/pandoc

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

- If you prefer your system Python instead of a venv, install deps first:
  `pip install beautifulsoup4 lxml` (pandoc is already on PATH).
- pandoc install reference: <https://pandoc.org/installing.html>.
