# Which real tool runs it — GitHub Copilot, the Copilot CLI, or GitLab

> **The short answer, in plain words.** The AI is the **worker**; the git platform
> (**GitHub** or **GitLab**) plus its automatic checks are the **spine and the gates** — you
> never trust the AI to follow the rules, the platform makes them impossible to break. So you
> pick **two separate things**: (1) *which AI does the work* — any of the three can; (2) *which
> platform enforces the rules* — **GitHub or GitLab** (that is the real decision). The **Copilot
> CLI is only ever a worker**, never a gate.

**Recommendation in one line:** start on **GitHub** (this repo already has the GitHub setup, so
it is the least work); move to **GitLab** if you need security you literally *cannot turn off*.
The one new thing to build is a small "every requirement has a test" check.

**The one gotcha:** a gate only counts if you close the back doors — no admin/bypass merge, and
the security check must be *required* and *fail-closed* (see decision **D24** below).

The full, concrete mapping follows. Bold platform settings are the exact things to switch on.

---

## 1. The big idea

The AI agents are **workers** standing at stations on an assembly line: fast and smart, but never trusted with the keys to the building. The **spine** (the conveyor belt that moves work through the stations in a fixed order) and the **gates** (the locked doors that only open when concrete facts are true) are **not AI** — they are plain, deterministic software: **CI pipelines plus branch/merge-protection rules**. Three of our four guarantees are about stopping a worker from cheating, and you cannot ask a worker to enforce a rule against itself — so the building holds the keys, not the worker.

One correction that runs through this whole doc: a platform feature is only a real guarantee **after** you turn on the specific non-default setting, mark the check *required and fail-closed*, and **strip every bypass door** (admin-merge, bypass actors, in-MR overrides). Out of the box, most of these controls are *default-open*. Where that matters, it's called out.

## 2. Which tool does what

