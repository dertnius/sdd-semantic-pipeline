# The first meeting — decide only these 4 things

The goal of the first meeting is **not** to design everything. It's to **agree the shape and
unblock a small first build.** Decide the four things below; **park the rest.** Bold words are in
the [glossary](glossary.md).

> **The one line to open with:** *"Today we decide four things — the shape, the platform, the
> first small build, and who approves. Everything else we decide later, while building."*

---

## Decide these 4 (each has a recommended default, so you can just say "yes")

### 1. Do we adopt this shape?
A fixed software **assembly line**, **AI workers** each doing one job, **humans approving** the
key moments, and the **four safety rules**: only the Builder writes code · the reviewer isn't the
builder · security can't be skipped · a human approves the merge.
→ **Recommended: yes** (adjust names/wording if you like — not the shape). *Show
[start-here.md](start-here.md) on screen.*

### 2. Which platform enforces the rules — GitHub or GitLab?
The **platform** (not the AI) enforces the safety rules.
→ **Recommended: GitHub** — this repo is already set up for it. Choose **GitLab** only if
security must be *impossible to turn off*. *(Detail: [harness-options.md](harness-options.md).)*

### 3. What do we build first (the small, safe MVP)?
The **smallest setup that already makes all four rules true**: one branch-protection rule +
three automatic checks (tests, a security scan, and a small "every requirement has a test"
check) + **one** AI Builder that opens a draft change. Add more AI workers later.
→ **Recommended: yes, build exactly this first**, and name who sets it up.

### 4. Who approves?
Name the person who approves **the spec** and the person who approves **the merge** (they can be
different). Confirm the AI (and the author) **can't approve their own work**.
→ **Recommended: name 1–2 people today.**

---

## Park everything else (decide later, while building)

These are real decisions — just **not for meeting one**. They live in the backlog
([discussion-agenda.md](discussion-agenda.md)) and the advanced docs. Examples:

- exact loop-budget numbers · how independent the reviewer must be · grounding "cache vs
  contract" · which AI brain per job (model routing) · skills vs sub-agents · the full worker
  fleet · the security-policy tier · closing every bypass door.

> If someone raises one of these, write it on the parking board and move on. **Don't spend
> meeting one on them.**

---

## A short agenda (~45 minutes)

| Time | What | Outcome |
|---|---|---|
| 0:00–0:10 | The idea — show [start-here.md](start-here.md) | Everyone shares the picture |
| 0:10–0:20 | **Decision 1** — adopt the shape? | Yes / adjust |
| 0:20–0:30 | **Decision 2** — GitHub or GitLab? | Pick one |
| 0:30–0:40 | **Decision 3** — build the small MVP? | Yes + who builds it |
| 0:40–0:45 | **Decision 4** — who approves? | Names |

## Record your 4 answers

| # | Decision | Answer | Owner |
|---|---|---|---|
| 1 | Adopt the shape | | |
| 2 | Platform (GitHub / GitLab) | | |
| 3 | Build the MVP | | |
| 4 | Who approves (spec / merge) | | |

That's the whole first meeting. The longer list of decisions is a **backlog for later**, not a
to-do for today.
