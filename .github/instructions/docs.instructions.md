---
applyTo: "docs/**/*.md,mkdocs.yml,README.md,CLAUDE.md"
description: Documentation rules — keep cli.md/configuration.md authoritative, run the doc-health battery, no broken links, MkDocs builds strict.
---

# Documentation rules

These rules apply to the docs sources (`docs/**`, `mkdocs.yml`, `README.md`,
`CLAUDE.md`). The docs are the single source of truth for humans; the code is the
single source of truth for behaviour.

- **The authoritative references** are `docs/reference/cli.md` (one `##` section per
  command, every long `--flag` documented) and `docs/reference/configuration.md`
  (one row per `PIPELINE_*` setting, plus the install-extras table). `README.md` and
  `CLAUDE.md` **link** to these — they don't duplicate the tables.
- **When you add/change a CLI command or flag, or a `PipelineConfig` field, update the
  matching reference page in the same change.** The doc-health gate
  (`src/tools/scripts/check_docs.py`) blocks the merge otherwise.
- **Run the battery before claiming docs are done:**
  `python src/tools/scripts/check_docs.py` (deterministic, model-free) then
  `mkdocs build --strict` (needs the `[docs]` extra; checks nav/render/orphans).
- **No broken links.** Intra-docs and source-file links must resolve. Don't link into
  the generated `outbox/` zone or `.claude/` (intentionally out of the gate).
- **New page → add it to `nav` in `mkdocs.yml`** (an orphan page fails
  `--strict`), or to `exclude_docs` if it's history/ingest material.
- **`learn/` citations** use the `module.py::symbol` convention and are tracked in the
  freshness table in `docs/learn/README.md` — keep both in sync when code moves.
- **Log doc changes** in `docs/guides/log.md`
  (`## YYYY-MM-DD | docs-sync | <what changed>`).
- The interactive fix-it pass is the `/docs-sync` skill (`.claude/skills/docs-sync/`);
  the enforced guarantee is `check_docs.py` + CI.
