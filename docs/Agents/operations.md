> **Advanced / optional — beginners do not need this page.** For the plain-English version,
> read **[keeping-it-safe.md](keeping-it-safe.md)** (human sign-offs + guardrails +
> verification) and **[install.md](install.md)** (setup). This page is the detailed operating
> plan for whoever implements the system, grounded in current (2025-2026) tooling.

---
# The SDD Agent Operating Plane — Final Operational Plan

**Reconciliation stance.** Two critiques pull opposite ways: Occam says "ship the spine, feel the pain, build the rest v2"; coverage-fit says "you've certified the parts but not the whole, and the substrate has no integrity model." They are not in conflict — they cut on different axes. Occam is right about *how much* to build first; coverage-fit is right about *which invariants must hold at any size*. I resolve every conflict by one rule:

> **Topology and invariants ship at MVP; sophistication is deferred.** A gate's *shape* (hard AND, no-budget veto, runtime assertion not prompt promise, closed verdict vocabulary) is cheap and load-bearing — it ships now. A gate's *intelligence* (LLM judges, classifiers, tiers, telemetry, gateways) is expensive and speculative — it waits for felt pain. You cannot cheaply retrofit topology; you can always cheaply add intelligence behind a stable seam.

Concretely: I accept Occam's cuts (no risk tiers, no model-based guardrails, no gateway, no LLM-judge gate, no extras matrix, flat model policy, defer D17/D18-as-CI-gate) **and** I accept coverage-fit's two must-fixes (G1 end-to-end pipeline certification, G3 artifact-store integrity model) plus the cheap G2 fix (name the tool-scope interceptor), because those are topology, not sophistication. The verdict-`reason` enum ships as a plain growable `Enum` (Occam) that is *seeded complete* from the plan (coverage-fit G6) — same object, both critics satisfied.

---

## Section 1 — Human-in-the-Loop & Guardrails

### 1.1 Gate taxonomy mapped to stages and verdicts

Three gate classes. The posture is a property of the **stage boundary**, not the agent — preserving "dynamic within a stage, deterministic between stages." A human gate is *earned by a verdict*, never blanket-imposed.

| Class | Gates | Who decides posture | MVP? |
|---|---|---|---|
| **MANDATORY** (spine constants, no tier removes them) | **Specifier approval · Security veto · Merge gate** | hard-coded in the spine | yes (Specifier + Merge as human gates; Security veto automated — see below) |
| **RISK-TIERED** (posture selected by `risk_tier`) | Grounding / Test-Author / Planner / Builder / Reviewer | Router emits `risk_tier` | **no — v2** |
| **ADVISORY** (post finding, silence = proceed) | Reviewer / Grounding findings | always advisory | yes (as a log, not a queue) |

**Verdict → posture → action (the load-bearing seam):**

| Agent verdict | Spine action | Human involvement |
|---|---|---|
| `PASS` at a mandatory / tiered-IN gate | park → `APPROVAL_REQUEST` artifact | **IN** — approve / edit / reject to advance |
| `PASS` at a tiered-ON / advisory gate | advance now; post notification | **ON** — may interrupt; silence = proceed |
| `PASS` at an OUT stage | advance; log only | **OUT** |
| `BLOCKED(reason, target)` | back-edge, decrement loop budget | none until budget = 0 |
| `ESCALATE(reason)` | **always** → `APPROVAL_REQUEST`, any stage | **IN** — the universal "promote to human" |

`ESCALATE` is the single verdict that forces a human gate anywhere — how an OUT stage reaches up without the spine hard-coding a gate there.

**Reconciliation (Occam vs. the original plan).** The original plan's three-tier Router classification, four review surfaces, and rubber-stamp auto-retuning telemetry are **deferred to v2**. Occam is correct: you cannot design anti-fatigue telemetry before you have felt fatigue, and handing blast-radius classification to the *cheapest* agent (the Router) is itself a feature needing its own evals before it may *remove* a human gate. **MVP = two hard-coded human gates (Specifier, Merge)**, which are rare and load-bearing and therefore cannot themselves cause fatigue. One tier (`high` flips Test-Author IN) is the *first* v2 addition, earned once ~20 real runs point at a class of change that burned us.

