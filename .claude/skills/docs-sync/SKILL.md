---
name: docs-sync
description: Reconcile the docs with the code after a change. Use when the user says "sync the docs", "the docs are stale", "I added/renamed a CLI command or flag", "update the docs for my change", "check the docs", or after editing src/sdd_pipeline. Runs the deterministic doc-health battery, then updates the CLI/config reference pages, the learn/ citations, CLAUDE.md, and the docs changelog so the docs are not broken and up to date.
---

# docs-sync — keep the docs aligned with the code

The docs are the single source of truth for humans; the code is the single source of
truth for behaviour. This skill reconciles the two after a change. The deterministic
gate is `src/tools/scripts/check_docs.py` (run in CI); this skill is the **interactive
fix-it pass** that resolves what the gate reports and updates the prose the gate can't.

`.claude/` is gitignored, so this skill is a **local helper** — the tracked, enforceable
guarantee is `check_docs.py` + the CI `verify` stage. Use the project venv
(`.\.venv\Scripts\python.exe`) and run from the repo root.

## Procedure

1. **Run the battery — see what's broken or stale.**
   ```powershell
   .\.venv\Scripts\python.exe src/tools/scripts/check_docs.py
   ```
   It reports two intents: *not broken* (B1/B2 links, B4 well-formedness) and *updated*
   (U1 CLI commands, U2 flags, U3 settings, U4 extras, U5 learn citations). Read every
   reported issue — each names the file and the drift.

2. **CLI surface → `docs/reference/cli.md`.** For any U1/U2 issue, diff the live CLI
   against the page:
   ```powershell
   .\.venv\Scripts\python.exe -m sdd_pipeline.cli help          # the command list
   .\.venv\Scripts\python.exe -m sdd_pipeline.cli <cmd> --help  # one command's flags
   ```
   Add a `## <command>` section (heading text == exact command name) for a new command,
   or add/rename the flag row in that command's table. Keep one `##` per command and
   document every long `--flag`.

3. **Config surface → `docs/reference/configuration.md`.** For any U3 issue, add the
   `PIPELINE_<FIELD>` row (env name = `PIPELINE_` + the upper-cased `PipelineConfig`
   field). Remember the **dual v2/v1 branches** in `config.py`. For U4, sync the extras
   table with `pyproject.toml`'s `[project.optional-dependencies]`.

4. **learn/ citations → fix stale `module.py::symbol`.** For any U5 issue, the cited
   module moved or was renamed. Use the freshness table in `docs/learn/README.md` to
   find the page(s) citing it, grep `docs/learn/` for the old symbol, and update both
   the citation and the freshness table.

5. **Broken links (B1/B2).** Repoint or remove the dead `[text](target)` / image. Links
   into the generated `outbox/` zone and `.claude/` are intentionally not in the gate —
   don't add new ones.

6. **Reconcile the prose the gate can't see.** Update `CLAUDE.md` (the module map +
   subsystem notes) and the `README.md` CLI section if the change adds a subsystem or
   command; both should *link* to the reference pages, not duplicate the tables.

7. **Log it.** Append a dated entry to `docs/guides/log.md`
   (`## YYYY-MM-DD | docs-sync | <what changed>`).

8. **Re-run the battery until green**, then `mkdocs build --strict` (needs the `[docs]`
   extra) to confirm nav/render. Report the files changed and any residual drift.

## Notes

- The battery is **deterministic and model-free** — trust its output; if it's green and
  the prose is reconciled, the docs are aligned.
- Don't disable a check to make it pass — fix the doc or the code. A genuinely
  intentional exception belongs in `check_docs.py` with a comment, not silenced ad hoc.
- New CLI command or `PipelineConfig` field? It is *not done* until `cli.md` /
  `configuration.md` document it — the gate (and CI) will block the merge otherwise.
