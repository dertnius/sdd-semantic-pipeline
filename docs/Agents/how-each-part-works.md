# How each part works (and how the rules are enforced)

Plain English. Bold words are in the [glossary](glossary.md). Read the **big idea** first —
it answers half your questions by itself.

## The one big idea: rules are enforced by software, not by trust

The AI never gets to *promise* it will behave. Instead, three ordinary-software tools make
the rules impossible to break:

1. **Toolboxes (permissions).** Each worker is handed only the tools it's allowed. If it
   doesn't have the "change code" tool, it *cannot* change code — there's no button.
2. **A fixed path with locked checkpoints.** The work travels a set route in plain code. Some
   checkpoints (security, final merge) are welded onto the only path — there's no way around
   them.
3. **Simple automatic checks.** Machine-checkable facts — "do all tests pass?", "does the
   builder's name differ from the reviewer's?", "does every requirement have a test?" These
   are yes/no checks in code, not opinions.

> We don't ask the AI to behave — we don't give it the *ability* to misbehave.

---

## 1. The Router — sorting the job

- **What it is:** a small piece of plain software that runs first and **labels the job**.
- **What it decides:** is this a brand-new project or existing code (**greenfield/brownfield**)?
  Is it a feature, a bug fix, or a cleanup? How risky is it — does it touch money, logins,
  personal data, or public interfaces?
- **How it's built (simplest):** basic checks — does a code folder exist, are there tests, how
  many files; match words in the request; compare the affected files against a short list of
  "sensitive areas." *(Optional later: a small cheap AI reads the request and suggests a label
  — but its answer is just data; the decisions stay in code.)*
- **What it produces:** a little **job ticket** (a saved note) with the labels. That ticket
  travels with the work and tells the line **which approvals and checks turn on**.
- **Picture:** a receptionist who reads your request, ticks boxes, and staples on a routing slip.

## 2. Grounding — finding what already exists

- **What it is:** a **read-only** AI worker that understands the existing code and docs *before*
  anyone writes a spec (essential for messy, existing projects).
- **How it finds information:** it has *search* tools —
  - **code search** (find files, functions, and everywhere they're used),
  - a **map of the code** (which parts call which),
  - **document search** over wikis/tickets/old decisions *(this is exactly what this repo's
    search engine already does — find the right passages by meaning, not just keywords)*,
  - **history** (recent changes, which tests exist).
- **How it works:** a loop — *decide what to look for → search → read the result → update its
  understanding → repeat* — until it has covered a checklist of everything the job touches.
- **How it stays honest:** it labels each fact **seen-for-sure / inferred / guessed**, writes
  down what it still doesn't know, and if it can't find enough it **stops and says "incomplete"**
  rather than pretend. It's **read-only** — it has no tool that can change anything.
- **Picture:** a detective who may only look and take notes, never touch the scene.

## 3. Specifier — writing the spec

- **What it is:** the AI worker that turns your request + Grounding's notes into a clear,
  checkable **spec**.
- **How it writes it:** it follows a **template** (a recipe). For each thing you want, it writes
  a **requirement** with a plain "**done when…**" line (an acceptance criterion) and a number
  (an **ID**). Where there's a real choice (which database, which approach), it writes a short
  **decision record**: the options, the trade-offs, the pick.
- **How it self-checks:** a simple checklist runs — *does every requirement have a "done when"
  and an ID?* If not, it fixes it before moving on.
- **What it does with fuzziness:** a **contradiction** → it stops and **asks you**; a small gap
  → it writes down a labelled **guess (assumption)** so a human can catch it later.
- **The safety step:** **you approve the spec** before anything is built. This gate can't be
  skipped — a wrong spec would poison everything downstream.
- **Picture:** a business analyst who writes the order form so precisely a tester could check it
  and a builder could build it — and who flags anything unclear to you.

## 4. Test-Author — and how we trust the tests

The tests are the *proof* the work is done, so they have to be trustworthy. How we verify them:

- **Coverage check (plain code):** every requirement ID from the spec **must** map to at least
  one test that names it. A simple script checks this; a requirement with no test **blocks the
  line**. Not an AI opinion — a yes/no check.
- **Independence:** the Test-Author is a **different worker from the Builder**, so tests aren't
  quietly written to match whatever the code happens to do.
- **Known-answer practice:** before this worker is trusted at all, it's run on example specs
  where we already know the right tests, and graded (the **promotion gate**).
- **For existing code:** it first writes **characterization tests** that capture how the code
  behaves *today*, giving a baseline to compare against.
- *(Optional, stronger:)* deliberately break the code and confirm the tests **catch it** — if
  they still pass on broken code, the tests are weak.
- **Picture:** the tests are the exam; we check every topic on the syllabus (the spec) has at
  least one question — and the exam-writer isn't the student.

## 5. Making sure only the Builder touches code

This is enforced by **toolboxes**, not by instructions:

- Only the **Builder's** toolbox contains the "**write / change files**" tool. Every other
  worker's toolbox has *read* tools only — there is literally no write button for them.
- A **gatekeeper around every tool use** (plain code) checks at the moment of use: *"Is this
  worker allowed to write? No → refuse."* So even if an AI *tried*, the software blocks it.
- Work happens in an **isolated sandbox**; code changes leave only as a proposed **diff** tagged
  with the Builder's name.
- **You don't tell the AI "please don't edit code" — you don't give it the ability to.**
- **Picture:** only the Builder has the key to the workshop; everyone else looks through the window.

## 6. Making sure the Reviewer isn't the Builder — and that the review is real

**Two separate guarantees.**

**(a) The Reviewer is not the Builder — enforced by the line:**
- They are **separate workers, separate steps, with fresh eyes** — the Reviewer sees only the
  finished **diff + the spec + the tests**, not the Builder's private working notes (and ideally
  uses a **different AI brain**).
