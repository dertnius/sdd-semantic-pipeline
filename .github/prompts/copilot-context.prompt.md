---
agent: ask
description: Explain a Copilot /context report and diagnose why Copilot may be missing files, then give concrete fixes to improve its awareness of this codebase.
---

# /copilot-context — analyse Copilot's /context

Port of the `gh-copilot-context-analyzer` skill. Use when the user pastes the output
of typing `/context` inside a Copilot chat session, or asks why Copilot doesn't know
about a file. Explain what Copilot is reading and how to widen its awareness.

## How to run it

1. **Read the pasted `/context` report.** Identify what's in context: open files,
   attached files, instruction files applied, workspace index status, and what's
   *missing* that the user expected.
2. **Explain each field** in plain terms — what it means and whether it's healthy.
3. **Diagnose gaps.** Common causes in this repo and their fixes:
   - **Source not indexed** → `.vscode/settings.json` sets
     `github.copilot.advanced.workspaceContext.includePatterns` to `src/**`,
     `tests/**`, `docs/**`. Confirm the file matches; add a pattern if not.
   - **Instructions not applied** → scoped guardrails live in
     `.github/instructions/*.instructions.md` with `applyTo` globs; repo-wide rules
     in `.github/copilot-instructions.md`. Check the file's path matches an
     `applyTo`, and that `chat.promptFiles` / use-instruction-files settings are on.
   - **Prompt not found** → reusable prompts live in `.github/prompts/*.prompt.md`,
     invoked as `/<name>`. Confirm the file is there and `chat.promptFiles` is
     enabled.
   - **MCP retrieval empty** → the `sdd-semantic` server needs a built index; run
     `/index-corpus`.
4. **Give an action list** — the smallest set of changes to get the missing context
   in, ordered by impact.

## Notes

- This explains/advises; it doesn't change settings unless the user asks.
- Copilot's workspace index, instruction files, and prompt files are all configured
  in this repo already — usually the fix is matching a path to an existing pattern,
  not adding new config.
