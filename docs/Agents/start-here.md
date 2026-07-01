# Start here — the whole idea in one page

*Plain English. No jargon you can't look up in the [glossary](glossary.md) (bold words are in it).*

## What are we trying to do?

Use AI to help build software **the careful way**: first write down exactly what we want
(the **spec**), then build it, then check the result against what we wrote. We do this with
a small team of AI **workers**, each with one job — and with a **human approving the
important steps**.

## The one picture to remember

Think of a **factory assembly line**. Work moves along a fixed track — and that track is
**plain software, not AI**, so it always behaves the same way (predictable = safe). At each
station, **one AI worker does one job**. At key points a **human signs off**, and **safety
guards** can stop the line.

## The AI team (who does what)

| Worker | Its one job | Note |
|---|---|---|
| **Router** | Sorts the job and picks the route | plain software, not AI |
| **Grounding** | Reads the existing code/docs to understand what's already there | mainly for messy existing projects |
| **Specifier** | Turns the request into a clear written **spec** + decisions | |
| **Test-Author** | Writes the tests that will prove the work is done right | |
| **Builder** | Writes the actual code until the tests pass | the only one allowed to change code |
| **Reviewer** | An **independent** checker: confirms the code matches the spec | never the same as the Builder |
| **Security guard** | Scans for security problems — can stop everything | can't be overruled |
| **Merge gate** | The final **human sign-off** before it's accepted | |

*(Grounding and a "Planner" are optional — added only when the job is big enough.)*

## How the work moves

Each worker finishes and reports one of three things: **PASS** (move on), **BLOCKED** (send
back to fix), or **ASK A HUMAN**. **Plain software — not AI — decides what happens next.**
That is what keeps it predictable. If work keeps bouncing back and forth, a **loop budget**
kicks in and a human is asked.

## How we keep it safe — the three guards (never removed)

1. **A human approves the big moments.** At minimum: approving the **spec**, and the **final
   merge**. A **security problem can never be waved through**.
2. **Guardrails block bad stuff automatically.** *Before* anything runs: check for dangerous
   or off-limits input. *After*: check the output is well-formed and truthful. *Always*: each
   worker may only use the tools it's allowed — **only the Builder can change code**.
3. **A separate Reviewer verifies the work.** The worker who wrote the code **never signs off
   on it**. A different checker confirms it actually does what the spec asked — and that
   **every requirement has a passing test**.

## Which AI brain for which job (routing)

Easy or narrow jobs use a **small, cheap** AI. Hard jobs (writing the spec, reviewing) use a
**bigger, more capable** AI. Which brain each worker uses is **fixed in a simple settings
file — the AI never picks its own brain**.

## Making sure a worker is good before we trust it

Before any AI worker is allowed on the real line, it must **pass practice tests with known
answers** (including safety/trick tests). If it fails, it doesn't go live. That rule is the
**promotion gate**.

## Installing it

Short version: install the package, add your keys/settings, run **one "check" command** that
confirms everything works, then run it. Step by step: **[install.md](install.md)**.

## Two golden rules to remember

- **Plain software drives; the AI only does the thinking inside each step.** (Predictable + safe.)
- **The one who builds never approves their own work.** (A human and an independent checker always verify.)

## Where to go next

- Hit a word you don't know? → **[glossary.md](glossary.md)**
- Want the safety story in a bit more depth? → **[keeping-it-safe.md](keeping-it-safe.md)**
- Setting it up? → **[install.md](install.md)**
- Want the full detail (advanced, optional)? → [agent-architecture.md](agent-architecture.md),
  [agent-checklists.md](agent-checklists.md), [prep-brief.md](prep-brief.md). You **don't**
  need these to follow the discussion.
