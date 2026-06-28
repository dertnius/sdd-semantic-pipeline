---
agent: agent
model: Claude Sonnet 4.6
description: Verify a change actually works by running the real commands — fast tests, lint/format, type-check, and the relevant sdd-pipeline CLI path — then report proof.
---

# /verify-change — prove the change works

Verify that a change does what it should by **running** it, not by reading it. Port
of the Claude `/verify` skill, adapted to this repo's commands.

## Steps

1. **Scope it.** From the diff, decide what to exercise: a pure-core change → fast
   tests; a CLI change → run the command; a docs change → the doc-health battery.
2. **Run the deterministic gates** (from the repo root, project venv):

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -m "not slow"
   .\.venv\Scripts\python.exe -m ruff format --check src/ tests/
   .\.venv\Scripts\python.exe -m ruff check src/ tests/
   .\.venv\Scripts\python.exe -m mypy src/
   ```

   For docs changes also run `src/tools/scripts/check_docs.py`; for Copilot-asset
   changes run `src/tools/scripts/check_copilot.py`.

3. **Exercise the real path** when behaviour changed. Examples:
   - converter: `sdd-pipeline convert` then `sdd-pipeline lint outbox/md --strict`
   - index/search: `sdd-pipeline index outbox/md --lexical` then
     `sdd-pipeline search "..." --lexical`
   - environment probe: `sdd-pipeline check`
4. **Slow lane only when needed.** The full suite (`pytest`) needs pandoc on PATH and
   downloads a model on first run — run it when the change touches pandoc/model paths
   or before a release.
5. **Report proof** — paste the passing/failing output. If something fails, say so
   with the output and diagnose; never claim success blind.

## Notes

- Default to the **fast lane** while iterating; reserve `slow`/`integration` for
  pandoc- or model-dependent paths.
- Inject the `hashing_embedder` fixture to exercise index→search **without** a model
  in the fast lane (see `tests/test_search_offline.py`).
