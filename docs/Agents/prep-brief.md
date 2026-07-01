# SDD agent structure — facilitator's prep brief

> **Read this first. Read this if you read nothing else.** It is the single reference to
> run the entire discussion from. ~1 hour to be fully ready. Companions:
> [agent-architecture.md](agent-architecture.md) (deep detail),
> [agent-checklists.md](agent-checklists.md) (per-agent steps),
> [discussion-agenda.md](discussion-agenda.md) (facilitation script).

---

## 0. Your ~55-minute prep plan

- [ ] **0–3 min** — memorize the *60-second position* (§1).
- [ ] **3–13** — internalize the *three mental-model ideas* (§2).
- [ ] **13–23** — learn the *vocabulary* (§3) — especially agent / subagent / skill / micro-skill / tool.
- [ ] **23–30** — read the *proposal on one screen* (§4).
- [ ] **30–42** — read *objections & rebuttals* (§5) — **the part that wins the room**.
- [ ] **42–48** — read *your recommended answers to the 11 decisions* (§6).
- [ ] **48–52** — skim [agent-checklists.md](agent-checklists.md) so you can speak to *how each agent runs*.
- [ ] **52–55** — re-read §1 + glance at *questions to ask the room* (§7) and *soundbites* (§8).

If you have less time: §1 → §5 → §6. Those three alone let you hold the room.

---

## 1. The 60-second position (memorize)

> **The naive four (requirements, orchestrator, planner, code) conflated *roles* with
> *agents*.** The SDD lifecycle *sequence* is known in advance, so the "orchestrator"
> should be **deterministic code, not an LLM agent** — forever. Intelligence belongs
> *inside* stages, not in the conductor. The defensible structure is a **deterministic,
> cyclic spine** carrying a **traceability + assumption ledger**, with **four core agents
> earned by distinct reasoning modes and trust boundaries — Specifier, Test-Author,
> Builder, Reviewer** — plus **conditional Grounding and Planner** promoted only on a
> testable trigger. And not everything is an agent: capabilities form a **ladder — tool →
> micro-skill → skill → subagent → agent** — and you climb it only when justified. What
> makes it "spec-driven" is the **traceability spine**, not the agent count.

---

## 2. The mental model — three ideas that generate every answer

1. **Roles ≠ agents.** A responsibility (requirements, planning, coding) can be a
   deterministic step, a tool, a skill, or a human gate. A thing earns "agent" status
   only via a **distinct reasoning mode, an error-reducing specialization, real
   parallelism, or a genuine trust boundary**. Burden of proof is on *adding* an agent.
2. **Dynamic within a stage, deterministic between stages.** The lifecycle sequence is
   code (auditable, traceable). The *content* of each stage (how to explore this legacy
   code, reconcile this contradiction, fix this test) is open-ended → an LLM loop. The
   model decides each stage's **verdict** (`PASS`/`BLOCKED`/`ESCALATE`); the code-owned
   spine decides what the verdict *does*.
3. **What makes it spec-driven is the traceability spine, not the agent count.** The
   `requirement → decision → task → code → test` chain + the assumption ledger are the
   load-bearing parts. Get those right and the agent count is a tuning knob.

> Corollary (the new bit): the *same* burden-of-proof rule runs all the way down the
> **capability ladder** — a new tool is not a new skill; a new skill is not a new subagent.

---

## 3. Vocabulary you must own

Own these cold — the discussion will use them and you should use them precisely.