- The software **records who built and who reviewed**, and the merge step **refuses if the two
  names match** (a one-line identity check). Self-review is simply not accepted.

**(b) The review is actually good — not just a thumbs-up:**
- **Objective floor (plain code):** the review only counts if concrete facts hold — **all tests
  pass**, **every requirement has a passing test**, the **security scan is clean**, and no
  written-down assumption was violated. A "pass" while a test is red is **auto-rejected**.
- **No vague reviews:** it must point to specifics ("requirement R-7 is covered by test T-12") —
  a fuzzy "looks good" fails the format check.
- **We test the Reviewer too:** we slip it **known-buggy code** and confirm it catches the bugs
  (the promotion gate measures its "catch rate"). High-risk changes get a **second independent
  check** and occasional human spot-checks.
- **Picture:** the grader must show their marking against the answer key — and we quietly slip in
  a known-wrong paper now and then to make sure they're paying attention.

## 7. Making the Security guard impossible to skip

- It is a **mandatory, welded-in checkpoint** on the **only path** between review and merge.
  There is **no route around it**, and **no setting can turn it off** (a risk level can add
  checks, never remove this one).
- It is **not an AI decision** — it's real scanners: a **secret scanner** (no passwords/keys
  committed), a **dependency vulnerability scanner**, and **static analysis**. Their result is a
  plain **pass/fail** the software reads.
- Its result is a **veto**: a fail means **BLOCK, full stop** — it can't be "averaged away" by
  good code elsewhere, and the **merge gate refuses to proceed without a green result**.
- Any emergency override (if allowed at all) requires a **named human** and is **logged loudly**.
- **Picture:** a metal detector bolted into the one doorway — a beep locks the door regardless
  of who you are.

## 8. The Merge gate — the final sign-off

- The **last checkpoint** before the work is accepted. Before a human is even asked, the software
  automatically confirms:
  - the **full test suite passes** (run one more time),
  - **every requirement has a passing test** (coverage complete),
  - the **security result is green**,
  - and it shows a clear summary: the **diff**, the **paper-trail table** (requirement → decision
    → code → test), and any **leftover guesses/open questions**.
- Then a **human approves** — and the builder **can't approve their own work**.
- Only when **all automatic checks pass *and* a human signs** does it merge.
- **Picture:** the loading-dock manager who won't sign the shipment until the packing list is
  complete, the inspection stamps are on, and they've personally signed.

---

## Cheat sheet — one line each

| Part | How it's built | How the rule is enforced |
|---|---|---|
| **Router** | plain checks (+ optional small AI) that label the job | it's just labelling; decisions stay in code |
| **Grounding** | read-only AI with search tools, in a look-then-note loop | given **no** tools that can change anything |
| **Specifier** | AI + a spec template + a self-checklist | **you approve the spec** (can't skip) |
| **Test-Author** | AI writes tests from the spec | plain check: every requirement → a test; separate from Builder |
| **Builder** | AI with the write tool, in a sandbox | **only its toolbox has "write"**; a gatekeeper blocks the rest |
| **Reviewer** | a *different* AI with fresh eyes | software refuses if reviewer = builder; review must cite passing tests |
| **Security guard** | real scanners on the only path | **welded in, veto, can't be turned off** |
| **Merge gate** | auto-checks + a human sign-off | won't merge unless all green **and** a human (not the builder) approves |
