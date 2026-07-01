# SDD pipeline — per-agent, per-step checklists

> Operational companion to [agent-architecture.md](agent-architecture.md). One block per
> stage: **trigger · inputs · steps (the Thought→Action→Observation work) · skills &
> micro-skills it uses · subagents it spawns · exit verdict · human gate · failure/budget**.
> Legend: **[A]** = agent · **[S]** = deterministic spine (not an agent) · **[A?]** =
> conditional agent (else a step).

---

## 0. Every stage obeys this contract (cross-cutting)

- [ ] Read inputs **from the artifact store**, not from chat; write outputs back as artifacts.
- [ ] Do the work as a bounded **Thought → Action → Observation** loop.
- [ ] Emit **exactly one verdict**: `PASS` · `BLOCKED(reason, target_stage)` · `ESCALATE(reason)`.
- [ ] Validate the **trace links** (`requirement→decision→task→code→test`) for anything you produced.
- [ ] Append any `Assumption` / `OpenQuestion` to the **assumption ledger**.
- [ ] Respect the **loop budget**; on exhaustion `ESCALATE` — never spin, never silently give up.

---

## 1. Router / Intake **[S]**

- **Trigger:** a new request (feature / fix / refactor) enters the pipeline.
- **Inputs:** raw request + repo handle.
- **Steps:**
  - [ ] Detect **greenfield vs brownfield** (repo present? size? tests present?).
  - [ ] **Risk-tier** the change (blast radius, security surface, reversibility).
  - [ ] Select the **pipeline profile** + which gates are live for this tier.
  - [ ] Choose **Grounding form** — RAG-tool vs subagent — by brownfield size.
  - [ ] Emit the `run_manifest` artifact.
- **Skills / micro-skills:** `repo-probe` (µ), `risk-tier` (µ), `route-select` (µ).
- **Exit:** always `PASS` → Grounding (it only *chooses a path*).
- **Human gate:** none (auto).

---

## 2. Grounding / Discovery **[A?]** (service by default; agent-form on large/low-quality brownfield)

- **Trigger:** `run_manifest` ready.
- **Inputs:** `run_manifest`, repo, docs, prior ADRs.
- **Steps:**
  - [ ] Load the **coverage checklist** (modules to map, integration points to name).
  - [ ] Loop: *(Thought)* plan the next probe → *(Action)* `code_search` / dependency- & call-graph read / test- & CI-history read / doc retrieval → *(Observation)* update the world-model — until the checklist is covered or the budget is hit.
  - [ ] Tag every claim **observed / inferred / assumed**.
  - [ ] Write the **Grounding Brief** + an explicit **Unknowns/Assumptions** list.
- **Skills / micro-skills:** `code-comprehension` (skill), `rag-query` (µ), `coverage-check` (µ). **Read-only tools only.**
- **Subagents:** in agent-form, may run a small dynamic manager over read-only tools (the one place the *investigation sequence* is genuinely unknowable).
- **Exit:** `PASS(COMPLETE)` → Specifier · `ESCALATE` if coverage `INCOMPLETE` or open-questions exceed threshold (**fail early, before spending spec/code effort**).
- **Human gate:** none standing; escalates. Greenfield: degenerates to grounding on external references (thin).

---

## 3. Specifier **[A]** — goal-based · prompt-chaining + evaluator-optimizer

- **Trigger:** Grounding Brief ready.
- **Inputs:** intent + Grounding Brief.
- **Steps:**
  - [ ] Ingest intent + Brief; list the requirements.
  - [ ] Loop: draft spec → run **contradiction/ambiguity check** → refine (evaluator-optimizer).
  - [ ] For each requirement: attach an **acceptance criterion** + **mint a requirement ID**.
  - [ ] Author **ADRs** from template (options → score trade-offs → decision) + an arch-note.
  - [ ] Record `OpenQuestion`s: **contradiction ⇒ escalate to human**; **gap ⇒ budgeted assumption**.
  - [ ] Run the **Spec Validator** lint (every requirement has a criterion + an ID).