| Tool | What it is | Best used as ___ |
|---|---|---|
| **GitHub Copilot** (platform) | Coding agent (opens draft PRs on `copilot/*`, can't self-merge), custom agents (`.github/agents/*.agent.md`), Copilot code review, **+ GitHub platform enforcement** (rulesets, required checks, CODEOWNERS, GHAS). | **The gate platform if you're GitHub-native** — plus a ready Builder (the coding agent) and reusable agent profiles. |
| **Copilot CLI** (`copilot` / `gh copilot`) | Agentic terminal tool: sessions, MCP, **tool allow-lists**, scriptable non-interactive runs; `gh` scripts PR create/review/merge. | **The scripted per-stage worker runtime** — the one surface that natively locks G1 (deny-beats-allow tool lists). Never a gate. |
| **GitLab** (Duo + CI) | `glab` CLI, Duo (Code Suggestions, Chat, agentic **Duo flows** like Issue-to-MR), **GitLab CI/CD**, **MR approval rules**, protected branches, and **security scan-result policies** that block an MR. | **The gate platform when un-skippable security matters most** — the strongest native G2/G3. |

**One-line read:** the AI worker is interchangeable across all three; the real decision is the **gate platform** (GitHub *or* GitLab). The CLI is only ever a worker.

## 3. The enforcement table (4 guarantees × 3 harnesses)

Each cell is the concrete feature — and the **non-default setting** you must enable, because without it the cell is a gap.

| Guarantee | **GitHub Copilot** | **Copilot CLI** | **GitLab** |
|---|---|---|---|
| **G1 — Only the Builder touches code** | **Real enforcer = branch protection on `main`** ("require a PR", "restrict who can push", **no bypass actors**). The coding agent's `copilot/*` branch + agent tool-set is *worker config*, not the lock. | **Best worker-layer G1:** non-builder stages run `--available-tools 'read'`; only Builder gets write/shell; **deny beats allow**. But an allow-list is *config*, not a platform guarantee — still needs `main` protection + **isolated per-stage branches** as the backstop. | Protected branch with **"Allowed to push = No one"** so all code arrives via MR; runner/token scope limits writes. No declarative "read-only agent" object — it's config discipline. |
| **G2 — Reviewer ≠ Builder** (and review counts only if facts hold) | Ruleset: required review **+ "Require approval of the most recent reviewable push"** (this is the one that blocks the last-pusher) **+ dismiss stale approvals on push +** CODEOWNERS excluding build identities. ⚠ Author-separation is **per-push, not per-authorship** — a co-committer who didn't push last can still approve unless CODEOWNERS excludes them. Copilot code review is **advisory only**. | Not enforced by the CLI (worker only) — leans on the GitHub gates. | **Cleanest native controls:** *Prevent approval by author* **+** *Prevent approvals by users who add commits* (excludes every committer, not just the author). ⚠ Committers can approve **by default** and the author can loosen the rule in-MR unless you also set **Prevent editing approval rules** + **Prevent overrides of default approvals**, ideally locked at group level. `@GitLabDuo` review is advisory only. |
| **G3 — Security guard can't be skipped** (hard veto) | GHAS CodeQL / secret scanning / dependency review — **but a scan that *runs* ≠ a scan that *blocks*.** Must be **marked a required status check**, with **"Do not allow bypassing"** on, **no `paths:`/`if:` that lets the scan silently not run**, ideally the code-scanning merge-protection rule. Needs paid GHAS (or an OSS scanner marked required + fail-closed). | Not enforced by the CLI (a script line is skippable) — enforced by a **GitHub required check**. | **Strongest:** an **MR Approval Policy** in a **group-level security policy project** that reads findings, **blocks the MR**, and **overrides project settings** — a developer can't switch it off. ⚠ Ultimate-tier; needs a **populated security-approver group** and **no `allow_failure: true`** on scanners; a **group owner** can still edit the policy. |
| **G4 — Merge gate** (auto-checks green **and** non-author human approves) | Ruleset on `main`: required checks + non-author approval + no self-merge. ⚠ **Worthless if a bypass actor / admin-merge / auto-merge-against-an-incomplete-required-set exists** — "Do not allow bypassing" must be on, bypass list empty, coding-agent identity **not** a bypass actor. | Not enforced by the CLI — opens a **draft** PR, can't self-merge; the GitHub gate does the rest. | Required approvals + CODEOWNERS + **"Pipelines must succeed"** + protected branch (+ optional merge train). ⚠ **"Allowed to merge = No one"** must exclude build identities; a group owner can still merge unless locked. |

**Read of the table:** GitHub and GitLab both enforce **G2/G3/G4 natively** at the platform layer *once the named settings are on*; the **CLI natively enforces only G1** and relies on a git platform for the rest. GitLab has the cleanest G2 (block committers) and G3 (un-skippable policy that overrides the project). The recurring gap on **both** platforms is bypass doors — see D24.

## 4. Stage-by-stage

| Stage | What RUNS it (the worker) | Enforces it — **GitHub** | Enforces it — **GitLab** |
|---|---|---|---|
| **1. Router** | Plain CI logic (best — keeps the spine dumb) or a classifier agent. | Actions job on labels/paths. | CI `rules:` on labels/paths. |
| **2. Grounding** (read-only) | Read-only agent + the repo's `sdd-semantic` MCP server (`.vscode/mcp.json`); reuse `adr-generator` subagents. | Agent tool-set = read/search only; `main` protection backstops. | Read-only Duo agent; runner/token with no write scope. |
| **3. Specifier** (spec, human-approved) | Coding agent / Duo flow writes the spec into a **draft PR/MR**. | "Human-approved" = **required review** on that PR. | **Required approval rule** on the MR. |
| **4. Test-Author** | Agent scoped to `tests/`. | Tests become a **required check**. | Tests are a **required pipeline job**. |
| **5. Planner** (optional) | Read-only planner (Copilot Plan sub-agent / GitLab **Planner Agent**). | No code write — nothing to gate. | Same. |
| **6. Builder** (writes code) | **Only worker with write/build tools** — coding agent (draft PR) / CLI Builder / Duo **Issue-to-MR**. | **G1:** only this agent has commit tools; can't push `main`, approve, or merge. | **G1:** only this runner has push scope; protected branch blocks direct push. |
| **7. Reviewer** (independent) | Copilot code review / `@GitLabDuo` (**advisory**) **+ a human**. | **G2:** non-author approval + dismiss-stale + CODEOWNERS; facts = required checks incl. the **traceability check**. | **G2:** prevent author/committer approval + CODEOWNERS; facts = "Pipelines must succeed". |
| **8. Security guard** (veto) | Deterministic scanners (not an AI opinion). | **G3:** CodeQL / secret / dependency review as **required, fail-closed** checks. | **G3:** SAST/Secret/Dependency/DAST + **MR approval policy** blocking on findings. |
| **Merge gate** (human sign-off) | A human with write access. **AI cannot merge.** | **G4:** checks green **AND** non-author human approves **AND** no bypass door open. | **G4:** approvals + CODEOWNERS + pipeline-must-succeed + protected branch. |

**Two facts are custom checks you must author** on either platform (neither is a native primitive): **"every requirement has a passing test"** (a traceability job) and **"coverage complete."** The platform enforces *"this check is required"*; it doesn't know *what* the check means. Model them on the repo's existing `check_docs.py` / `check_copilot.py` gate scripts. The coverage half you **already own** — `pyproject.toml` has `fail_under=70`; just mark that job required.

## 5. Recommendation + MVP

**Worker and gate are two separate picks.** The worker is interchangeable; the gate platform is the real commitment.

### Primary platform: **GitHub Copilot** for the MVP.

Not because it's stronger than GitLab — because **the repo already ships the substrate**: `.github/workflows/` (the spine), `.github/agents/*` + subagents, `.github/prompts/*`, and the `sdd-semantic` MCP server. Choosing GitLab for its ~5% stronger security policy means standing up a second platform's gates from scratch — the opposite of lean. **Reuse beats the policy edge for the MVP.**

**When to prefer GitLab instead:** if you can use **Ultimate** and un-skippable security is the top requirement. GitLab's MR Approval Policy lives in a *group* project and **overrides the project's own settings** — a developer literally cannot turn it off — and "prevent approvals by users who add commits" is the strongest author-separation control of the three. The repo **already ships `.gitlab-ci.yml`**, so that spine exists too. Do the *gates* on whichever platform you commit to; stay flexible on the *worker*.

### Where the Copilot CLI fits

**A worker, never a gate.** Use it as the scriptable per-stage runner (`copilot -p --agent=<stage>` with a tight `--available-tools` allow-list) because it's the one surface that **natively locks G1**. It must always open a **draft** PR (`gh pr create --draft`) that the platform gates for G2/G3/G4, and its token must carry **no merge scope**. Add it once you want explicit scripted CI stages; it's not MVP-critical (the coding agent already gives you a draft PR + G1).

### The smallest setup that already enforces all 4 guarantees (GitHub)

The MVP goal is **all four locks on, even with minimal workers.** Safety comes from the gates, not the agent fleet.

1. **One branch-protection ruleset on `main`:** require a PR; require **1 approval from a non-author / non-last-pusher** (turn on *"Require approval of the most recent reviewable push"*); **dismiss stale approvals on push**; **no self-merge, no bypass actors, "Do not allow bypassing" on.** → **G2 + G4.**
2. **Required check: your existing `pytest` job** (already in `.github/workflows/`) — the "facts hold" half of G2.
3. **Required check: one security scan** — CodeQL (GHAS) or an OSS scanner (`bandit`/`pip-audit`) marked required and **fail-closed, no conditional skips.** → **G3.**
4. **Required check: one traceability script** — "every requirement has a passing test," modelled on `check_docs.py`. This is **the one genuinely new thing to build** — the platform gives you 3.5 of 4 guarantees by config; you write exactly one script. → completes G2's "facts hold."
5. **Coverage gate you already own** — `fail_under=70` in `pyproject.toml`; mark that job required. → "coverage complete."
6. **Builder = Copilot coding agent** (draft PR on `copilot/*`, can't approve/merge); **every other stage read-only.** → **G1.**

That's the whole MVP: **1 ruleset + 3 required checks (tests, security, traceability) + the coverage gate you already have + 1 write-scoped Builder.** All four guarantees are live. Defer the five distinct stage-agents, merge trains, and GitLab — they add **quality and traceability, not enforcement.**

**GitLab equivalent MVP:** protected branch + approval rule with *Prevent approval by author* **+** *Prevent approvals by users who add commits* **+** *Prevent editing approval rules* (G2) + "Pipelines must succeed" with a green test job (G4) + one native scanner template with an MR approval policy to block on findings (G3) + push scope so only the Builder writes (G1).

### Fuller version (the production line)

Router / Grounding / Specifier / Test-Author / Planner each as a **distinct scoped agent** (reuse `.github/agents/*` + the MCP server for grounding); **full GHAS** or **full scanner suite + group-locked MR policy with a populated security-approver group**; Copilot code review / `@GitLabDuo` as an *assisting* reviewer (human casts the counting approval); merge train / merge queue so `main` always reflects the tested combination. This layer makes the line **smart and traceable** — the safety (all 4 guarantees) is already fully present in the MVP.

## 6. New decisions (D19+)

- **D20 — Worker and gate are separate picks.** "Which AI runs the stage" and "which platform enforces the guarantees" are independent decisions. The worker is interchangeable; the gate platform is the real commitment. **Recommend: adopt this split explicitly.**

- **D21 — Primary gate platform = GitHub for the MVP; GitLab (Ultimate) when un-skippable security is the top priority.** Options: (a) GitHub — maximal reuse of existing repo assets, G3 needs paid GHAS or an OSS scanner; (b) GitLab Ultimate — the un-skippable, project-overriding security policy + strictest author-separation, but a second platform to stand up and Ultimate-tier cost. **Recommend: (a) GitHub for the MVP; revisit (b) if security must be un-turn-off-able by developers.**

- **D22 — The Copilot CLI is the worker runtime, never a gate.** It natively locks G1 (tool allow-lists, deny-beats-allow); it must always feed a **draft** PR/MR into the platform gates, with a token carrying no merge scope. **Recommend: use it for scripted per-stage CI runs, not as MVP-critical.**

- **D23 — Author the two non-native checks ourselves — as MVP, not fuller.** "Every requirement has a passing test" (traceability) and "coverage complete" are **custom required checks** on either harness. Coverage you already own (`fail_under=70`); traceability is the **one script to build.** Until it's required, G2's "review counts only if facts hold" is **half-enforced.** **Recommend: build the traceability gate in the MVP, modelled on `check_docs.py`.**

- **D24 — "No bypass actors" is a precondition on all four guarantees, not a footnote.** A bypass actor / admin-merge / in-MR override / auto-merge-against-an-incomplete-set **single-handedly defeats G2, G3, and G4.** The normal path is blocked; the bypass path is not — and the AI's design closes none of these. **Recommend: on every protected rule, audit the bypass list, enable "Do not allow bypassing," verify auto-merge's required set is complete, lock in-MR override editing, and confirm no build/agent identity is a bypass actor. Make this a standing checklist, re-audited on every rule change.**

- **D25 — Copilot / Duo AI review is advisory, never the counting approval.** Neither Copilot code review nor `@GitLabDuo` can cast the approval that satisfies G2. **Recommend: wire them in as an extra reviewer; the enforced approval always comes from a human (or a separate required custom check).**

- **D26 — MVP first: 1 ruleset + 3 required checks + a coverage gate + 1 write-scoped Builder.** Stand up all four guarantees with the minimal setup before adding the agent fleet. **Recommend: ship the MVP, then layer the fuller version for quality/traceability, not for safety.**

- **D27 — Keep the spine deterministic and protected.** Stage order lives in a CI file (`.github/workflows/` or `.gitlab-ci.yml`), not in an agent's judgment. **Recommend: keep the Router as plain CI logic where possible, and protect the CI file (CODEOWNERS + ruleset) so the spine can't be quietly re-ordered.**