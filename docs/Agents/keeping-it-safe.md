# Keeping it safe (in plain words)

The system is built so AI can **help** but can't cause harm on its own. It rests on
**three guards** and **two habits**. Bold words are in the [glossary](glossary.md).

## Guard 1 — A human approves the big moments (*human-in-the-loop*)

At set checkpoints (**gates**), work **stops until a person approves** it.

- **Always-on gates (can never be skipped):** approve the **spec**; the **final merge**;
  and anything the **security guard** flags.
- **Optional gates (only for risky jobs):** the **Router** decides how risky a job is. Small,
  safe jobs may skip the middle approvals to save time; big or risky jobs get more.
- **When AI is unsure, it stops and asks.** If it hits a contradiction it can't resolve, it
  escalates to a human instead of guessing on something important.

*Why it isn't annoying:* only risky work needs lots of approvals — routine work flows.

## Guard 2 — Guardrails block bad stuff automatically

Three kinds, in plain words:

- **Before (input):** reject dangerous or off-topic requests; hide secrets/passwords; and
  **ignore sneaky instructions hidden inside documents** the AI reads (a real risk when it
  reads old project files).
- **After (output):** make sure the answer is in the right format and is **actually backed by
  facts** — not made up.
- **Always (limits):** each worker may only touch what it's allowed — **only the Builder
  changes code**; nobody may spend more than the **budget**; and the **security scan can stop
  everything by itself** (it can't be outvoted).

## Guard 3 — A separate checker verifies the work (*verification*)

- The **Builder** writes the code; a **different** worker — the **Reviewer** — checks it.
- The Reviewer confirms three things: the code **does what the spec asked** (not just "it
  runs"), **every requirement has a passing test**, and the code respects the guesses we
  wrote down (the **assumption ledger**).
- **The one who builds never signs off on their own work.**

## Choosing the right AI brain (*model routing*)

- Easy or narrow jobs → a **small, cheap** AI. Hard jobs (writing the spec, reviewing) → a
  **big, capable** AI.
- The choice is **fixed in a settings file — the AI can't pick its own brain.** This keeps
  cost down and results consistent.

## Trying out an AI worker before trusting it (*testing*)

- Before any AI worker goes live, it must **pass practice tasks with known answers** —
  including **trick/safety tests** (e.g. "does the security guard actually block a bad
  change?").
- If it fails, **it doesn't go live**. That rule is the **promotion gate**.

## Two habits that make all of this work

- **Plain software drives the line; the AI only thinks inside each step.** Predictable = safe.
- **Everything is written down** — a paper-trail from *requirement → code → test*
  (**traceability**) — so a human can always check what happened.

---

*Full technical detail lives in the advanced docs, but you don't need it to trust the system —
these guards are the whole story.*
