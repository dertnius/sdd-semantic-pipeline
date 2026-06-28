---
mode: agent
description: Review the current branch diff for correctness bugs plus reuse/simplification/efficiency cleanups, respecting this repo's architecture guardrails.
---

# /code-review — review the working diff

Review the changes on the current branch (diff against `origin/main`) for
**correctness** first, then **quality** (reuse, simplification, efficiency). Port of
the Claude `/code-review` skill, adapted to this repo's guardrails.

## Steps

1. **Get the diff.** Prefer `git diff origin/main...HEAD`; fall back to
   `git diff` for uncommitted work. Read the changed files in full for context, not
   just the hunks.
2. **Correctness pass.** Look for: logic errors, off-by-one, wrong/missing edge
   cases, broken determinism (the core must stay deterministic), swallowed errors,
   mutated shared state, resource leaks, and **non-ASCII output on Windows paths**
   (cp1252 crashes when stdout is redirected — see `CLAUDE.md` *Known pitfalls*).
3. **Guardrail pass.** Flag any change that breaks a module boundary:
   - `models.py` must stay pure data contracts (no service logic).
   - `vector_store.py` is the only vector-store-backend module; `embeddings.py` the
     only embedding-loader; `ast_parser.py` the only pandoc caller (flow A).
   - `structural.py` / `enrichment.py` / `chunking.py` must stay deterministic.
   - `workspace.py` / `shell.py` are CLI-layer only — never wired into the core.
   - A new `PipelineConfig` field must be in **both** v2/v1 branches **and**
     `docs/reference/configuration.md`; a new CLI command/flag in
     `docs/reference/cli.md`. `to_embed_text` changes must bump `EMBED_FORMAT_VERSION`.
4. **Quality pass.** Reuse existing helpers/fixtures, simplify, remove dead code,
   match surrounding style (ruff: line-length 100, double quotes, py311).
5. **Report.** Group findings by severity (correctness > guardrail > quality). For
   each: `file:line`, what's wrong, why it matters, and a concrete fix. Note when a
   change needs an added/updated test.

## Notes

- This is a **review**, not an edit — propose fixes, don't apply them unless asked.
- Tests for changed behaviour are expected; call out missing coverage.
- Mark tests needing pandoc or a real model as `slow`.