### 1.2 Escalation policy (deterministic, spine-owned — not agent judgment)

- **Contradiction** (new evidence conflicts a committed artifact) → always `ESCALATE(contradiction)`.
- **Gap** (missing info) → budgeted **assumption-ledger** entry, proceed; escalate only on budget exhaustion.
- **Loop-budget / deadlock** → `ESCALATE(deadlock)`.
- **USD budget** → `ESCALATE(budget)` (see §2 precedence, G5 fix).

### 1.3 Interrupt / resume via the artifact store (the store *is* the checkpointer)

The versioned artifact store is the single source of truth **and** the checkpointer **and** the audit log. No separate checkpointer library needed — but import the two hard-won lessons from graph-orchestration frameworks (e.g. LangGraph):

1. **The resume token is `work_item_id`.** The pipeline is cyclic; a parked item simply stops advancing while others flow.
2. **The gate must be the first, side-effect-free suspension point in a stage** (or the stage must be idempotent), because a naïve resume re-runs the node top. `EDIT` = decision payload overwrites the artifact before advancing; `REJECT` = `BLOCKED(reason, target_stage)`.

**Must-fix G3 — the control-plane store needs a stated integrity model (ships at MVP, it's topology).** The repo's memory-backend "rewrite-the-whole-JSON after every file" pattern is explicitly *wrong at scale* and must **not** be inherited for the control plane. State it now:

- **Content-addressed artifacts.** Every artifact id is a hash of its content; a *supersede is a new id*, never a mutation. The audit log is therefore append-only by construction — the spine cannot tamper in place.
- **Per-`work_item_id` optimistic lock** on the checkpoint (compare-and-swap on a version counter) so two stage-runners cannot clobber one item's state.
- **Scale-appropriate backend from day one** (an embedded transactional KV / SQLite-class store, not a rewrite-everything JSON blob).

**Must-fix (coverage-fit Q1) — stale-checkpoint on resume.** While an item is parked, upstream artifacts or the `policy_hash` may move. On resume, **re-run the stage's input-provenance assertion**: if the checkpoint references a superseded artifact id or an older `policy_hash`, resume yields `BLOCKED(reason="stale-checkpoint", target_stage=<upstream>)` rather than blindly advancing. One row on the resume path, reusing the provenance stamp (§0-substrate).

**G8 fix — approver authz.** Each `APPROVAL_REQUEST` carries a required-approver-role derived from the gate class; a Security-veto override (if permitted at all) needs a distinct role. `doctor.hitl` asserts every mandatory gate has an approver-role bound.

### 1.4 The layered guardrail catalog

A guardrail answers *"is this ALLOWED?"* → `BLOCKED`/`ESCALATE`. An evaluator answers *"is this GOOD ENOUGH?"* → quality score → loop-budget retry. **Same plumbing, different question.** Prefer a deterministic guardrail (micro-skill); climb to a model-based subagent only when a rule cannot express the check.

| Layer | Guardrail | MVP mechanism (deterministic) | v2 (model-based) | Ladder rung |
|---|---|---|---|---|
| **INPUT** (blocking, pre-agent) | secret / PII scan | **Gitleaks / TruffleHog + regex**, on inputs; `ESCALATE` only on a *verified-live* credential | Presidio NER | micro-skill |
| | input schema validation | JSON-Schema on the work-item | — | micro-skill |
| | prompt-injection scan | — (deferred) | injection-classifier subagent over prompt **and every retrieved chunk** | subagent |
| **OUTPUT** (concurrent, pre-commit) | artifact-schema validation | the artifact contract itself | — | micro-skill |
| | generated-code safety | **semgrep + bandit + Gitleaks on the diff** — *this is the veto's evidence at MVP* | — | micro-skill |
| | faithfulness / grounding | — (deferred) | faithfulness-judge subagent | subagent |
| **BEHAVIORAL** (ambient, spine/runtime) | **tool-scope least privilege** | **runtime tool-dispatch interceptor** (see G2) | — | spine shim |
| | ingestion sanitization | reuse `quality.check_chunk` shape — chunk hygiene + secret scan on every grounded chunk | + injection classifier | micro-skill |
| | loop / cost caps | cumulative-USD + loop-count → `ESCALATE` | — | spine |

**Must-fix G2 — name the tool-scope interceptor (topology, ships at MVP).** "Least privilege by interception" cannot rest on a prompt promise. `workspace.py` is a *path* guard, not a *tool-catalog* guard — so add its behavioral twin: a spine-side **tool-dispatch shim** that consults `tools/catalog.yaml` at call time and rejects any out-of-scope tool call with `BLOCKED(reason="tool-scope")` — the tool-dimension twin of the inbox/outbox `exit 2`. CI asserts both directions: every tool a stage *declares* is in the catalog, **and** the agent physically *cannot* emit a tool outside its row.

**G4 fix — ingestion sanitization is ambient, not Grounding-scoped.** Grounding is a *conditional* stage; pinning the indirect-injection defense to it means a greenfield pipeline silently loses it. Reclassify ingestion sanitization as a **behavioral/ambient** guardrail that fires wherever a retrieved chunk enters *any* prompt; `doctor.guardrails` asserts it is present independent of whether Grounding exists.

### 1.5 The security veto — the one architectural crux

Ratify: the veto is a **hard, non-averaged AND-gate** into Merge — two separate edges (`Reviewer PASS` **AND** `Security PASS`), a PASS from one *cannot* cancel a BLOCK from the other. It runs in **isolated context** (a subagent) so a compromised Builder cannot talk it out of a block. **A security BLOCK does *not* consume loop budget — security escalates, it never retries.**

**Reconciliation.** Occam is right that the *scanner* behind the veto is dumb at MVP: the veto's value is its **topology**, not the sophistication of what fires it. **MVP veto = "did semgrep/gitleaks find a P0 (hardcoded cred, obvious injection sink)? → BLOCK."** No "veto-reasoner subagent." The red-team-tuned model-based veto is v2 — but the *AND-gate shape and the no-budget rule ship now* and never change.

### 1.6 Anti-patterns → fixes

| Anti-pattern | Fix |
|---|---|
| Gate fatigue from too many human gates | MVP has exactly two; add tiered gates only on felt pain, not speculatively |
| Security fused as a weighted score with Reviewer | hard AND-gate; a PASS cannot outvote a BLOCK |
| Least privilege as a prompt instruction | runtime tool-dispatch interceptor (G2), not prose |
| Injection defense pinned to a conditional stage | reclassify as ambient (G4) |
| Blind resume of a parked item | stale-checkpoint re-validation (Q1) |
| Control-plane store as a rewrite-everything JSON blob | content-addressed + optimistic-lock + transactional backend (G3) |

---

## Section 2 — Model Routing & Enforcement

### 2.1 Decision

Model choice is **infrastructure policy owned by the spine**, not a runtime self-decision. **Primary pattern: static per-stage policy, asserted in-process.** Reject the learned dynamic router — it injects a non-deterministic decision *between* stages, and with ~7 stages a lookup table beats a classifier on legibility and correctness.

**Reconciliation (Occam).** The original plan's four-rule bespoke `check_model_policy.py`, the gateway with virtual-key 403s, and the dormant `cascade:` field are all **deferred**. Occam is right: for ~7 stages a lookup table needs no proxy and no standalone linter, and a dormant schema field is a one-line change *later anyway* (YAGNI). What survives is the part that genuinely *prevents* the failure rather than declaring intent — and coverage-fit confirms this is the plan's best-defended claim.

### 2.2 The code-owned registry — MVP shape (flat) and the growth path

**MVP (flat, one model per stage):**

```yaml
# config/model-policy.yaml   (schema-validated at load)
policy_hash: <content-hash>          # stamped onto every artifact (§0)
stages:
  router:        { model: <fast-model> }
  grounding:     { model: <mid-model> }
  specifier:     { model: <frontier-model> }    # trust-critical
  test_author:   { model: <frontier-model> }    # trust-critical
  builder:       { model: <mid-model> }
  reviewer:      { model: <frontier-model> }     # trust-critical
  security_veto: { model: <frontier-model> }     # trust-critical
  merge_gate:    { model: <fast-model> }
```

**Growth path (add only when a fallback is actually wanted):** promote each `model:` scalar to a tier alias + an `allow:` list, so the concrete model ID lives in exactly one `tiers:` block (the `EMBED_FORMAT_VERSION`-in-one-module discipline). Trust-critical stages (Specifier, Test-Author, Reviewer, Security veto) declare **no `allow` beyond frontier and no down-cascade** — a trust boundary that can silently drop to a weaker model is a broken trust boundary. The `cascade:` field and the per-stage `effort` lever join here, not at MVP.

### 2.3 The four enforcement mechanisms

1. **Runtime assertion (ships at MVP — the load-bearing one).** After each model call, `assert served_model == policy[stage].model` (or `∈ allow[stage]` once lists exist) else `BLOCKED(reason="model-policy", target_stage)`. **Coverage-fit Q3 fix:** the assertion must read the **provider-returned** model id from the response, *not* the requested id — otherwise it is a tautology asserting the request against itself. A provider that does not echo its served model is `[unsupported]` for policy enforcement until a gateway lands; a contract test proves the assertion reads the response-side field. This catches the real failure mode — a subagent silently inheriting the parent model — even with no gateway.
2. **CI / lint declaration check (MVP = schema; standalone gate = v2).** MVP: JSON-Schema validation of `model-policy.yaml` + a five-line assertion (every stage maps to a real agent; trust-critical stages carry no weak model). The bespoke `check_model_policy.py` sibling with four rules is v2, folded in when there are many callers to police ("no un-governed caller").
3. **Provenance stamping (MVP — nearly free).** Every artifact carries `{stage, model_id, tier, effort, tokens, usd, policy_hash}`. Traceability now records which model touched each edge; a `policy_hash` drift → warn-to-re-run (the re-index-warning pattern).
4. **Budget caps (MVP).** Cumulative stamped `usd` over cap → `ESCALATE(budget)` (never silently continue or truncate). **G5 fix — precedence is defined:** the **USD cap is a hard ceiling** that emits `ESCALATE(budget)` regardless of remaining loop budget; loop-count exhaustion emits `ESCALATE(deadlock/infeasible)`. Two distinct reasons, checked USD-first.

**Deferred to v2:** the gateway (physical 403 via model-access-groups) for the strong multi-caller guarantee; per-key budgets; the two scoped up-cascades (Builder worker mid→frontier on failure; Router nano→mid on ambiguity), enabled once telemetry shows a cheap tier failing often; the `effort` matrix.

---

## Section 3 — Testing Agents Before Use

### 3.1 Decision

**Gate the deterministic parts as code; gate the stochastic parts as evals; no stochastic component enters the pipeline without both.** Test each ladder rung with the cheapest layer that can certify it. Offline eval **blocks the merge**; online (sampled judges + ~5% canary) **alerts/rolls back**, never inline.

**Reconciliation (Occam vs. coverage-fit — the sharpest split).** Occam: the LLM-judge harness, `pass^k`, pinned-judge provenance, `agent.yaml` manifests, and the A1–A6 merge-blocking gate are apparatus for a maturity we don't have; blocking merges on a freshly-invented flaky LLM-judge trains the team to disable the gate. Coverage-fit: nothing certifies the *assembled* pipeline (G1). **Both are right and both cuts apply:** defer the *fuzzy* gate, keep the *deterministic* gate — and add the end-to-end deterministic test Occam didn't ask for but which is *cheaper* than the LLM-judge harness it replaces at MVP.

### 3.2 The agentic test pyramid mapped to capability-ladder rungs

| Rung | Cheapest certifying layer | Blocks merge at MVP? |
|---|---|---|
| **tool** | contract test + **scope test** (respects read/write catalog) | yes |
| **micro-skill** | unit tests | yes |
| **skill** | unit + trajectory smoke | contract parts only |
| **subagent** | contract + guardrail + trajectory smoke | contract + guardrail parts |
| **agent** | eval (LLM-judge) + trajectory/replay + guardrail + verdict-contract at `pass^k` | **v2** (MVP: golden fixtures, report-only for fuzzy ones) |

### 3.3 The three deterministic tests that ship day one (model-free pytest)

These test the **spine**, the part that must not break:

1. **Verdict-contract tests.** Every stage's fixtures yield a schema-valid `PASS / BLOCKED(reason, target) / ESCALATE(reason)`; `reason` is in the closed enum (§ D18); `target` is a *legal back-edge*.
2. **Loop-budget termination (the single most important correctness test).** Drive a stage that *always* returns `BLOCKED` and assert the spine converges to `ESCALATE(infeasible)` within budget — no back-edge spins forever. Pure state-machine, no model.
3. **Must-fix G1 — end-to-end pipeline certification (A7).** A golden trajectory drives a fixture requirement Router→Merge with **mocked-deterministic agents**, asserting the *composition*: back-edges fire, the **veto AND-gate holds** (a Security BLOCK cannot be outvoted by a Reviewer PASS), budget escalates with correct precedence, and the terminal verdict is the expected one. This is the difference between "each part certified" and "the plane flies" — and it is *cheaper* than the LLM-judge suite, so it ships at MVP while the fuzzy evals wait.

### 3.4 Golden fixtures — human-authored, mostly report-only at MVP

Per agent, a handful of **human-authored** golden fixtures (never LLM-authored-and-trusted — LLM assertions drift toward the current implementation). Where possible use **exact/substring** assertions ("given this spec, the Test-Author output must contain a test for the stated acceptance criterion") and **run them, report them, block merge only on the deterministic contract tests.** Blocking on a fuzzy LLM-judge before we have real output to disagree with a golden about is how the gate gets disabled.

**The one fuzzy assertion that *is* hard and blocking:** the **veto fires on the poisoned fixtures — exactly 1.0, threshold-exempt, un-talk-out-able** (multi-turn escalation attempts still BLOCK). This is a *deterministic* assertion (scanner found the planted secret → BLOCK), not an LLM-judge, so it costs nothing to make hard.

### 3.5 The promotion gate — no agent goes live uncertified

The gate is **both** a CI check and a runtime twin:

- **CI (`check_agents.py`, model-free — it audits result artifacts, it does not run models).** MVP subset: **A1** every registered agent has a manifest with resolving suite paths · **A4** verdict-contract tests pass · **A6** loop-budget termination proof present · **A7** end-to-end golden green. Deferred to v2: **A2** thresholds met on this manifest version · **A3** guardrail/red-team suite (`injection_block == 1.0`, veto fired on every poisoned fixture) · **A5** provenance matches (eval-dataset SHA + judge-model == manifest; silent drift *fails*).
- **Runtime twin.** The spine's registry **refuses to instantiate** an agent whose running `(version, model, eval_dataset_sha)` ≠ the certified triple — the index-provenance-mismatch-raises pattern applied to agents. *This is the concrete meaning of "an eval failure blocks an agent from the live pipeline."*

**v2 anti-gaming (coverage-fit D15):** the LLM-judge is **pinned, version-stamped, and different from the agent under test**; `pass^k` (not `pass@1`) for the four core agents; a silent judge/data bump **fails** the gate. Simulated-user runs are a *pre-merge smoke signal, not a gate* (LLM-simulated users are unreliable proxies).

**Tooling:** pytest for the deterministic core; an eval runner (e.g. promptfoo / DeepEval / Inspect-class harness) for the v2 LLM-judge suites; wired into the same CI stage the repo already uses for `check_docs.py` / `check_copilot.py`, plus a runtime registry check.

---

## Section 4 — Packaging & Install

### 4.1 Decision

Ship as **one versioned distribution** = a **deterministic-core Python package** (spine + CLI, *no LLM SDK in core deps*) that contains a **plugin bundle** (agents/skills as folder-convention) and a **policy pack** (declarative YAML). **The core installs and unit-tests with zero credentials and zero model download** — the repo's "deterministic core is model-free, providers are lazy extras" discipline, generalized.

**Reconciliation (Occam).** The extras matrix, the versioned plugin-manifest `schema_version`/`min_spine` compatibility protocol, the container image, signed eval attestations, and the 8-row `doctor` are **v2** — governance for an install base of zero. **MVP = one package, `pip install -e ".[dev]"`, one entry point `sdd`.** Extras become worth it the day someone installs *without* dev; `doctor` grows a row at a time *as each subsystem becomes real*.

### 4.2 What the package contains

- **Spine + CLI** (deterministic core, model-free deps): the state machine, verdict type, artifact store, gates, tool-dispatch interceptor.
- **Plugin bundle** (folder-convention, manifest-optional): `agents/*.md` with valid frontmatter *is* an agent; `skills/*/SKILL.md` *is* a skill — the repo's existing `.claude/skills/` discovery model. Discovery is **fail-loud**: a missing `description`, a `model:` alias absent from the registry, or an ungranted tool → hard error at load (generalizing `check_copilot.py` C1–C6).
- **Policy pack** (`config/*.yaml`): `model-policy`, `gates`, `guardrails`, `eval`, `tools/catalog` — validated against shipped JSON Schema at load.

### 4.3 Config & secrets

Secrets are **env-only** (`SDD_*` via pydantic-settings) — never in YAML, never as CLI flags (the `PIPELINE_DOWNLOAD_*` discipline). Stage models are referenced by **alias** in `model-policy.yaml`; the concrete ID and the credentials never co-locate.

### 4.4 The `sdd doctor` / verify command

`doctor` and the runtime promotion gate share **one code path** (`spine.policy.eval_status(agent)`), so install-verify and runtime-promotion cannot disagree. **MVP rows** (grow the rest as subsystems land):

| Row | Asserts | MVP? | Ties to |
|---|---|---|---|
| `deps` | every config-required dep imports | yes | §2/§4 |
| `discovery` | every agent/skill has valid frontmatter; names unique; no dangling refs | yes | §3 |
| `policy` | policy YAML valid; every stage maps to a real agent; every tool a stage uses is in the catalog | yes | §1/§2 |
| `hitl` | the 2 mandatory human gates present & non-removable; loop budgets finite; back-edge targets real; each mandatory gate has an approver-role (G8) | yes | §1 |
| `pipeline` | the end-to-end golden (A7) is green | yes | §3/G1 |
| `models` | every alias resolves; creds present; 1-token reachability ping | v2 | §2 |
| `evals` | each agent's eval suite last ran and passed ≥ threshold (reads the eval cache) | v2 (hard gate) | §3 |
| `guardrails` | guardrail config validates; rails load; **veto lane present** | v2 | §1 |
| `provenance` | store/index provenance == spine schema version | v2 (WARN) | §0 |

`sdd doctor` exits 0 only if no ERROR row fails. `sdd verify` is `doctor` in CI form; `sdd version` prints spine + plugin + policy-hash + resolved aliases (the "what am I running" one-liner).

### 4.5 Versioning & provenance

One monotonic **`policy_hash`** stamped on every artifact (D17 resolution below): older→warn (re-run), newer→block (the `EMBED_FORMAT_VERSION` pattern). Commit the lockfile (`uv.lock`) — that is the whole reproducibility story until someone else builds it.

### 4.6 Install recipe

**MVP (one dev, one repo):**
```bash
git clone <repo> && cd sdd-agent
pip install -e ".[dev]"          # core + dev; no model download, no creds
sdd check                         # 5-row doctor: deps / discovery / policy / hitl / pipeline
cp .env.example .env              # secrets ENV-ONLY; stage models by ALIAS in config/model-policy.yaml
sdd run --requirement REQ-142     # spine drives Router → … → Merge gate
```

**Full (v2 — external adopter):**
```bash
uv tool install sdd-agent                                   # isolated global CLI
sdd init                                                     # scaffold ./.sdd/, copy editable policy pack, write .env.example
uv pip install "sdd-agent[guardrails,eval,azure,retrieval,mcp,tracing]"
cp .env.example .env
sdd doctor                                                  # full 9-row health; fails on any ERROR
sdd eval run --all && sdd doctor                            # populate the eval cache the promotion gate reads → green
sdd run --requirement REQ-142
```
Reproducibility floor (v2): a digest-pinned container running `uv sync --frozen --extra all` off the *same lockfile* as the pip install.

**G7 fix (one sentence):** the artifact store's provenance stamps **are** the trace — a span is a stage invocation keyed by `work_item_id` — so the v2 `[tracing]` extra is merely an OTLP exporter over the store, not a second telemetry system.

---

## Consolidated new decisions (D12–D18)

| # | Decision | Options | Recommendation (reconciled) |
|---|---|---|---|
| **D12** | HITL posture authority & anti-fatigue | (a) Router auto-sets tier vs. human-confirmed; (b) mandatory-gate floor; (c) telemetry auto-retune vs. human review | **MVP: no tiers — two hard human gates (Specifier, Merge).** Ratify the irreducible floor = {Specifier, Security veto, Merge}. Telemetry auto-retune is v2. Rule out per-tool-call synchronous approval by default and static `interrupt_before/after` — gates are earned by `ESCALATE`. |
| **D13** | Security-veto shape (the crux) | (a) hard AND-gate vs. scorer fused with Reviewer; (b) build integrated agent-firewall vs. deterministic scanners | **Hard, non-averaged AND-gate into Merge; runs isolated; BLOCK does not consume loop budget.** MVP scanner = semgrep/gitleaks (deterministic P0 detection); model-based firewall is v2. |
| **D14** | Model-routing enforcement locus | gateway 403 vs. spine echo-assertion; static vs. cascade-enabled | **MVP = spine-side echo assertion reading the provider-returned model id (Q3); fully static, no cascade.** Trust-critical floor (Specifier, Test-Author, Reviewer, Security veto) pinned frontier, no down-cascade. Gateway + cascade = v2. |
| **D15** | Agent-testing rigor & anti-gaming | (a) judge model pinned & ≠ agent; (b) `pass^k` vs `pass@1`; (c) goldens human vs. LLM-authored; (d) veto threshold-exempt | **MVP: deterministic verdict-contract + loop-termination + end-to-end golden block merge; human-authored golden fixtures report-only; veto == 1.0 hard.** LLM-judge (pinned, ≠ agent-under-test, `pass^k`) is v2. Goldens always human-owned; silent judge/data bump fails. |
| **D16** | Packaging shape & eval-attestation coupling | (a) one distribution vs. split; (b) policy editable-in-`./.sdd/` vs. hash-pinned; (c) hard eval gate + signed-attestation escape hatch | **One `sdd-agent` distribution. MVP: `pip install -e ".[dev]"`, editable policy, `evals` row stubbed.** v2: hard eval gate **with** signed-attestation escape hatch for air-gapped/no-creds installs. |
| **D17** | Unified `policy_hash` / `schema_version` bump protocol | one monotonic `policy_hash` vs. per-file versions | **One `policy_hash` for MVP** (you have 1–2 policy files, no cross-product to govern); per-file versioning only if re-cert churn proves painful. Older→warn, newer→block. |
| **D18** | Verdict-`reason` as one shared namespace | closed CI-enforced enum vs. growable plain `Enum` | **A plain Python `Enum`, seeded complete from this plan, grown by deliberate contract bump.** No standalone `check_*.py` enforcing it at MVP — the type checker already does; promote to a CI-governed contract once a third gate-author appears. Seed set (coverage-fit G6): `{injection, pii, insecure_code, ungrounded, model_policy, budget, uncertified_agent, schema, off_topic, contradiction, deadlock, human_reject, tool_scope, stale_checkpoint, infeasible}`. |

---

## MVP vs. full — per-section summary

| Section | MVP (ship now — topology + invariants) | Full (v2 — sophistication, on felt pain) |
|---|---|---|
| **1. HITL & guardrails** | 2 hard human gates (Specifier, Merge); `ESCALATE`-always-gates; advisory findings to a log; deterministic guardrails only (schema + gitleaks/PII regex + semgrep/bandit + reused `check_chunk`); **security veto as a hard AND-gate, no budget**; **tool-scope runtime interceptor**; content-addressed + optimistic-lock artifact store; stale-checkpoint re-validation; ambient ingestion sanitization | risk tiers + rubber-stamp telemetry auto-retuning; four review surfaces; per-tool `high`-Builder approval; model-based injection/faithfulness subagents; two-layer sandbox; red-team-tuned veto |
| **2. Model routing** | flat `{stage: model_id}` policy; **in-process echo assertion on the provider-returned model**; JSON-Schema validation; provenance stamp; USD-hard-ceiling budget with defined precedence | tier aliases + `allow:` lists + scoped up-cascade; gateway physical-403 + per-key budgets; standalone `check_model_policy.py`; effort matrix |
| **3. Testing** | verdict-contract + loop-termination + **end-to-end golden (A7)** block merge; human-authored golden fixtures report-only; veto==1.0 hard; `check_agents.py` A1/A4/A6/A7 + runtime cert-triple refusal | LLM-judge harness (pinned, ≠ agent, `pass^k`); A2/A3/A5 with provenance; red-team guardrail suites; online sampled judges + 5% canary + rollback |
| **4. Packaging** | one package, `pip install -e ".[dev]"`, `sdd run` + 5-row `sdd check`; fail-loud folder discovery; env-only secrets; one `policy_hash`; committed lockfile | extras matrix; `uv tool install` + `sdd init`; 9-row `doctor` with eval-cache gate + signed attestation; container image; `schema_version` upgrade path; `[tracing]` OTLP exporter over the store |

---

**One meta-point for the room.** The reconciliation rule did the work: **every conflict resolved to "topology now, intelligence later."** The two critics never actually disagreed about a single mechanism — Occam wanted less *sophistication* (tiers, judges, gateways, extras: all deferred, all correctly), coverage-fit wanted more *invariant coverage* (end-to-end certification, store integrity, named interceptor: all cheap, all kept). What ships at MVP is the repo's proven **`provenance + workspace-guard + check_*.py + typed-verdict`** quartet applied five times, plus three coverage-fit topology fixes (G1/G2/G3) that are *cheaper* than the sophistication we deferred. The 2-hour session is now three enforcement-locus calls (D14 gateway, D16 attestation, D13 veto — all resolved "MVP-deterministic, v2-model") and two integration ratifications (D17 one-hash, D18 seeded-enum), not a subsystem design exercise.