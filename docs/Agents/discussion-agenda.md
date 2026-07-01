# SDD Agent Structure — facilitator's agenda (2-hour session)

> Companion to [agent-architecture.md](agent-architecture.md). Print this; use it to run
> the room and record decisions. **Date:** 2026-07-01.

## Objective

Leave the room with **(a)** an agreed agent *structure* for SDD and **(b)** a decision on
each of the 11 items below — owner + choice recorded. Do **not** re-derive the naive four
from scratch; start from the proposed structure and stress-test it.

## Pre-reads (send 24h ahead)

- [agent-architecture.md](agent-architecture.md) — the proposal (10 min read).
- The TL;DR box + verdict table (2 min) for anyone who won't read the whole thing.
- Ask each attendee to come with **one objection** to the proposal.

## Ground rules

- **Burden of proof is on *adding* an agent**, not on collapsing one (OpenAI / Anthropic:
  start simple). A role earns "agent" status only via a distinct reasoning mode, an
  error-reducing specialization, real parallelism, or a genuine trust boundary.
- Decisions are **recorded with an owner**. "We'll circle back" goes to the parking lot,
  not into the design.

---

## Run-of-show

| Time | Segment | Goal | Anchor |
|---|---|---|---|
| 0:00–0:10 | **Frame** | State the thesis; agree the ground rules. | TL;DR box |
| 0:10–0:30 | **Kill/keep the naive four** | Accept "orchestrator = code" and "planner = a Builder mode for now"; keep Specifier + Builder; agree the three omitted roles. | Verdict table |
| 0:30–0:50 | **The gateway decision** | Deterministic spine vs dynamic orchestrator — decide once; everything downstream follows. | §1 backbone |
| 0:50–1:15 | **Core role set + trust boundaries** | Confirm Specifier / Test-Author / Builder / Reviewer; debate the generator≠evaluator cost. | §2 role table |
| 1:15–1:35 | **Brownfield + low-quality** | Grounding service, assumption ledger, escalation policy, "infeasible" as a terminal state. | §4 |
| 1:35–1:55 | **Decisions** | Work the decision agenda; assign owners + defaults. | Below |
| 1:55–2:00 | **Close** | Pick the MVP phase and the first trigger to watch. | §5 phases |

**Facilitator notes per segment**

- **Frame (10m):** read the TL;DR aloud. The single sentence to land: *dynamic within a
  stage, deterministic between stages.* If the room accepts that, most of the design
  follows.
- **Kill/keep (20m):** go row-by-row through the verdict table. Expect pushback on "cut
  the orchestrator" — the counter is auditability/traceability (an LLM conductor can't be
  audited the way a state machine can). Expect pushback on "cut the planner" — the counter
  is *handoff-loss*: a premature planner→builder seam loses intent; keep it a Builder mode
  until parallelism is real and measurable.
- **Gateway (20m):** this is the highest-leverage 20 minutes. If you only decide one thing
  today, decide this. Everything else is downstream.
