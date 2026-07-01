# How the tools work together (synergy) — who plays what role

Plain English. You don't pick **one** tool — each fills a different **slot**, and you can mix
them. Bold words are in the [glossary](glossary.md).

## The one idea: two layers, filled separately

There are two jobs to fill:

- **The worker** — the AI that does the thinking (drafts the spec, writes the code, suggests
  fixes).
- **The gate + spine** — the platform that runs the fixed steps and **enforces the rules**
  (**GitHub** or **GitLab**).

You choose the **worker** and the **gate** *separately* — and you can use more than one worker.
That's the whole synergy.

> **Handy fact:** the GitHub Copilot **cloud coding agent** (the one that auto-opens PRs) is
> GitHub-only. But **VS Code Copilot** and the **Copilot CLI** work on *any* repo you have
> locally — **including a GitLab one** — so they can be your worker while **GitLab** does the
> enforcing.

## What each surface is best at

| Surface | Layer | Best role | Why |
|---|---|---|---|
| **VS Code GitHub Copilot** (the IDE) | worker **+ the human's seat** | **The cockpit** — where a person drafts and steers agents interactively, reads the diff, and clicks **approve**. Runs the grounding **MCP server** right in the editor and picks the per-stage custom agents. | It's interactive and **human-in-the-loop-friendly** — ideal for the two 🙋 approvals and for stages a human wants to steer (drafting the spec, reviewing). |
| **GitHub Copilot CLI** (terminal) | worker (**headless**) | **The automated worker in CI** — runs one stage with a tight **tool allow-list** and opens a **draft** change. | Scriptable and non-interactive; its allow-list *is* the **toolbox** that natively locks "only the Builder writes code." Great for the Builder/Grounding stages when no human is driving. |
| **GitLab + Duo** | worker **and** gate | **All-in-one if you live on GitLab** — Duo drafts/writes (Issue→MR); GitLab CI + approval rules + scanners enforce. | One ecosystem: the AI works **and** the platform enforces, no GitHub needed (needs a Duo licence). |
| **GitLab without Duo** | **gate + spine only** (no AI) | **The strongest enforcement layer — bring your own AI worker.** GitLab CI (spine) + MR approval rules (**"prevent approval by author"**) + native **security scanners/policies** (un-skippable). | Pair it with a Copilot worker: **Copilot thinks, GitLab enforces.** Its security policies are the hardest of all to turn off. |

## Because worker ≠ gate, you can mix — three common recipes

### Recipe A — All GitHub
**VS Code Copilot** (human seat + interactive stages) **+ Copilot CLI** (headless CI stages) **+
GitHub** enforces. One vendor, least setup — **this repo already fits it.**

### Recipe B — Copilot worker + GitLab gates
Your code lives on **GitLab**; you use **VS Code Copilot / Copilot CLI** as the AI worker (it
opens the MR), and **GitLab (without Duo)** enforces with its strong security policies.
Cross-vendor, but clean **because the worker and the gate are separate picks.**

### Recipe C — All GitLab (with Duo)
**GitLab + Duo** does both: Duo is the worker, GitLab is the gate. Simplest if you're
GitLab-centric and licensed for Duo.

## Who runs which stage (per recipe)

| Stage | **A — all GitHub** | **B — Copilot + GitLab** | **C — all GitLab** |
|---|---|---|---|
| Grounding | VS Code Copilot / CLI + MCP | Copilot CLI + MCP | Duo |
| Specifier (draft the spec) | VS Code Copilot (human steers) | VS Code Copilot | Duo |
| 🙋 **approve the spec** | GitHub PR review | GitLab MR approval | GitLab MR approval |
| Test-Author / Builder | Copilot CLI or coding agent → draft PR | Copilot CLI → draft MR | Duo → draft MR |
| Reviewer (the "facts") | GitHub **required checks** | GitLab **required jobs** | GitLab **required jobs** |
| Security guard | GitHub CodeQL/scanners (**required**) | GitLab scanners **+ policy** | GitLab scanners **+ policy** |
| 🙋 **approve the merge** | GitHub non-author approval | GitLab prevent-author-approval | GitLab prevent-author-approval |

*(In every recipe the two 🙋 gates and the 🔒 security check are enforced by the **platform**,
never by the AI.)*

## Recommendation

- **GitHub-first?** → **Recipe A**. (This repo already fits it — least work.)
- **Code on GitLab but you love Copilot?** → **Recipe B** — Copilot worker, GitLab gates.
- **GitLab + Duo licensed?** → **Recipe C**.
- **VS Code Copilot is useful in *every* recipe** as the human's cockpit + review seat.
- **Copilot CLI is the headless worker** for CI in any recipe (it can open a GitHub PR or, via
  `glab`, a GitLab MR).

## One-line summary

**VS Code Copilot** = the human's cockpit · **Copilot CLI** = the headless worker · **GitLab +
Duo** = worker *and* gate in one · **GitLab without Duo** = the strongest gate, bring your own
worker.

*More detail on each platform's enforcement features: [harness-options.md](harness-options.md).*
