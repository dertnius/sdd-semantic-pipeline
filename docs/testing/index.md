# Testing

A reference for the test suite, fixtures, marker tiers, and the evaluation harness.
For a *teaching* walkthrough of how the tests are written (fixture strategy, why the
tiers exist), read [Walkthrough 03 — the test-suite tour](../learn/walkthroughs/03-test-suite-tour.md);
this page is the lookup/facts companion.

## At a glance

- **~53 test files, ~840 test functions** under [`tests/`](../../tests).
- **Coverage gate:** `fail_under = 70` ([`pyproject.toml`](../../pyproject.toml)),
  with `cli.py` omitted (the Typer CLI is best covered by integration tests).
- **Default dev loop:** `pytest -m "not slow"` — no pandoc binary, no model download.

## Commands

```powershell
pytest -m "not slow"                 # fast unit lane (default while iterating)
pytest                               # full suite (needs pandoc; first run downloads a model)
pytest tests/test_enrichment.py -k "test_extract_entities"   # single test
pytest -m "not slow" --cov=sdd_pipeline --cov-report=term-missing
ruff format src/ tests/ && ruff check src/ tests/            # lint + format
mypy src/                            # type-check
```

## Marker tiers

| Marker | Meaning | When it runs |
|---|---|---|
| *(none)* | Fast unit test — pure-Python, deterministic, no pandoc/model. | Always. |
| `slow` | Needs the pandoc binary or a real ML model. | Full `pytest` only. |
| `integration` | End-to-end with all runtime services. | Full `pytest` only. |

Mark any test that shells out to pandoc or loads an embedding model `slow`.

## The model-free fast lane

The fast lane exercises the real `index → search` path **without a model or pandoc**
via fixtures in [`tests/conftest.py`](../../tests/conftest.py):

| Fixture | Role |
|---|---|
| `hashing_embedder` | Deterministic, model-free hash embedder (512-dim from token hashing + L2 norm). Inject into `SemanticPipeline(..., embedding_model=hashing_embedder)` to run enrich→chunk→embed→store→search offline. |
| `sample_document_model` | Pre-built `DocumentModel` with typed sections (skips pandoc stages 2–3). |
| `sample_ast` | Hand-written pandoc JSON AST (no pandoc binary needed). |
| `sample_chunks` | Minimal `SemanticChunk`s (skips stages 2–6). |
| `_workspace_env` (autouse) | Sets `PIPELINE_ENFORCE_WORKSPACE=false` and redirects default zones to `tmp_path`, so tests never touch the repo's inbox/outbox. |

[`tests/test_search_offline.py`](../../tests/test_search_offline.py) validates the
search *contract* (filters narrow, output is stable, hybrid/RRF runs) on the
hashing embedder — semantic *relevance* lives in the `slow` e2e tests.

## What's covered

| Area | Representative test files |
|---|---|
| Core stages | `test_ast_parser`, `test_structural`, `test_enrichment`, `test_chunking`, `test_vocabulary`, `test_embeddings`, `test_vector_store` |
| Entity / taxonomy | `test_enrichment_inventory`, `test_extract_structural`, `test_extract_prose`, `test_reconcile`, `test_corpus_taxonomy`, `test_template_taxonomy`, `test_header_norm`, `test_doc_router`, `test_detection`, `test_lang_rules` |
| Retrieval & search | `test_retrieval`, `test_search_offline`, `test_eval_retrieval` |
| Quality gates | `test_quality`, `test_chunk_gate` |
| Workspace contract | `test_workspace`, `test_cli_workspace` |
| CLI / TUI / MCP | `test_cli`, `test_tui`, `test_cli_mcp` |
| Converter (flow B) | `tests/convert/test_html_to_gitlab_md`, `test_html_to_gitlab_md_v3`, `test_convert_cli`, `test_confluence_pf_filter`, `test_docx_to_md` |
| Diagrams | `test_gliffy_to_svg`, `test_gliffy_parse`, `test_drawio`, `test_diagram_model`, `test_fidelity`, `test_drawio_png_regression`, `test_convert_drawio_cli` |
| Config / models | `test_config`, `test_models` |
| Skills / doc-health | `test_doctomd_skill`, `test_check_docs`, `test_docs_sync_skill` |

## Evaluation harness

Retrieval quality is measured separately from correctness, in
[`src/tools/eval/`](../../src/tools/eval/README.md) (see its README):

- `corpus/` — committed SDD-shaped golden documents.
- `queries.yaml` / `e2e_queries.yaml` — frozen golden query sets.
- `RETRIEVAL_LOG.md` — append-only baseline + milestone record.
- Driven by [`src/tools/scripts/eval_retrieval.py`](../../src/tools/scripts/eval_retrieval.py)
  (recall@5/@10, MRR). `slow`; runs against a real model or the mock embedder.

## Converter regression fixtures

[`tests/convert/examples/`](../../tests/convert/examples/README.md) holds the HTML
fixtures (clean render, adversarial edge cases, storage-format) and documents the
tier-1/2/3 "no information loss" quality bar the converter must hold.

## Documentation health checks

The docs themselves are tested. [`check_docs.py`](../../src/tools/scripts/check_docs.py)
(no LLM/model/pandoc) asserts docs are **not broken** (links, source-refs, render,
well-formedness) **and updated** (CLI/config/extras/citation coverage against the
code). It runs in the CI `verify` stage alongside `mkdocs build --strict`. The
on-demand `docs-sync` skill (`.claude/skills/docs-sync/SKILL.md`, a tracked portable
Agent Skill read by both Claude Code and Copilot) drives the same reconciliation
interactively.