- **Roles (25m):** the live debate is usually *Reviewer independence* (decision #3) and
  *whether Test-Author is a full agent* (decision #6). Timebox each to ~8 min.
- **Brownfield (20m):** ground the abstractions in a real messy repo everyone knows. Ask:
  "on *that* repo, where does this pipeline stop and ask a human?"
- **Decisions (20m):** don't try to close all ten — close the 3–4 that block Phase-1, park
  the rest with owners.

---

## Decision agenda

For each: pick an option, record the owner. Recommendations are the proposal's position —
override freely.

### D1 — Specifier merge: spec + ADR in one agent, or two approvers?
- **Options:** (a) one Specifier emitting linked artifacts; (b) re-split ADR into its own agent.
- **Trade-off:** if the **same** human signs both the spec and the decisions → one agent.
  If **different** humans / adversarial decision-review is wanted → a new trust boundary
  appears → split is justified.
- **Recommendation:** (a) merged, until a different approver for ADRs actually exists.
- **Decide by:** naming the approver(s). → **Decision: ______  Owner: ______**

### D2 — The exact metric that promotes Planner to an agent
- **Options:** task-count > N; cross-module edges > M; a measured coherence-loss on single-shot.
- **Trade-off:** "multi-module" is hand-wavy — if you can't measure it, you can't justify the
  split, and it stays a Builder step.
- **Recommendation:** pick one measurable number now, even if provisional.
- → **Decision: ______  Owner: ______**

### D3 — Reviewer independence: separate model *run*, or "same model, fresh context, different prompt"?
- **Options:** (a) separate context/run (Anthropic's letter); (b) same instance, new prompt (cheaper).
- **Trade-off:** cost/latency vs genuine author-blindness. Does fresh context alone defeat the
  author's blind spots?
- **Recommendation:** at minimum fresh context + different prompt; separate run for high-risk tiers.
- → **Decision: ______  Owner: ______**

### D4 — Grounding Brief: contract or cache?
- **Options:** (a) frozen one-shot stage; (b) re-queryable persistent service.
- **Trade-off:** a frozen brief loses late-discovered brownfield facts; a cache reorders the
  plan (Grounding becomes Phase-1 *infrastructure*, not a Phase-3/4 *agent*). **This single
  choice cascades through the whole topology.**
- **Recommendation:** (b) cache/service.
- → **Decision: ______  Owner: ______**

### D5 — Loop budget: concrete numbers, and who trips the human gate on exhaustion
- **Options:** per-edge max; global step cap; cost cap; all three.
- **Trade-off:** no answer = a runaway with a credit-card bill; too tight = legitimate repair
  loops abort. Set numbers, not adjectives.
- **Recommendation:** all three, with starting values (e.g. per-edge 3, global 25 steps, $ cap per run).
- → **Decision: ______  Owner: ______**

### D6 — Where does test-authoring live?
- **Options:** (a) its own agent (proposal); (b) a Specifier sub-responsibility; (c) inside the Builder (rejected).
- **Trade-off:** letting the Builder author certifying tests re-collapses generator and
  evaluator. The question is whether test-authoring earns a *full agent* or rides the
  Specifier as an author-independent artifact.
- **Recommendation:** (a) own agent, especially in test-poor brownfield.
- → **Decision: ______  Owner: ______**

### D7 — How risk-tiered are the human gates, and which are never auto-waivable?
- **Options:** fixed four gates vs a Router-set risk tier that toggles spec/plan gates.
- **Trade-off:** auto-approving low-risk speeds throughput but must **never** touch the merge
  gate or the security veto.
- **Recommendation:** risk-tiered spec/plan gates; merge + security veto always mandatory.
  Fill in the Router's gate table.
- → **Decision: ______  Owner: ______**

### D8 — Any residual role for a top-level LLM orchestrator — ever?
- **Options:** (a) never (deterministic edges + model verdicts, the proposal's position);
  (b) some transition a state machine genuinely can't express.
- **Trade-off:** prove the exception with a **concrete transition**, or delete the
  LLM-orchestrator idea permanently and commit to the cyclic state machine.
- **Recommendation:** (a) never — challenge anyone to produce the concrete counter-example.
- → **Decision: ______  Owner: ______**

### D9 — Append-only vs versioned-with-supersession artifact store
- **Options:** (a) simple append-only log; (b) versioned artifacts with computed staleness propagation.
- **Trade-off:** append-only is simpler but rots across back-edges (stale ADRs derived from a
  revised spec); supersession costs bookkeeping but keeps the single-source-of-truth honest
  once cycles exist.
- **Recommendation:** (b) — the cycles make it necessary.
- → **Decision: ______  Owner: ______**

### D10 — Security: veto lane or score term?
- **Options:** (a) a non-averaged veto stage; (b) one axis inside the Reviewer's utility function.
- **Trade-off:** averaging lets great code outweigh a real vulnerability; a separate veto
  guarantees a security failure blocks regardless. Also decide **who owns ingestion
  sanitization** against prompt-injection from ingested repo/docs.
- **Recommendation:** (a) veto lane; name the ingestion-sanitization owner.
- → **Decision: ______  Owner: ______**

### D11 — Skill granularity: how broad are skills, and where does a skill become a subagent?
- **Options:** (a) few **broad skills** (rich, monolithic, easy to author); (b) many composable
  **micro-skills** (testable, reusable, more registry overhead); (c) promote to a **subagent**
  (own context / trust boundary / parallelism).
- **Trade-off:** micro-skills are where determinism + unit-testability live and keep agent
  prompts lean, but proliferation adds orchestration + description-quality burden; a subagent
  costs context + latency, so climb only when isolated context / a different trust boundary /
  parallelism is genuinely needed. *A new tool is not a new skill; a new skill is not a new subagent.*
- **Recommendation:** micro-skills for the deterministic spine checks (spec-lint, trace-ID,
  header-norm, coverage-map); broad skills for recurring procedures (author-ADR,
  author-acceptance-tests); subagents only for the Builder worker fan-out and read-only
  Grounding / adversarial review.
- **Decide by:** naming **3 micro-skills, 2 broad skills, and the 1 subagent boundary** for the MVP.
  → **Decision: ______  Owner: ______**

---

## Decisions log (fill in during the session)

| # | Decision | Choice | Owner | Follow-up |
|---|---|---|---|---|
| D1 | Specifier/ADR split | | | |
| D2 | Planner promotion metric | | | |
| D3 | Reviewer independence | | | |
| D4 | Grounding: contract/cache | | | |
| D5 | Loop budget numbers | | | |
| D6 | Test-authoring home | | | |
| D7 | Risk-tiered gates | | | |
| D8 | Residual LLM orchestrator | | | |
| D9 | Artifact store versioning | | | |
| D10 | Security veto vs score | | | |
| D11 | Skill/micro-skill/subagent granularity | | | |

## Parking lot

- _(capture out-of-scope threads here so the room stays on time)_

## Close-out — pick the first move

- **MVP phase to build first:** ______ (proposal: Phase 1 — spine + Specifier/Builder/Reviewer).
- **The one trigger to watch that promotes the next role:** ______.
- **Owner of the write-up:** ______ · **Next review date:** ______.
