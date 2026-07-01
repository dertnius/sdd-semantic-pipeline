# Build the MVP on GitLab — the how

You chose **GitLab** and to **adopt the shape**. Here's the smallest safe setup, and exactly
**who approves the spec and the merge — and how.** Plain English; the technical bits are ready to
hand to a developer. Bold words are in the [glossary](glossary.md).

## What "the MVP" is (recap)

The smallest setup that already makes **all four safety rules** true:

- **1 protected branch + approval rule** — so only reviewed, non-self-approved code reaches `main`,
- **3 required CI checks** — tests, a security scan, and a "every requirement has a test" check,
- the **coverage gate you already have** (`fail_under=70`),
- **1 AI Builder** that only ever opens a **draft** Merge Request (MR).

---

## Part 1 — Build it on GitLab (a checklist)

A **maintainer** turns these on in the project settings (~15 minutes):

1. **Protect `main`** — *Settings → Repository → Protected branches:*
   - **Allowed to push: No one** → every change must come through an MR.
   - **Allowed to merge:** your maintainers (or a "reviewers" group) — **not** the AI/build user.

2. **Require review + block self-approval** — *Settings → Merge requests → Approvals:*
   - **Approvals required: 1** (or more).
   - ✅ **Prevent approval by the author.**
   - ✅ **Prevent approvals by users who add commits** (nobody who touched the code can approve).
   - ✅ **Prevent editing approval rules in merge requests** (a developer can't loosen it inside the MR).

3. **Make the pipeline required** — *Settings → Merge requests:*
   - ✅ **Pipelines must succeed.**
   - ✅ **All threads resolved** (optional, nice to have).

4. **Add the CI jobs** — in `.gitlab-ci.yml` (the repo already has one; add these). A minimal skeleton:

   ```yaml
   include:
     - template: Security/SAST.gitlab-ci.yml
     - template: Security/Secret-Detection.gitlab-ci.yml
     - template: Security/Dependency-Scanning.gitlab-ci.yml

   stages: [test, verify]

   tests:
     stage: test
     script: pytest

   coverage:
     stage: test
     script: pytest --cov --cov-fail-under=70   # the gate you already have

   traceability:                                 # the one NEW thing to build
     stage: verify
     script: python tools/check_requirements_have_tests.py
   ```

   The **traceability** job is the only new code: a small script that checks *"every requirement in
   the spec has a passing test."* Model it on the repo's existing `check_docs.py`.

5. **The Builder** — an AI worker (**GitLab Duo** or the **Copilot CLI**) that **only ever opens a
   draft MR**. Give its access token **push rights to feature branches only — never merge rights.**

That's the whole MVP: **protected branch + approval rule + "pipelines must succeed" + 4 CI jobs
(tests, coverage, security, traceability) + a write-limited Builder.** All four rules are now live.

---

## Part 2 — Who approves the spec and the merge (and how)

You **name people or groups** in two places; **GitLab enforces** that the approver isn't the
author. You never trust the AI to check this — the platform does.

### Who approves the SPEC → set it with CODEOWNERS

- The spec is a file in the MR (e.g. `docs/adr/…` or a `spec.md`).
- Add a **`CODEOWNERS`** file that names who signs specs, by file path:

  ```
  /docs/adr/    @your-architect-or-lead
  /specs/       @your-architect-or-lead
  ```

- Add **"Code Owners"** as a **required** approval rule (and *"Require Code Owner approval"* on the
  protected branch).
- **Result:** the MR **cannot be approved** until that named person (who is **not** the author)
  approves the spec.

**→ Spec approver = whoever you name in `CODEOWNERS` for the spec files** (usually an architect or
tech lead).

### Who approves the MERGE → set it with an approval rule

- Create an **approval rule** naming your reviewers/maintainers, e.g. *"1 approval from
  @reviewers".*
- Because *"prevent approval by author / by committers"* is on, **the one who wrote it (human or
  AI) can't approve their own merge.**
- Because **"Allowed to merge"** is limited and **"Pipelines must succeed"** is on, the merge only
  happens when the checks are green **and** a named non-author approves.

**→ Merge approver = whoever you name in the approval rule** (e.g. a reviewers group) — and never
the author.

### In one line

> **You just name two people/groups** — the *spec approver* (in `CODEOWNERS`) and the *merge
> approver* (in the approval rule). **GitLab enforces the rest**, including "the approver can't be
> the one who wrote it."

---

## One caveat worth knowing (GitLab tiers)

Some of these are **paid** features:

- **Required approval rules + "prevent approval by author" + CODEOWNERS-required** → need
  **GitLab Premium**.
- The **un-skippable security policy** (scan-result policy that blocks an MR on findings) → needs
  **GitLab Ultimate**.
- On the **Free** tier you still get a lot — protected branches, *"pipelines must succeed"*, and
  limiting who can merge — but the **"the reviewer can't be the author"** rule is a **Premium**
  feature. Good to confirm your tier before relying on it.

---

## The result — all four rules, on GitLab

| Safety rule | What makes it true on GitLab |
|---|---|
| **Only the Builder writes code** | Protected branch (no direct push) + the Builder's token limited to feature branches. |
| **Reviewer ≠ Builder** | "Prevent approval by author / by committers." |
| **Security can't be skipped** | Required scan jobs (+ a scan-result policy on Ultimate). |
| **Merge gate** | "Pipelines must succeed" + non-author approval + limited "allowed to merge." |

## Who does what to set this up (tiny plan)

- **A GitLab maintainer** → Part 1, steps 1–3 (the settings, ~15 min).
- **A developer** → Part 1, step 4 (add the CI jobs + write the small traceability script).
- **You** → decide the **two names**: the spec approver (CODEOWNERS) and the merge approver
  (approval rule).

*Choosing the AI worker (Duo vs Copilot): see [harness-synergy.md](harness-synergy.md) — Recipe B
(Copilot worker + GitLab gates) or Recipe C (all-GitLab with Duo).*
