# GitHub Copilot integration

The Claude Code skills that drive this pipeline are **ported to GitHub Copilot** as
native assets, so the same workflows are available whether you work with Claude Code
or Copilot in VS Code. Copilot can't run Claude's Skill tool, so each skill's
behaviour is reproduced as a Copilot **prompt file**, the architecture guardrails as
scoped **instruction files**, and the ADR persona as a custom **agent** — all under
`.github/` (which is tracked, unlike the gitignored `.claude/`).

## Prompt files — the ported skills

Reusable prompts live in `.github/prompts/*.prompt.md` and are invoked as `/<name>`
in Copilot Chat. Each is a faithful port of a Claude skill, adapted to this repo:

| Prompt | Source skill | Drives |
|---|---|---|
| `/doc-to-md` | `doc-to-md` | `sdd-pipeline convert-docx` (Word → Markdown) |
| `/convert-confluence` | pipeline flagship | `sdd-pipeline convert` + `lint` (Confluence HTML → Markdown) |
| `/index-corpus` | pipeline flagship | `sdd-pipeline index --lexical` / `export` (build the index the MCP server searches) |
| `/docs-sync` | `docs-sync` | the doc-health battery + the reference pages |
| `/code-review` | `code-review` | the working diff — correctness + guardrails |
| `/simplify` | `simplify` | quality-only cleanup of the diff |
| `/security-review` | `security-review` | secret / subprocess / SSRF / workspace review |
| `/verify-change` | `verify` | run the real gates + CLI path |
| `/grill-me` | `grill-me` | interview a plan to resolution |
| `/gitlab-mr` | `gitlab-mr-generator` | a GitLab MR description from the branch diff |
| `/copilot-context` | `gh-copilot-context-analyzer` | explain / fix a Copilot `/context` report |

`.github/prompts/README.md` lists the port and the Claude-Code-only skills that are
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
  `/instructions/**`, `.vscode/mcp.json`) — the conventions the gate below enforces.

Repo-wide rules (always on) stay in `.github/copilot-instructions.md`; the ADR
Generator persona is `.github/agents/adr-generator.agent.md`, which grounds ADRs via
the `sdd-semantic` MCP server registered in `.vscode/mcp.json`. Build an index first
with `/index-corpus` so its retrieval returns results.

## The guardrail gate

`src/tools/scripts/check_copilot.py` is a deterministic, model-free battery (the
sibling of `check_docs.py`) that keeps the Copilot assets honest:

| Check | Asserts |
|---|---|
| C1 frontmatter | prompts have a `description`; agents `name` + `description`; instructions `applyTo` |
| C2 CLI refs | every `sdd-pipeline <cmd>` in a code span is a real registered command |
| C3 MCP wiring | `.vscode/mcp.json` invokes a real command; every referenced MCP tool (`tool_name(...)`) exists |
| C4 links | relative markdown / source-file links resolve |
| C5 well-formed | balanced code fences + closed YAML frontmatter |

Run it locally:

```powershell
.\.venv\Scripts\python.exe src/tools/scripts/check_copilot.py
```

It runs in CI on both hosts — the GitLab `verify:quality` stage and the GitHub
`copilot-health` workflow — so a broken Copilot asset can't merge. The gate is itself
self-tested by `tests/test_check_copilot.py`.

## Enabling discovery in VS Code

`.vscode/settings.json` already enables prompt-file and instruction-file discovery
(`chat.promptFiles`, `chat.promptFilesLocations`, `chat.instructionsFilesLocations`,
`github.copilot.chat.codeGeneration.useInstructionFiles`). Open Copilot Chat and type
`/` to see the prompts; the instruction files apply automatically by `applyTo` glob.

See the [Pipeline 101 runbook](pipeline-101.md) for the underlying CLI workflow the
prompts drive.