| Term | One-line definition | Why it matters here |
|---|---|---|
| **Agent** | model + tools + instructions running a Thought→Action→Observation loop toward a goal | The unit you're rationing. Specifier/Test-Author/Builder/Reviewer are the four. |
| **Subagent** | a *separate agent instance* a parent delegates a bounded task to — own prompt, own context, own tool scope | How the Builder fans out and how Grounding/adversarial-review stay isolated. Costs context + latency. |
| **Skill (broad)** | a packaged *procedure* = instructions + tools + templates, loaded on demand | Keeps agents consistent + prompts lean. e.g. "author-ADR", "author-acceptance-tests". |
| **Micro-skill** | one atomic, single-purpose, tightly-contracted step (often deterministic) | Where the spine's determinism + unit-testability live. e.g. "req-has-criterion+ID", "mint-trace-ID". |
| **Tool** | one external capability (function/API) an agent calls | The lowest rung: `run_tests`, `code_search`, `apply_patch`, RAG query. |
| **Workflow vs agent** | workflow = *predefined code path*; agent = *LLM directs itself* (Anthropic) | Our backbone is a workflow; agents live inside stages. |
| **Augmented LLM** | an LLM + retrieval + tools + memory (Anthropic's building block) | What Grounding/Specifier/Reviewer are. |
| **Orchestrator-workers** | a coordinator dynamically delegates to worker LLMs (Anthropic) | The Builder cell. |
| **Evaluator-optimizer** | a generator + an independent evaluator iterate to a bar (Anthropic) | Builder↔Reviewer, and spec/ADR refinement. |
| **Manager vs handoffs** | central LLM calling agents-as-tools vs peer-to-peer control transfer (OpenAI) | We reject **both** at the top level — they break auditability. |
| **Routing / parallelization / prompt-chaining** | classify-then-dispatch / run-in-parallel / sequential steps (Anthropic) | Router = routing; grounding scans = parallelization; the spine = prompt-chaining. |
| **Deterministic vs dynamic orchestrator** | code decides next step vs LLM decides (Microsoft's gateway) | Our gateway call: **deterministic**. |
| **Traceability spine** | the `requirement→decision→task→code→test` ID chain | The thing that makes it *spec-driven*. |
| **Assumption ledger** | pipeline-long log of assumptions/open-questions | Makes "tolerate low-quality info" real. |
| **Verdict / back-edge** | `PASS`/`BLOCKED(→stage)`/`ESCALATE`; a coded return to a named earlier stage | How cycles stay code-owned. |
| **Loop budget** | per-edge + global step/cost caps; exhaustion → escalate | Stops a cyclic agentic graph from becoming a runaway. |
| **Human gate** | a mandatory or risk-tiered human checkpoint | Layered guardrail; merge + security veto never auto-waivable. |
| **generator ≠ evaluator** | the author must not certify its own work | Why Reviewer and Test-Author are separate from Builder. |
| **Grounding / characterization test** | discovery over existing code / a test that pins current behavior | The brownfield core. |

---

## 4. The proposal on one screen

**Verdict on the naive four**

| Assumed | Ruling | Becomes |
|---|---|---|
| Requirements | keep (absorb ADR) | **Specifier** |
| Orchestrator | **cut** as an agent | the **deterministic spine** |
| Planner | cut from base | a **Builder mode** (promote on a measurable trigger) |
| Code | keep | **Builder** (orchestrator-workers cell) |
| *(missing)* | **add** | **Grounding · Reviewer · Test-Author** |

**Flow:** `Router → Grounding → Specifier ⟶(human gate) → Test-Author → [Planner?] → Builder → Reviewer → Security veto → Merge gate(human)`, with coded back-edges (`Reviewer→Builder`, `Builder→Planner`, `Spec→Grounding`) and escalations to a human.

**The capability ladder** (rung → use when):

```
tool         one capability                         an agent needs to act
micro-skill  one atomic, testable step              a step recurs; you want determinism/tests
skill        a packaged recurring procedure         a how-to recurs; must stay consistent
subagent     a delegated agent, own context         you need isolated context / trust boundary / parallelism
agent        a stage owner with a verdict           a stage needs open-ended judgment + a trust boundary
```

Full detail: [agent-architecture.md](agent-architecture.md) · diagram in [README.md](README.md).

---

## 5. Objections & rebuttals (rehearse these)

**O1 — "Where's the orchestrator agent? Everyone has one."**
→ An LLM conductor over a *known* sequence adds cost, latency, and nondeterminism, and
destroys auditability — the whole point of SDD. We still get dynamic behavior via
model-emitted verdicts on a code spine. The Manager pattern re-introduces exactly the
conductor we're removing. *If they push:* "name one transition a state machine genuinely
can't express" — that's decision **D8**.

**O2 — "This is over-engineered. Start with one agent."**
→ We **do**. Phase 0 is a single agent + human; the MVP is three (Specifier/Builder/
Reviewer); the rest phase in on triggers. Agent count *at maturity* ≠ count *at MVP*.

**O3 — "Planning is clearly different from coding — Planner must be its own agent."**
→ Conceptually yes; operationally a premature planner→builder seam **loses intent**
(handoff loss). Keep it a Builder mode until parallel fan-out actually fires — and name
the metric now (**D2**). It's "not yet," not "never."

**O4 — "Why a separate Reviewer? The Builder can check its own work."**
→ **generator ≠ evaluator.** An author is blind to its own defects; independent
verification is the single highest-leverage move for low-quality code. The only debate is
*how* independent (**D3**), not whether.

**O5 — "Skills vs tools vs subagents — isn't this just jargon?"**
→ No — granularity decides **reuse, testability, and cost**. Micro-skills are where
determinism and unit tests live; skills keep agents consistent; subagents cost context +
latency, so you climb only when justified. That's a real design decision (**D11**).

**O6 — "Will this even survive our brownfield mess and half-written specs?"**
→ That's the *design center*: Grounding + assumption ledger + characterization tests +
the fail-early insufficient-grounding gate. A req→code design fails here precisely because
it skips grounding; this one front-loads it.

**O7 — "Humans-in-the-loop everywhere will be too slow."**
→ Gates are **risk-tiered** by the Router: low-risk changes auto-pass the spec/plan gates;
only **merge + security veto** are always-on (**D7**). Throughput vs safety is tuned, not
maxed.

**O8 — "Who owns state? This will drift across all those loops."**
→ A **versioned artifact store** as single source of truth + the traceability spine +
supersession that propagates staleness (**D9**). Agents talk via artifacts, not chat.

**O9 — "Cyclic loops = runaway cost."**
→ **Loop budgets** (per-edge + global + \$ cap); exhaustion escalates to a human;
Builder↔Reviewer deadlock is a *named terminal state* (**D5**).

**O10 — "Can it just run autonomously?"**
→ Yes, within budgets and gates — and **"infeasible as specified" is a valid terminal
output**. It's *governed* autonomy, not open-ended.

---

## 6. Your recommended answers to the 11 decisions

Steer toward these; concede gracefully where the room has better local knowledge. Full
write-ups (options + trade-off) in [discussion-agenda.md](discussion-agenda.md).

| # | Decision | Recommend | One-line why |
|---|---|---|---|
| D1 | Specifier + ADR one agent? | **Merged** | Same reasoning, same approver — until a different ADR approver exists. |
| D2 | Metric that promotes Planner | **Pick one measurable now** | "Multi-module" you can't measure can't justify the split. |
| D3 | Reviewer independence | **Fresh context + different prompt**; separate run for high-risk | Defeats author-blindness at tiered cost. |
| D4 | Grounding: contract or cache? | **Cache/service** | Brownfield surfaces facts late; a frozen brief rots. Cascades through the topology. |
| D5 | Loop budget | **Per-edge + global + \$, with numbers** | No numbers = runaway; adjectives don't stop a loop. |
| D6 | Test-authoring home | **Own agent** | Builder authoring its own certifying tests re-collapses generator/evaluator. |
| D7 | Risk-tiered gates | **Tiered spec/plan; merge + security always-on** | Speed on low-risk, never on the dangerous gates. |
| D8 | Residual LLM orchestrator? | **Never** | Coded verdicts already cover unpredictability, more auditably. |
| D9 | Artifact store | **Versioned + supersession** | Cycles rot an append-only log. |
| D10 | Security: veto or score? | **Veto lane** | Averaging lets good code outweigh a real vuln. |
| **D11** | **Skill / micro-skill / subagent granularity** | **Micro-skills for spine checks; broad skills for recurring procedures; subagents only for Builder fan-out + read-only Grounding/review** | Climb the ladder only for isolated context, a trust boundary, or parallelism. |

**The four that block a Phase-1 build:** the gateway decision (commit to the deterministic
spine), **D3**, **D4**, **D5**. Close those; park the rest with owners.

---

## 7. Questions to ask the room (to drive convergence)

- "Who signs the spec, and who signs the decisions? Same person or not?" *(settles D1)*
- "On *our* worst legacy repo, where does this pipeline stop and ask a human?" *(grounds D4/D7)*
- "What's the number that says 'now we need a Planner agent'?" *(forces D2)*
- "What's our per-run budget before a human must look?" *(forces D5)*
- "Name three things that should be micro-skills, two that should be skills, and the one
  thing that should be a subagent." *(settles D11 concretely)*
- "Can anyone give me a transition a state machine can't express? If not, the orchestrator
  is code." *(closes D8)*

---

## 8. Soundbites (say-this-if-asked)

- *"Dynamic within a stage, deterministic between stages."*
- *"The orchestrator is code, forever. The model decides the verdict; the spine decides what the verdict does."*
- *"A role is not an agent until it earns a trust boundary."*
- *"generator ≠ evaluator — the author can't certify its own work."*
- *"A new tool is not a new skill; a new skill is not a new subagent."*
- *"What makes it spec-driven is the traceability spine, not the agent count."*
- *"On brownfield, grounding does most of the work; coding is easy once the map and spec are solid."*
- *"'This can't be built as specified' is a valid, successful output."*

---

## 9. The references in one line each (for citing in the room)

- **IBM / Red Hat** — the agent taxonomy: reflex → model-based → goal-based → utility-based → learning → hierarchical → multi-agent. *(Names our agent types.)*
- **Hugging Face** — the **Thought→Action→Observation** loop is the unit of agent execution. *(How every stage runs.)*
- **OpenAI, *Practical guide to building agents*** — agent = model+tools+instructions; **start single-agent**; Manager vs handoffs; layered guardrails. *(Our climb rule + why we reject the Manager at top level.)*
- **Anthropic, *Building effective agents*** — **workflows vs agents**; augmented LLM; the five patterns (chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer). *(Our backbone + where each pattern sits.)*
- **Microsoft, *Components of agent architecture*** — the **deterministic-vs-dynamic orchestrator gateway**; the component list (model/tools/knowledge/memory/guardrails/monitoring). *(Our gateway decision + the shared substrate.)*
- **Copilot Studio guide** — knowledge + topics + tools + dynamic orchestration; **description quality drives selection**. *(Why skills need good descriptions.)*

---

## 10. What to open when

| If someone asks… | Open |
|---|---|
| "Show me the whole design" | [agent-architecture.md](agent-architecture.md) |
| "What exactly does the Builder *do*?" | [agent-checklists.md](agent-checklists.md) |
| "What are we deciding today?" | [discussion-agenda.md](discussion-agenda.md) |
| "Give me the picture" | the diagram in [README.md](README.md) |
