# Glossary — every term in plain words

New to these words? Read this. Each term has a one-line meaning and a simple comparison.
Think of the whole system as a **factory assembly line staffed by AI workers, with human
sign-offs and safety guards.** That picture explains most of the words below.

## The basics

| Term | In plain words |
|---|---|
| **AI model / LLM** | A computer program that reads and writes text like a person. The "brain." (e.g. Claude, GPT.) |
| **Agent** | An AI given **one job**, some tools, and instructions. It works in a loop until the job is done. → *one worker on the line.* |
| **Spec** (specification) | A clear written description of what we want, including how we'll know it's finished. → *a detailed order form.* |
| **Spec-Driven Development (SDD)** | A way of working: **write the spec first**, build to it, then **check the result against it.** |
| **Pipeline** | A fixed set of steps that work passes through from start to finish. → *the assembly line.* |
| **Greenfield / brownfield** | Greenfield = a brand-new project (blank page). Brownfield = existing, often messy code you must work inside. |

## The AI workers and their helpers (from smallest to biggest)

| Term | In plain words |
|---|---|
| **Tool** | A single instrument a worker uses — "run the tests," "search the code." Not smart on its own. |
| **Micro-skill** | A tiny, single-step recipe (one check or one small edit). Reliable and reusable. → *one checklist item.* |
| **Skill** | A longer recipe (several steps) a worker follows for a common task, e.g. "write a decision record." → *keeps everyone consistent.* |
| **Subagent** | A helper AI a main worker calls in for a specific piece, then gets the answer back. → *bringing in a specialist.* |
| **Capability ladder** | The rule: use the **smallest option that works** — tool → micro-skill → skill → subagent → agent. Don't call a specialist when a checklist will do. |

## How the work moves

| Term | In plain words |
|---|---|
| **Orchestrator / spine** | The plain, predictable **software** that moves work from step to step. It is **not AI**, so it always behaves the same way. → *the conveyor belt and the rules of the line.* |
| **Stage** | One step on the line (e.g. "write the spec," "write the code"). |
| **Workflow vs agent** | A *workflow* is fixed steps written in code (predictable). An *agent* decides its own steps (flexible). We use fixed steps for the overall route, and let AI be flexible **inside** each step. |
| **Verdict** | What each step reports: **PASS** (go on), **BLOCKED** (send back to fix), or **ASK A HUMAN**. |
| **Back-edge** | When a step fails, work is sent **back** to an earlier step to be fixed. |
| **Loop budget** | A limit on how many times work can bounce back-and-forth before a human is asked. → *stops it going forever (and running up cost).* |
| **Router** | The first step. It sorts the job (new vs old code, big vs small) and picks the route and which safety checks apply. |

## Keeping it safe (these never get removed)

| Term | In plain words |
|---|---|
| **Human-in-the-loop (HITL)** | A **person must approve** at important moments before work continues. → *a manager's sign-off.* |
| **Gate** | A checkpoint where work passes only if a rule — or a human — says OK. |
| **Guardrail** | An automatic safety rule that blocks bad or dangerous output. → *a spell-checker + a security scanner + "no merge without approval."* |
| **Security veto** | A safety check that can **stop everything on its own** if it finds a security problem. It can't be outvoted. |
| **Verification / Reviewer** | A **separate** checker that confirms the finished work truly matches the spec — not just "it runs." **The worker who built it never checks their own work.** |
| **Traceability** | A paper-trail linking each **requirement → decision → task → code → test**, so you can prove everything was covered. |
| **Assumption ledger** | A running list of "things we had to guess" and "open questions," kept visible so a human can catch a bad guess. |

## Building and running it

| Term | In plain words |
|---|---|
| **Model routing** | Choosing **which AI brain** to use per job — a small, cheap one for easy jobs; a big, powerful one for hard jobs. |
| **Testing / evaluation (eval)** | Trying an AI worker on **practice tasks with known answers** to see if it's good enough — *before* it touches real work. |
| **Promotion gate** | The rule that an AI worker is **not allowed into the real pipeline** until it passes its tests. |
| **Package / install** | Bundling the whole system so someone can set it up with a few commands. |

---

*Next: read [start-here.md](start-here.md) for the whole idea in one page.*
