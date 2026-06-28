# SDD Semantic Pipeline

A two-flow toolkit for turning Confluence/HTML/Word SDD & ADR documents into a
**local, searchable knowledge base**:

- **Flow A — indexing & search.** A 7-stage pipeline (pandoc → structural →
  enrich → chunk → embed → store → search) that turns Markdown into a vector index
  you query with `search`, the `tui`, or an `mcp` server for GitHub Copilot.
- **Flow B — conversion.** An independent Confluence-rendered-HTML → GitLab-Markdown
  converter (`convert`), plus Word docx (`convert-docx`) and Gliffy diagram
  (`resolve-gliffy`, `convert-drawio`) paths.

## Start here

| If you want to… | Go to |
|---|---|
| Run the pipeline end-to-end | [Pipeline 101 runbook](guides/pipeline-101.md) |
| Look up a command or flag | [CLI reference](reference/cli.md) |
| Look up a setting / env var | [Configuration reference](reference/configuration.md) |
| Understand the architecture | [Architecture & guardrails](_root/claude.md) · [ADR-0001](adr/adr-0001-modular-semantic-pipeline.md) |
| Learn the codebase (C# → Python) | [Learn curriculum](learn/README.md) |
| Understand the tests | [Testing](testing/index.md) |
| Convert HTML to Markdown | [Linux](guides/convert-html-gitlab-markdown-linux.md) · [Windows](guides/convert-html-gitlab-markdown-windows.md) |
| Present the project | [Presentation decks](presentation/README.md) |

## Design rationale

The "why" behind the architecture lives in four defense documents:
[Technology selection](technology-selection.md) ·
[Processing mode & structural model](processing-mode-and-structural.md) ·
[Enrichment algorithm](enrichment-algorithm.md) ·
[Confluence conversion rules](confluence-conversion-rules.md).

## This site

These docs are authored as Markdown under [`docs/`](https://github.com) and rendered
with **MkDocs Material**. The same Markdown is the single source for the repo, this
site, and a future wiki.js import. The repo-root [README](_root/readme.md) and
[CLAUDE.md](_root/claude.md) are surfaced in-site but stay canonical at the
repository root.

Three ways to read these docs, all with working full-text search:

- **Hosted** — the published [GitHub Pages](https://dertnius.github.io/sdd-semantic-pipeline/)
  / GitLab Pages sites (search works out of the box over HTTPS).
- **Offline, from disk** — run `mkdocs build`, then open `site/index.html`
  directly (double-click / `file://`). The `offline` plugin inlines the search
  index into every page, so search works with **no server**.
- **Live editing** — `mkdocs serve`, then browse <http://localhost:8000/> for a
  local site with hot-reload.

> Material's search is client-side and normally needs an HTTP server, so a plain
> `file://` build would search nothing. If search ever misbehaves from disk, serve
> the built site instead: `python -m http.server -d site 8000`.
