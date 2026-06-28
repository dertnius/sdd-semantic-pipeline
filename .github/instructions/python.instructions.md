---
applyTo: "src/sdd_pipeline/**/*.py"
description: Architecture guardrails for the sdd_pipeline core — module boundaries, determinism, lazy optional deps, ASCII-on-Windows.
---

# Python core guardrails

These rules apply to `src/sdd_pipeline/**`. They mirror `CLAUDE.md`
*Architecture guardrails* — preserve the boundaries unless the user explicitly asks
otherwise; if a request seems to require breaking one, flag the conflict and confirm
first.

## Module boundaries (do not cross)

- `models.py` stays **pure data contracts** — no service logic, no external deps.
- `vector_store.py` is the **only** module touching vector-store backends
  (langchain-core `InMemoryVectorStore`, ChromaDB) — selected by `make_vector_store`.
- `embeddings.py` is the **only** module loading an embedding backend
  (sentence-transformers / Azure OpenAI) — selected by `make_embedder`.
- `ast_parser.py` is the **only** module invoking pandoc (flow A).
- `structural.py`, `enrichment.py`, `chunking.py` stay **deterministic and
  unit-testable** — same input → same output, no I/O, no model.
- `workspace.py` (inbox/outbox guard) and `shell.py` (pwsh discovery) are
  **CLI-layer only** — imported by `cli.py`/`dump.py`, never wired into the core.
- The `convert/` subpackage is independent of flow A; importing it must not pull in
  flow A modules.

## Conventions

- **Optional deps are lazy-imported** — `chromadb`, `textual`, `mcp`, `openai`,
  `langdetect`, spaCy are imported inside the function/command that uses them, so
  core flows work without them installed.
- **A new `PipelineConfig` field** must be added to **both** pydantic-settings v2 and
  the v1 fallback branch in `config.py`, **and** documented in
  `docs/reference/configuration.md` (the doc-health gate enforces both).
- **A new CLI command/flag** must be documented in `docs/reference/cli.md`.
- **Changing `SemanticChunk.to_embed_text` composition** requires bumping
  `EMBED_FORMAT_VERSION` in `models.py` in the same change.
- **Vector-store metadata must be scalar** (`str|int|float|bool`); JSON-encode lists.
- **Windows console is cp1252** — keep `convert`/`mcp`/diagnostic stdout ASCII-only;
  pin subprocess decoding to UTF-8.
- Style: ruff, line-length 100, double quotes, py311 target. Type-annotate new code.

## Tests

Behaviour changes ship with tests. Mark anything needing pandoc or a real model as
`slow`; prefer mocks/`hashing_embedder` for the fast lane.
