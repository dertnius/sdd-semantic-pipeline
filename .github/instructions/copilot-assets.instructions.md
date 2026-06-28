---
applyTo: ".github/prompts/**,.github/agents/**,.github/instructions/**,.vscode/mcp.json"
description: Conventions for the Copilot integration assets, enforced by check_copilot.py — frontmatter, real command/tool references, resolvable links.
---

# Copilot asset conventions

These rules apply to the Copilot integration surface
(`.github/prompts/`, `.github/agents/`, `.github/instructions/`, `.vscode/mcp.json`).
They are enforced by `src/tools/scripts/check_copilot.py` (CI) — keep them valid so a
broken asset can't merge.

## Frontmatter (required)

- **Prompt files** (`*.prompt.md`): a non-empty `description`. Recommended: `mode`
  (`agent` for command-driving tasks, `ask` for advisory ones). Invoked as `/<name>`.
- **Agent files** (`*.agent.md`): non-empty `name` **and** `description`.
- **Instruction files** (`*.instructions.md`): a non-empty `applyTo` glob (the files
  the guardrails auto-apply to). Comma-separate multiple globs.

## References must resolve

- Every `sdd-pipeline <cmd>` (or `python -m sdd_pipeline.cli <cmd>`) in a code span
  must be a **real registered CLI command**. Run `sdd-pipeline help` to see the list;
  don't invent commands.
- Every MCP tool referenced in call form (`tool_name(...)`) must be one the
  `sdd-semantic` server actually exposes: `semantic_search`, `find_decision_context`,
  `find_sad_coverage`, `list_section_types`, `list_spaces`
  (see `src/sdd_pipeline/mcp_server.py`).
- `.vscode/mcp.json` must register the `sdd-semantic` stdio server whose args invoke a
  real CLI command (`mcp`).
- Every relative markdown link / source-file link must resolve on disk.

## Adding a new prompt

1. Create `.github/prompts/<name>.prompt.md` with frontmatter + body.
2. Add a row to `.github/prompts/README.md`.
3. Run `python src/tools/scripts/check_copilot.py` until green.
4. If it ports a Claude skill, keep the behaviour faithful and note the source skill.
