---
applyTo: "tests/**/*.py"
description: Test conventions — markers (slow/integration), shared fixtures, model-free fast lane, mocks over real services.
---

# Test conventions

These rules apply to `tests/**`.

- **Default to the fast lane.** A test with no marker must run with neither pandoc
  nor an ML model and stay fast. Run `pytest -m "not slow"` while iterating.
- **Markers:**
  - `slow` — needs the pandoc binary or a real embedding model. Mark any such test.
  - `integration` — full end-to-end with all services.
- **Reuse `tests/conftest.py` fixtures** rather than rebuilding state. Notably:
  - `hashing_embedder` — deterministic, model-free embedder. Inject it into
    `SemanticPipeline(..., embedding_model=hashing_embedder)` to exercise the real
    index→search path **without** a model (see `tests/test_search_offline.py`).
  - `sample_document_model` — a pre-built `DocumentModel` to chunk/embed.
  - the autouse `PIPELINE_ENFORCE_WORKSPACE=false` fixture bypasses the workspace
    guard; the contract itself is covered by `test_workspace.py` /
    `test_cli_workspace.py`.
- **Prefer mocks** for the vector store and embedder in unit tests; avoid network and
  large-model downloads in default paths.
- **`pythonpath=["src"]`** is set in `pyproject.toml`, so `import sdd_pipeline` works
  without installing.
- Test the **contract**, not internal incidentals — the offline search tests assert
  filters narrow / output is stable / hybrid runs, not semantic relevance (that lives
  in the `slow` e2e tests).
- A skill/asset wiring test should **skip** when the asset is absent (e.g. `.claude/`
  is gitignored) — see `test_docs_sync_skill.py`.
