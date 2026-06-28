# GitHub Copilot integration

The workflows that drive this pipeline are available whether you work with Claude Code
or Copilot in VS Code. **Project-specific skills are authored once as portable
`SKILL.md` folders under `.claude/skills/`** — the [Agent Skills](https://agentskills.io)
open standard, read **natively** by both Claude Code and Copilot (`.claude/skills/` is the
one project directory both tools discover). That subtree is the **single source of truth**
for our skills and the one tracked exception to the otherwise-gitignored `.claude/`.

The remaining `.github/` assets are the things with **no** `.claude/skills/` equivalent:
Copilot-only **prompt files** porting Claude's bundled/plugin skills (Claude Code has
those built-in), the architecture guardrails as scoped **instruction files**, and the
ADR persona as a custom **agent**.

## Agent Skills — portable, dual-read

Project-specific skills live as `SKILL.md` folders under `.claude/skills/` and are
invoked as `/<name>` in **both** Claude Code and Copilot Chat:

| Skill | Drives |
|---|---|
| `/doc-to-md` | `sdd-pipeline convert-docx` (Word → Markdown) |
| `/docs-sync` | the doc-health battery + the reference pages |

A skill is a folder with a `SKILL.md` (YAML frontmatter — `name` + `description` — plus
markdown instructions and optional `scripts/`/`references/`/`assets/`). Authoring it once
means every skills-compatible agent (Claude Code, Copilot, Cursor, Codex, …) gets it from
one source; no hand-port to keep in sync.

## Prompt files — Copilot-only ports

Reusable prompts live in `.github/prompts/*.prompt.md` and are invoked as `/<name>` in
Copilot Chat. These have **no** `.claude/skills/` equivalent — they port Claude's
**bundled/plugin** skills (Claude Code has those built-in) plus two pipeline-flagship
workflows:

| Prompt | Source skill | Drives |
|---|---|---|
| `/convert-confluence` | pipeline flagship | `sdd-pipeline convert` + `lint` (Confluence HTML → Markdown) |
| `/index-corpus` | pipeline flagship | `sdd-pipeline index --lexical` / `export` (build the index the MCP server searches) |
| `/code-review` | `code-review` | the working diff — correctness + guardrails |
| `/simplify` | `simplify` | quality-only cleanup of the diff |
| `/security-review` | `security-review` | secret / subprocess / SSRF / workspace review |
| `/verify-change` | `verify` | run the real gates + CLI path |
| `/grill-me` | `grill-me` | interview a plan to resolution |
| `/gitlab-mr` | `gitlab-mr-generator` | a GitLab MR description from the branch diff |
| `/copilot-context` | `gh-copilot-context-analyzer` | explain / fix a Copilot `/context` report |

`.github/prompts/README.md` lists these and the Claude-Code-only skills that are
deliberately **not** ported (harness control, plugin MCP servers, computer-use, etc.).

## Instruction files — scoped guardrails

`.github/instructions/*.instructions.md` carry an `applyTo` glob, so Copilot
auto-applies the right guardrails to the file you're editing:

- `python.instructions.md` (`src/sdd_pipeline/**`) — module boundaries, determinism,
  lazy optional deps, ASCII-on-Windows, the dual config branches + `EMBED_FORMAT_VERSION`.
- `tests.instructions.md` (`tests/**`) — markers (`slow`/`integration`), shared
  fixtures, the model-free fast lane (`hashing_embedder`).
- `docs.instructions.md` (`docs/**`, `mkdocs.yml`, `README.md`, `CLAUDE.md`) — keep
  [the CLI](../reference/cli.md) and [configuration](../reference/configuration.md)
  references authoritative; run the doc-health battery.
- `copilot-assets.instructions.md` (`.github/prompts/**`, `/agents/**`,
  `/instructions/**`, `.vscode/mcp.json`, `.claude/skills/**`) — the conventions the
  gate below enforces.

Repo-wide rules (always on) stay in `.github/copilot-instructions.md`; the ADR
Generator persona is `.github/agents/adr-generator.agent.md`, which grounds ADRs via
the `sdd-semantic` MCP server registered in `.vscode/mcp.json`. Build an index first
with `/index-corpus` so its retrieval returns results.

## The guardrail gate

`src/tools/scripts/check_copilot.py` is a deterministic, model-free battery (the
sibling of `check_docs.py`) that keeps the Copilot assets honest:

| Check | Asserts |
|---|---|
| C1 frontmatter | prompts have a `description`; agents `name` + `description` (and any `agents:` refs resolve); instructions `applyTo` |
| C2 CLI refs | every `sdd-pipeline <cmd>` in a code span is a real registered command |
| C3 MCP wiring | `.vscode/mcp.json` invokes a real command; every referenced MCP tool (`tool_name(...)`) exists |
| C4 links | relative markdown / source-file links resolve |
| C5 well-formed | balanced code fences + closed YAML frontmatter |
| C6 skills | every `.claude/skills/*/SKILL.md` has spec-valid frontmatter (`name` matches its dir + grammar/length; `description` ≤1024 chars) |

C2/C4/C5 cover the `.claude/skills/` bodies too, so a skill referencing a non-existent
CLI command, a broken link, or an unbalanced fence also fails the gate.

Run it locally:

```powershell
.\.venv\Scripts\python.exe src/tools/scripts/check_copilot.py
```

It runs in CI on both hosts — the GitLab `verify:quality` stage and the GitHub
`copilot-health` workflow — so a broken Copilot asset can't merge. The gate is itself
self-tested by `tests/test_check_copilot.py`.

## Enabling discovery in VS Code

`.vscode/settings.json` already enables skill, prompt-file, and instruction-file
discovery (`chat.agentSkillsLocations` → `.claude/skills`, `chat.promptFiles`,
`chat.promptFilesLocations`, `chat.instructionsFilesLocations`,
`github.copilot.chat.codeGeneration.useInstructionFiles`). Open Copilot Chat and type
`/` to see the skills and prompts; the instruction files apply automatically by
`applyTo` glob.

See the [Pipeline 101 runbook](pipeline-101.md) for the underlying CLI workflow the
prompts drive.
