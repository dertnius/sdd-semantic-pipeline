# Putting it together — the tools on the endpoint change, step by step (GitLab)

Combines the worked example ([example-endpoint-change.md](example-endpoint-change.md)) with the
tool roles ([harness-synergy.md](harness-synergy.md)). You chose **GitLab**, so this uses
**Recipe B** — **Copilot** as the AI worker, **GitLab** as the gates — with the **Recipe C (Duo)**
swap at the end. Plain English. Markers: 🤖 AI worker · 🙋 **you** approve · 🔒 automatic gate.

## The cast (who plays what)

- **VS Code GitHub Copilot** — the **human's cockpit**: interactive drafting, reviewing, approving.
- **GitHub Copilot CLI** — the **headless worker**: runs a step in CI with a tight **toolbox**,
  pushes to the MR.
- **GitLab** — the **spine** (CI runs the fixed steps) **+ the gates** (approvals, security,
  merge). **It enforces everything.**

## The task

> "Customers should filter their orders by a date range" → change the existing `GET /orders`.

## Step by step

| # | Step | Who does it (worker) | What happens | Who enforces (GitLab) |
|---|---|---|---|---|
| 0 | Kickoff | a person | Open a **GitLab Issue** with the request. | — |
| 1 | 🤖 Router | GitLab CI (plain) | A CI job labels it *brownfield, medium risk*. | GitLab CI = the spine |
| 2 | 🤖 Grounding | **VS Code Copilot** + the **MCP server** (read-only) | Understand the current `GET /orders`; write a short brief. | read-only tools only |
| 3 | 🤖 Specifier | **VS Code Copilot** (you steer) | Draft the spec + the "extend vs. new endpoint" choice; push a feature branch → **draft MR**. | GitLab holds the MR |
| 4 | 🙋 **Approve the spec** | **you** (spec approver) | Approve the spec in the MR (in VS Code's GitLab view, or the GitLab web UI). | **CODEOWNERS** rule — approver **can't be the author** |
| 5 | 🤖 Test-Author | **Copilot CLI** (in CI, scoped to `tests/`) | Write the acceptance tests; push them to the MR. | writes tests only |
| 6 | 🤖 Builder | **Copilot CLI** (or VS Code Copilot agent mode) | Write the code, run tests until green, push to the **draft MR**. **Only this worker has write tools.** | protected branch — **no direct push to `main`** |
| 7 | 🤖 Reviewer (the facts) | **GitLab CI** (+ optional Duo/Copilot advisory comment) | Required jobs run: **tests, coverage, traceability**. Red → back to the Builder. | **"Pipelines must succeed"** |
| 8 | 🔒 Security | **GitLab CI** | SAST / secret / dependency scans run; a finding **blocks**. | required scans / scan-result policy |
| 9 | 🙋 **Approve the merge** | **you** (merge approver) | Approve; pipeline green; a maintainer merges. | approval rule — **prevent approval by author** |

## How each step connects to the next (the baton)

The steps **don't talk to each other directly.** Each step **reads what the previous step wrote,
and writes its own result** — all in one shared place: **GitLab** (first the **Issue**, then the
**branch / draft MR**). Moving to the next step is triggered either by a **person picking it up**
or by **CI firing automatically**.

**So how is step 2 connected to step 1?**

- **Step 1 (Router)** doesn't hand anything to a person — it **writes labels on the GitLab
  Issue** (e.g. `brownfield`, `risk:medium`). That's its output.
- **Step 2 (Grounding)** **starts from that Issue**: it reads the Router's labels (which tell it
  *"this is existing code — do a full grounding pass"*) and then produces the **Grounding Brief**.
- **The connection is the labelled Issue in GitLab** — not a direct tool-to-tool link. GitLab is
  the shared **hub** every tool reads from and writes to.

The whole baton-pass, one line each:

| Hand-off | What's passed (the baton) | What triggers the next step |
|---|---|---|
| **1 → 2** | the **Issue + Router's labels** | a person opens it (or CI fires on the label) |
| 2 → 3 | the **Grounding Brief** | the Specifier reads the brief |
| 3 → 4 | the **spec, in a draft MR** | you get a review request |
| 4 → 5/6 | the **approved spec** in the MR | Test-Author / Builder add to the same MR |
| 6 → 7 | the Builder's **pushed commits** | the MR **pipeline runs automatically** |
| 7/8 → 9 | **green pipeline + your approval** | a maintainer merges |

**The rule underneath it all:** *workers pass work as written artifacts, never by chatting to
each other* — and here those artifacts live in the **Issue** and then the **MR**. That's what
makes the whole line auditable: you can see every baton pass.

## The synergy in one glance

> **Copilot thinks and drafts** (steps 2–3, 5–6) → **GitLab holds and gates** (the MR: steps 4,
> 7–9). The AI **never merges** — its output is always a **draft MR** that GitLab then checks.
> You use **VS Code Copilot** as the cockpit for the steered steps and the **two approvals**.

## If a check fails (the loop)

Step 7 goes red (say a test fails) → the **Copilot CLI Builder** pushes a fix to the **same MR** →
the pipeline re-runs → when green, back to step 9. After a few failed rounds (the **loop budget**),
it stops and **asks you**.

## Recipe C swap — all-GitLab with Duo

Don't want a Copilot worker? Replace it with **GitLab Duo**: Duo does Grounding / Specifier /
Builder as an **Issue → MR** agent. **Steps 4, 7, 8, 9 (the gates) are identical** — one
ecosystem, one licence.

## Who's "in the loop"

Just **two clicks from you** — step 4 (approve the spec) and step 9 (approve the merge) — plus the
**automatic** security gate at step 8. Everything else runs on its own and asks you if it gets
stuck.

*Setup for all this: [mvp-on-gitlab.md](mvp-on-gitlab.md). Tool roles in general:
[harness-synergy.md](harness-synergy.md).*
