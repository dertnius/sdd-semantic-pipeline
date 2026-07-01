# A worked example — change an existing endpoint, or add a new one

Plain English. We follow **one real request** through all the workers and mark exactly where
**you** approve. Markers: 🤖 an AI worker does it automatically · 🙋 **you** (a human) must
approve · 🔒 an automatic software gate that can't be skipped. Bold words are in the
[glossary](glossary.md).

## The request

> "Customers should be able to filter their orders by a date range."

There are two ways to build this:

- **Change the existing** endpoint — add `from` / `to` dates to `GET /orders`, **or**
- **Add a new** endpoint — `GET /orders/search`.

**Who decides which? You do — at the first approval.** The agents don't silently pick your
API design. The Specifier *proposes* the choice with pros and cons, and **you approve it**.
That is the human-in-the-loop moment for exactly your question.

---

## Walk the line (changing the existing endpoint)

**1. 🤖 Router — sorts the job.**
Labels it: *existing project* (**brownfield**), *type = change a feature*, *risk = medium*
(touches customer data, but not logins or payments). Turns on the right checks. → a small
**job ticket**.

**2. 🤖 Grounding — reads what's already there.**
Searches the code and finds the current `GET /orders` handler, how it queries the database,
the existing tests, and whether there's already a "filtering" pattern to copy. Writes a short
**brief**, and notes what it's unsure about (e.g. "is there a database index on the date
column?").

**3. 🤖 Specifier — writes the spec + proposes the design.**
Writes the requirement — *"a customer can pass `from` and `to` dates to `GET /orders` and get
only orders in that range"* — with clear **done-when** checks:
- a valid range returns only orders in it,
- an invalid range returns a clear error (400),
- **no dates = exactly today's behavior** (nothing breaks for existing callers).

It also writes a one-paragraph **decision**: *"Extend the existing `GET /orders` (recommended,
simpler for callers) vs. add a new `GET /orders/search` (more work, another thing to
maintain)."* And it writes down its **assumptions** (dates are inclusive; times are in UTC).

> **🙋 APPROVAL GATE 1 (you, required).** You read the spec and pick **extend vs. new
> endpoint**, and confirm the done-when list and assumptions. *This is where "change existing
> or create new" is actually decided — by you.* Nothing gets built until you approve.

**4. 🤖 Test-Author — writes the tests that will prove it.**
From your approved done-when list: a test for a valid range, one for an invalid range (400),
one proving **old callers still work**, one for the UTC/timezone edge. Each test points back to
a requirement. *(The Test-Author is a different worker from the Builder — on purpose.)*

**5. 🤖 Planner — skipped here.**
This is a one-endpoint change, so there's nothing to split up. (A big, multi-part job would get
a Planner.)

**6. 🤖 Builder — writes the code (the only worker that can).**
Adds the `from` / `to` parameters, updates the database query, keeps the old behavior when no
dates are given, and runs the tests until they pass. Opens a **draft change** (a draft PR) —
it **cannot** approve or merge its own work.

**7. 🤖 Reviewer — an independent check (not the Builder).**
Confirms: all the tests pass, every done-when item has a passing test, **old callers still
work**, the code matches the design **you approved** (extended the endpoint, didn't invent a new
one), and the UTC assumption is honored.

> **🔁 If the Reviewer finds a problem** — say old callers *would* break — it reports
> **"needs fixing"** and the work goes **back to the Builder**, who fixes it and it's reviewed
> again. If they can't agree after a few rounds (the **loop budget**), it stops and asks you.

**8. 🔒 Security guard — automatic, can't be skipped.**
Scanners check the new query parameters for injection risks, look for leaked secrets, and check
for vulnerable libraries. **Any problem = blocked**, full stop.

**9. 🙋 APPROVAL GATE 2 (you, required) — the merge gate.**
Before you're even asked, the software confirms **tests green + coverage complete + security
green**, and shows you the change, the paper-trail (requirement → test), and any leftover
assumptions. **You approve the merge** — and you can't be the Builder. Then it ships.

---

## What's different if you ADD A NEW endpoint instead

Almost everything is the same. The differences:

- **Grounding** looks harder for "is there something to reuse?" and the pattern for adding a new
  route.
- **The Specifier's decision** becomes *"new endpoint `GET /orders/search`"* and defines its
  full contract: the path, the parameters, the response shape, and **who's allowed to call it**
  (authorization).
- **Extra done-when checks:** the new route is registered, is protected like its siblings, and
  is documented.
- **The Security guard pays more attention** — a brand-new public entry point is a bigger
  surface.
- **The flow and your two approvals are identical.**

---

## Where the human is (the whole HITL story, in one place)

For a normal medium-risk endpoint change, **you are asked exactly twice**, plus an automatic guard:

| # | When | What you do |
|---|---|---|
| 🙋 **Gate 1** | after the spec is written | Approve the spec, and **pick change-existing vs. new endpoint** |
| 🔒 **Security** | before merge | *Automatic* — you don't act, but nothing merges if it fails |
| 🙋 **Gate 2** | at the end | Approve the merge (you're not the Builder) |

Everything else runs on its own **within a budget**, and **stops to ask you** if it gets stuck,
hits a contradiction, or the Reviewer and Builder can't agree.

*Tiny, low-risk changes can be set to skip Gate 1 automatically — but a customer-facing endpoint
keeps it. The merge and security gates are never skippable.*

---

## On the real tools (one line)

On **GitHub**: the Builder is the Copilot coding agent opening a **draft PR**; **Gate 1** is you
approving the spec, **Gate 2** is you approving/merging the PR, and the **Security guard** is a
required check. Details: [harness-options.md](harness-options.md).
