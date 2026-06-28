---
mode: agent
description: Reconcile docs with code after a change — run the deterministic doc-health battery, then fix the CLI/config reference pages, citations, CLAUDE.md and the changelog.
---

# /docs-sync — keep the docs aligned with the code

Port of the Claude `docs-sync` skill. The docs are the single source of truth for
humans; the code is the single source of truth for behaviour. This prompt reconciles
the two. The deterministic gate is `src/tools/scripts/check_docs.py` (run in CI);
this is the **interactive fix-it pass** that resolves what it reports and updates the
prose the gate can't see.

## Procedure

1. **Run the battery** from the repo root:

   ```powershell
   .\.venv\Scripts\python.exe src/tools/scripts/check_docs.py
   ```

   It reports two intents — *not broken* (B1/B2 links, B4 well-formedness) and
   *updated* (U1 CLI commands, U2 flags, U3 settings, U4 extras, U5 learn citations).
   Read every reported issue; each names the file and the drift.

2. **CLI surface → `docs/reference/cli.md`** (U1/U2). Diff the live CLI against the
   page (`sdd-pipeline help`, `sdd-pipeline <cmd> --help`). One `## <command>`
   section per command (heading == exact command name); document every long `--flag`.

3. **Config surface → `docs/reference/configuration.md`** (U3/U4). Add the
   `PIPELINE_<FIELD>` row for each new `PipelineConfig` field (remember the **dual
   v2/v1 branches** in `config.py`); sync the extras table with `pyproject.toml`.

4. **learn/ citations** (U5). A cited `module.py::symbol` moved/renamed — update the
   citation and the freshness table in `docs/learn/README.md`.

5. **Broken links** (B1/B2). Repoint or remove the dead target. Don't add links into
   the generated `outbox/` zone or `.claude/` (intentionally out of the gate).

6. **Reconcile the prose the gate can't see.** Update `CLAUDE.md` (module map +
   subsystem notes) and the `README.md` CLI section; both should *link* to the
   reference pages, not duplicate the tables.

7. **Log it.** Append a dated entry to `docs/guides/log.md`
   (`## YYYY-MM-DD | docs-sync | <what changed>`).

8. **Re-run until green**, then `mkdocs build --strict` (needs the `[docs]` extra) to
   confirm nav/render. Report the files changed and any residual drift.

## Notes

- The battery is **deterministic and model-free** — trust its output.
- Don't disable a check to make it pass — fix the doc or the code.
- A new CLI command or `PipelineConfig` field is **not done** until `cli.md` /
  `configuration.md` document it — the gate (and CI) block the merge otherwise.