- **Skills / micro-skills:** `author-ADR` (skill), `author-spec` (skill), `contradiction-check` (µ), `spec-lint` (µ), `mint-trace-ID` (µ), `option-score` (µ). **Read-only.**
- **Exit:** `PASS` → Test-Author (after the gate) · `BLOCKED(→Grounding)` if grounding gaps block · `ESCALATE` on contradiction.
- **Human gate:** **MANDATORY — spec/decision gate.** (D1: one approver ⇒ one agent; two approvers ⇒ split ADR out.)

---

## 4. Test-Author **[A]** — goal-based · generator ≠ evaluator (for tests)

- **Trigger:** Spec + ADRs **approved** at the spec gate.
- **Inputs:** approved Spec + ADRs.
- **Steps:**
  - [ ] For each acceptance criterion: author an **executable acceptance test** citing the requirement ID.
  - [ ] Brownfield: author **characterization tests** to pin current behavior (a baseline for "verify against done").
  - [ ] Map coverage: **every criterion → ≥1 test** (fail if any criterion is untestable).
  - [ ] Flag untestable criteria back to the Specifier.
- **Skills / micro-skills:** `author-acceptance-tests` (skill), `characterize-legacy-behavior` (skill), `coverage-map` (µ). **Reads code; writes tests only** (a real scope boundary — it must not touch product code).
- **Exit:** `PASS` → Planner/Builder · `BLOCKED(→Specifier)` if a criterion can't be made testable.
- **Human gate:** none standing; its output is gated at merge. *(D6: keep it its own agent so the Builder never certifies its own code.)*

---

## 5. Planner **[A?]** — goal/hierarchical (present only when the trigger fired)

- **Trigger:** change spans ≥2 modules with real inter-task dependencies **and** parallel fan-out fires (else this is a step inside the Builder).
- **Inputs:** approved Spec + ADRs + acceptance tests.
- **Steps:**
  - [ ] Decompose into an **ordered, dependency-aware task graph**.
  - [ ] Assign requirement IDs to each task (**trace**).
  - [ ] Mark **parallelizable vs serial** tasks; flag overlapping-file conflicts for serialization.
  - [ ] Emit the task-plan artifact.
- **Skills / micro-skills:** `decompose-plan` (skill), `dependency-order` (µ), `conflict-detect` (µ).
- **Exit:** `PASS` → Builder · `BLOCKED(→Specifier/ADR)` if planning exposes a spec gap.
- **Human gate:** **conditional** (risk-tier) plan gate. *(D2: name the metric that makes this agent exist.)*

---

## 6. Builder cell **[A]** — orchestrator-workers + evaluator-optimizer

### 6a. Builder cell (orchestrator)
- **Trigger:** task plan (or, without a Planner, the approved spec) ready.
- **Steps:**
  - [ ] Read the task plan; **fan out one Builder subagent per task**, respecting dependency order / conflict serialization.
  - [ ] Collect diffs + task-test results from workers.
  - [ ] **Reconcile conflicts** across parallel workers touching overlapping code.
- **Subagents:** N × **Builder worker** (6b).

### 6b. Builder worker **[subagent]** (per task)
- **Steps:**
  - [ ] Loop: **edit → build → run task tests → fix**, until the task's acceptance criteria pass or the budget is hit (evaluator-optimizer).
  - [ ] Write unit scaffolding as needed (its own tests, *not* the certifying acceptance tests).
  - [ ] Emit **diff + passing task tests + an uncertainty note**, tagged task + requirement IDs.
- **Skills / micro-skills / tools:** `implement-task` (skill); tools: `apply_patch`, `build`, `run_tests`, `code_search` (**read + write**). Cell-level `conflict-reconcile` (µ).
- **Exit:** `PASS` → Reviewer · `BLOCKED(→Planner)` if a task is unimplementable as planned · `ESCALATE` on budget exhaustion.
- **Human gate:** batch-gated at merge (no per-task gate).

