---
applyTo: ".github/prompts/**,.github/agents/**,.github/instructions/**,.vscode/mcp.json,.claude/skills/**"
description: Conventions for the agent assets (Copilot integration + portable Agent Skills), enforced by check_copilot.py — frontmatter, real command/tool references, resolvable links.
---

# Agent asset conventions

These rules apply to the agent-asset surface — the Copilot integration
(`.github/prompts/`, `.github/agents/`, `.github/instructions/`, `.vscode/mcp.json`)
**and** the portable Agent Skills (`.claude/skills/*/SKILL.md`, read by both Claude Code
and Copilot). They are enforced by `src/tools/scripts/check_copilot.py` (CI) — keep them
valid so a broken asset can't merge.

## Frontmatter (required)

- **Agent Skills** (`.claude/skills/<name>/SKILL.md`): `name` (lowercase letters/digits/
  hyphens, no leading/trailing/double hyphen, ≤64 chars, **matching the directory**) and
  a non-empty `description` (≤1024 chars, stating *what* + *when*). The single source of
  truth for a project skill — author here, not as a `.github/prompts/` port. Invoked as
  `/<name>` in both Claude Code and Copilot.
- **Prompt files** (`*.prompt.md`): a non-empty `description`. Recommended: `mode`
  (`agent` for command-driving tasks, `ask` for advisory ones). Invoked as `/<name>`.
  Use a prompt only for Copilot-only behaviour with no `.claude/skills/` equivalent.
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

## Adding a new skill (preferred)

1. Create `.claude/skills/<name>/SKILL.md` with spec-valid frontmatter + body (bundle
   `scripts/`/`references/`/`assets/` as needed). `<name>` must match the directory.
2. Run `python src/tools/scripts/check_copilot.py` until green.
3. Both Claude Code and Copilot pick it up as `/<name>` — no port needed.

## Adding a new prompt (Copilot-only)

Only when the behaviour has no `.claude/skills/` equivalent (e.g. it ports a Claude
**bundled/plugin** skill Claude Code already has built-in):

1. Create `.github/prompts/<name>.prompt.md` with frontmatter + body.
2. Add a row to `.github/prompts/README.md`.
3. Run `python src/tools/scripts/check_copilot.py` until green.
4. Keep the ported behaviour faithful and note the source skill.
