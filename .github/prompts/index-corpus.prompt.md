---
mode: agent
description: Build the local search index so Copilot's sdd-semantic MCP server can RAG over the corpus (model-free lexical by default).
---

# /index-corpus — build the index the MCP server searches

The `sdd-semantic` MCP server (registered in `.vscode/mcp.json`, consumed by the
ADR Generator agent) searches an **already-built** index. If
`semantic_search`/`find_decision_context` return an empty-index error, build one
with this prompt. The default is **model-free lexical** — no embedding model is
downloaded, every language works.

## Steps

1. **Have Markdown in `outbox/md/`.** If you only have raw HTML/docx, run
   `/convert-confluence` and/or `/doc-to-md` first.
2. **Build a model-free lexical index** (matches the `--lexical` MCP server in
   `.vscode/mcp.json`):

   ```powershell
   $env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe -m sdd_pipeline.cli index outbox/md --lexical --lang auto
   ```

   The index lands in `outbox/index/` (the persist dir the MCP server reads).

3. **(Optional) export portable chunks** for other pipelines — pandoc-only, no model:

   ```powershell
   .\.venv\Scripts\python.exe -m sdd_pipeline.cli export outbox/md --lang auto
   ```

4. **(Optional) semantic index** — dense vectors need a model. Local
   sentence-transformers (`--model all-MiniLM-L6-v2` is the small dev model) or the
   Azure provider (`--provider azure`, credentials via `PIPELINE_AZURE_OPENAI_*` env
   only). A semantic-built index must be searched with the matching provider/model —
   provenance is verified and mismatch raises.

5. **Verify retrieval.** Confirm the index answers:

   ```powershell
   .\.venv\Scripts\python.exe -m sdd_pipeline.cli search "your query" --lexical
   ```

   Then the ADR Generator agent's `find_decision_context(topic)` and
   `semantic_search(query)` calls will return grounded results.

## Notes

- The MCP server in `.vscode/mcp.json` runs in **lexical** mode and reads
  `outbox/index/` with the `memory` backend — keep the build aligned (`--lexical`).
- `sdd-pipeline check` reports whether pandoc, the model deps, and the MCP extra are
  available.