---

## 7. Reviewer / Verifier **[A]** — utility-based critic · evaluator-optimizer

- **Trigger:** Builder emitted diffs + passing task tests.
- **Inputs:** diff + Spec + ADRs + acceptance tests + assumption ledger — **fresh context, a different prompt from the Builder** (D3).
- **Steps:**
  - [ ] Run the **acceptance tests** + coverage + static analysis.
  - [ ] **Requirement-coverage** (deterministic): every requirement → a passing, traceable test.
  - [ ] **Done-criteria conformance**: does the diff satisfy the acceptance-criteria *text*? (Catches a green test that tests the wrong thing.)
  - [ ] Check the code **honors open assumptions** in the ledger.
  - [ ] Find author-blind defects; produce a **Verification Report** (pass/fail per requirement).
- **Skills / micro-skills:** `verify` (skill), `traceability-check` (µ), `done-criteria-conformance` (µ), `static-analysis` (tool).
- **Subagents (optional):** an adversarial `refute` subagent per high-risk finding (perspective-diverse verify).
- **Exit:** `PASS` → Security veto · `BLOCKED(→Builder)` with **specific** defects · `ESCALATE` on Builder↔Reviewer deadlock (named terminal state).
- **Human gate:** feeds the merge gate.

---

## 8. Security veto lane **[S]** — non-averaged

- **Trigger:** Reviewer `PASS`.
- **Steps:**
  - [ ] Run **SAST**, **secret-scan**, **dependency/SCA**.
  - [ ] Confirm **ingestion sanitization** was applied to any retrieved repo/doc data (prompt-injection surface).
  - [ ] **Non-averaged:** any security failure blocks regardless of other quality.
- **Skills / micro-skills:** `sast` (tool), `secret-scan` (tool), `sca` (tool), `ingestion-sanitize` (µ).
- **Exit:** `PASS` → Merge gate · `BLOCKED(→Builder)` on any finding.
- **Human gate:** the veto is **never auto-waivable** (D10).

---

## 9. Integrator / Merge gate **[S]** + human

- **Trigger:** Security veto `PASS`.
- **Steps:**
  - [ ] Run **full CI**.
  - [ ] Assert **requirement-coverage completeness** (every acceptance criterion → a passing test).
  - [ ] Surface **unresolved assumptions / open-questions** from the ledger.
  - [ ] Present the **traceability matrix** (`requirement→decision→task→code→test`) for sign-off.
- **Skills / micro-skills:** `ci-run` (tool), `coverage-assert` (µ), `trace-matrix` (µ).
- **Exit:** `PASS` = **merge** · else `BLOCKED`/`ESCALATE`.
- **Human gate:** **MANDATORY — human merge.**

---

## Skills & subagents at a glance (fill in for the MVP — D11)

| Kind | Owned by | Examples above | Rule to apply |
|---|---|---|---|
| **Micro-skill** (µ) | the spine + every agent | `spec-lint`, `mint-trace-ID`, `coverage-map`, `traceability-check`, `ingestion-sanitize` | Extract when one step is reused + you want it deterministic/unit-tested. |
| **Skill** (broad) | one or more agents | `author-ADR`, `author-acceptance-tests`, `characterize-legacy-behavior`, `implement-task`, `verify` | Package when a whole *how-to* recurs and must stay consistent. |
| **Subagent** | Builder cell, Grounding, Reviewer | Builder workers; read-only Grounding manager; adversarial `refute` | Promote **only** for isolated context, a different trust boundary, or parallelism. |
| **Tool** | any agent | `run_tests`, `apply_patch`, `code_search`, `sast` | The default; a capability, not a procedure. |

> Homework for the room: name **3 micro-skills, 2 skills, and the 1 subagent boundary** you
> commit to for the MVP. That single exercise operationalizes decision **D11**.
