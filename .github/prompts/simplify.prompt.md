---
mode: agent
description: Quality-only cleanup of the changed code — reuse, simplification, efficiency, altitude — without hunting for bugs. Applies the fixes.
---

# /simplify — clean up the changed code

Review the working diff for **quality only** — reuse, simplification, efficiency,
and altitude — then apply the fixes. Port of the Claude `/simplify` skill. This does
**not** hunt for correctness bugs; use `/code-review` for that.

## Steps

1. **Get the diff** (`git diff origin/main...HEAD`, or `git diff` for uncommitted
   work) and read the changed files for context.
2. **Look for, and fix:**
   - **Reuse** — an existing helper/fixture/protocol already does this (e.g.
     `make_embedder`/`make_vector_store`, the `hashing_embedder` test fixture,
     `header_norm` normalisers). Don't reinvent.
   - **Simplification** — collapse needless branching, comprehensions over manual
     loops, remove dead code and redundant comments.
   - **Efficiency** — avoid re-parsing/re-embedding, hoist invariants, prefer lazy
     imports for optional deps (the codebase imports `chromadb`/`textual`/`mcp`/
     `openai` only when used).
   - **Altitude** — the change sits at the right module layer; CLI-layer concerns
     (`workspace.py`, `shell.py`) stay out of the deterministic core.
3. **Preserve behaviour and guardrails.** Keep module boundaries (see `CLAUDE.md`
   *Architecture guardrails*); keep `structural.py`/`enrichment.py`/`chunking.py`
   deterministic. If a cleanup would cross a boundary, stop and flag it instead.
4. **Apply the fixes**, then run `ruff format src/ tests/ && ruff check src/ tests/`
   and the fast tests (`pytest -m "not slow"`) to confirm nothing regressed.
5. **Report** the edits made and the test result.

## Notes

- Match the surrounding style; don't restructure beyond the cleanup.
- If a simplification changes observable behaviour, it belongs in `/code-review`, not
  here — surface it rather than applying it silently.
