# Implementing the Grounding step (with the harness you have)

The **Grounding Brief** is the read-only "what already exists" note that the Specifier reads
before writing the spec. Good news: **most of it already exists in this repo** — you're mostly
wiring + a template, not building from scratch. Plain English; the technical bits are ready for a
developer. Bold words are in the [glossary](glossary.md).

## What you already have (reuse it)

- **A semantic-search MCP server — `sdd-semantic`** — already wired in `.vscode/mcp.json`. It
  searches your **docs / ADRs / SAD** by meaning, with tools like `semantic_search` and
  `find_decision_context` (grouped context for a decision). *This is the grounding search engine.*
- **A read-only grounding agent — `corpus-researcher`** (`.github/agents/corpus-researcher.agent.md`)
  — a **retrieve → assess → refine** loop that returns a grounding pack and honestly reports gaps.
  *This is a grounding agent already* — adapt it to emit the Brief.
- **Copilot reads your code** natively (VS Code / CLI). So: **Copilot for the code + the MCP
  server for the docs/decisions = a full brief** for existing (brownfield) code.

## 1. What the Grounding Brief looks like (the output)

A short read-only document. A template to drop in `templates/grounding-brief.md`:

```
# Grounding Brief — <topic>
## System map          the parts involved and how they connect
## Key files / endpoints   e.g. GET /orders -> handler, DB query, tests
## Current behavior     what it does today
## Constraints          auth, data, patterns to follow
## Unknowns & assumptions   each tagged: observed / inferred / assumed
## Coverage: COMPLETE | INCOMPLETE   (+ what's missing, if incomplete)
```

The tags (observed / inferred / assumed) and the honest **Coverage** line are what keep it
trustworthy — it says what it *knows* vs *guessed*.

## 2. Three ways to run it — pick by how hands-on you want to be

### A. In VS Code with Copilot (simplest — start here)
- Open the repo. In Copilot **agent mode / Chat**, pick the grounding agent.
- It uses **read** tools + the **`sdd-semantic` MCP server** to search the docs, and reads the
  code, then writes `grounding-brief.md`. You eyeball it. Fully human-steered — no CI needed.

### B. Headless in GitLab CI with the Copilot CLI (automated on every Issue)
A CI job runs the Copilot CLI **non-interactively** with a **read-only tool list**, then posts the
brief as an Issue/MR note. Sketch (flags are illustrative — the point is a *read-only allow-list*):

```yaml
grounding:
  stage: ground
  script:
    - copilot -p "Produce a Grounding Brief for issue $CI_ISSUE_IID using the grounding agent"
        --allow-tool read --allow-tool search --deny-tool write
    - glab issue note "$CI_ISSUE_IID" -m "$(cat grounding-brief.md)"
```

The **`--deny-tool write`** (no edit/commit tools) is what makes the worker read-only.

### C. GitLab Duo (if you're licensed for it)
Use **Duo Chat / Duo Agent** with repo context to draft the brief and drop it as an MR/issue
note. Same output, GitLab-native worker.

## 3. Keep it read-only (the enforcement — software, not trust)

- **Copilot CLI:** deny write/edit tools in the allow-list — it can **search and read, not
  change** anything.
- **GitLab:** give the grounding job's token **no push rights to protected branches** — at most it
  writes the brief to a scratch note or branch. It **cannot touch product code.**
- The brief itself changes nothing — it's just notes for the Specifier.

## 4. When it can't find enough

The agent ends with **`Coverage: INCOMPLETE`** + a list of gaps → that's an **escalate**: a human
decides *proceed / narrow the scope / add the missing docs*. A loud "I don't know these parts" is
better than a confident guess.

## Recommended for you

1. **Start with A** — VS Code Copilot + the `sdd-semantic` MCP server + the `corpus-researcher`
   agent. It reuses what's already here and needs **zero** CI work.
2. **Move the same agent to B** (a GitLab CI job with the Copilot CLI) when you want the brief
   produced **automatically on every Issue**.
3. **Swap to C** (Duo) if you standardize on GitLab Duo.

*Where this fits in the flow: it's step 2 in [synergy-walkthrough.md](synergy-walkthrough.md) —
the Brief is the **baton** the Specifier reads next.*
