# Copilot prompt files

Reusable GitHub Copilot prompts, invoked as `/<name>` in Copilot Chat (VS Code).
These are the **Copilot port of the Claude Code skills** — Copilot can't run
Claude's Skill tool, so each skill's behaviour is reproduced as a native prompt
file. Scoped guardrails live alongside in [`../instructions/`](../instructions/);
the persistent ADR persona lives in [`../agents/`](../agents/).

Validity is enforced by `src/tools/scripts/check_copilot.py` (CI): every prompt
needs a `description`, every `sdd-pipeline <cmd>` must be a real command, every
referenced MCP tool must exist, and every link must resolve.

## Ported prompts

| Prompt | Source skill | Drives |
|---|---|---|
| `/doc-to-md` | `doc-to-md` | `sdd-pipeline convert-docx` |
| `/convert-confluence` | (pipeline flagship) | `sdd-pipeline convert` + `lint` |
| `/index-corpus` | (pipeline flagship) | `sdd-pipeline index --lexical` / `export` |
| `/docs-sync` | `docs-sync` | `check_docs.py` + reference pages |
| `/code-review` | `code-review` | the working diff (correctness + guardrails) |
| `/simplify` | `simplify` | quality-only cleanup of the diff |
| `/security-review` | `security-review` | secret/subprocess/SSRF/workspace review |
| `/verify-change` | `verify` | run the real gates + CLI path |
| `/grill-me` | `grill-me` | interview a plan to resolution |
| `/gitlab-mr` | `gitlab-mr-generator` | a GitLab MR description from the branch diff |
| `/copilot-context` | `gh-copilot-context-analyzer` | explain/fix a Copilot `/context` report |

## Intentionally **not** ported (Claude-Code-only)

These skills depend on the Claude Code harness or its plugins and have no faithful
Copilot equivalent — porting them would create broken or misleading prompts:

- Harness control: `loop`, `schedule`, `update-config`, `keybindings-help`,
  `fewer-permission-prompts`, `init`, `setup-cowork`.
- Claude memory / skill tooling: `consolidate-memory`, `skill-creator`, `claude-api`.
- Plugin MCP servers: `claude-crawl:*`, `claude-guard:*`, `understand-anything:*`,
  computer-use / Chrome-driving tools.
- Document-generation skills with bundled scripts (`docx`, `pptx`, `pdf`, `xlsx`)
  ship with the anthropic-skills plugin; use that plugin directly rather than a
  thin re-implementation here.

If Copilot ever gains an equivalent capability, add a prompt here and a row above.
