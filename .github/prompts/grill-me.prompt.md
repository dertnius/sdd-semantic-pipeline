---
mode: ask
description: Stress-test a plan or design by interviewing the user relentlessly until every branch of the decision tree is resolved.
---

# /grill-me — interview me about a plan or design

Port of the Claude `/grill-me` skill. Interview the user about their plan, design,
or change until you both reach shared understanding and every open branch of the
decision tree is resolved. The goal is to surface hidden assumptions and unmade
decisions **before** code is written.

## How to run it

1. **Get the plan.** Ask the user to state the change/design in a sentence or two if
   they haven't. Use `${selection}` or the open file as the subject when present.
2. **Ask one sharp question at a time.** Don't dump a checklist — probe the weakest
   point, get the answer, then follow that thread until it bottoms out before moving
   on. Prefer questions that have a concrete right/wrong answer over open-ended ones.
3. **Push on this repo's real decision points** when relevant:
   - Which module owns the change, and does it respect the boundaries in `CLAUDE.md`?
   - Deterministic core vs CLI-layer — which side does this live on?
   - New `PipelineConfig` field (dual v2/v1 branches + docs) or CLI flag (docs)?
   - Does it change `to_embed_text` (bump `EMBED_FORMAT_VERSION`, re-index)?
   - Model-free vs model path; lexical vs hybrid vs semantic; which extra it needs.
   - What's the test (fast/`slow`/`integration`)? What's the failure mode?
4. **Track the tree.** Keep a running list of resolved vs open questions; restate it
   when the user drifts. Stop when no open branch remains.
5. **Synthesise.** End with a tight summary of the decisions reached and any residual
   risks, ready to hand to `/code-review` or an implementation prompt.

## Notes

- Be relentless but constructive — you're pressure-testing the idea, not the person.
- If the user can't answer a question, that *is* the finding: flag it as an unmade
  decision rather than papering over it.
