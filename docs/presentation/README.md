# Presentation — SDD Semantic Pipeline (POC review)

For a technical management audience. Benefits-led, with a *Before → After* spine,
an **animated pipeline walkthrough** (file → cited answer), and the project's
**next-steps roadmap**.

> ### ▶ No installation required
> The decks are **single, self-contained HTML files** — all CSS and JavaScript are
> inline, with **no external assets, no CDN, no fonts to fetch**. Just
> **double-click the `.html` file to open it in any browser** (or drag it into a
> tab). No server, no Node, no build step — it works offline.

## Files

| File | What it is |
|---|---|
| **[`sdd-pipeline-presentation.html`](sdd-pipeline-presentation.html)** | **Present this — full deck (9 slides).** Self-contained, with the **animated pipeline journey** (click-to-step). Just open it in a browser. |
| **[`sdd-pipeline-presentation-short.html`](sdd-pipeline-presentation-short.html)** | **Short version (5 slides)** — title + RAG intent, Before/After, the animation, next steps, the ask. Same self-contained file. |
| [`sdd-pipeline-overview.pdf`](sdd-pipeline-overview.pdf) | Static handout / screen-share fallback (no animation) |
| [`sdd-pipeline-overview.md`](sdd-pipeline-overview.md) | Editable Marp source for the static PDF/HTML |
| [`sdd-pipeline-overview.html`](sdd-pipeline-overview.html) | Static HTML render of the Marp source |
| [`sdd-pipeline-deep-dive.md`](sdd-pipeline-deep-dive.md) | **Technical appendix** (architecture, robustness gates, test detail) — for Q&A |
| [`demo-script.md`](demo-script.md) | Live demo runbook — exact commands + real expected output |

## Full deck — the 9-slide flow

1. **Title** — from SDD docs to an AI that *knows* them
2. **The goal** — bridge SDD knowledge ↔ AI agents (scope)
3. **The journey** — animated walkthrough of every pipeline stage, file → cited answer (click to step)
4. **Before → After** — the core contrast
5. **Why RAG is required** — an LLM guesses about *our* architecture; RAG makes it retrieve + cite
6. **Why enrichment is required** — RAG is only as good as what it retrieves; enrichment makes retrieval precise
7. **The benefits** — 4 outcome cards
8. **What's next** — the roadmap (broader ingest → decision intelligence)
9. **The ask** — proof, then the decision needed

## Short deck — the 5-slide flow

1. **Title + RAG intent** — the one-line "why"
2. **Before → After**
3. **The journey** — the animation
4. **What's next** — the roadmap
5. **The ask**

## Present the animated deck

Open `sdd-pipeline-presentation.html` in any browser (double-click, or drag into a
tab). Press **F11** for full screen. Navigate with **→ / ← / space**, click to
advance, or the on-screen **‹ ›** buttons. Each slide reveals one point at a time
so the room follows along.

## Render / edit the static version

The Marp source (`sdd-pipeline-overview.md`) regenerates the PDF/HTML:

```bash
npx @marp-team/marp-cli docs/presentation/sdd-pipeline-overview.md --html --pdf
npx @marp-team/marp-cli docs/presentation/sdd-pipeline-overview.md --html --pptx   # editable PowerPoint
```

(Or use the **Marp for VS Code** extension: open the `.md`, preview, export.)

## Presenting notes

- Run the demo from `demo-script.md` **steps 0–3** live — model-free, finishes in
  seconds. Steps 4–6 (real search + Copilot grounding) need the model installed;
  the captured output on the proof slide covers them otherwise.
- Every metric is real and reproducible from this repo (see the runbook). **Don't**
  quote the mock-embedder retrieval numbers as quality — the real baseline is
  intentionally pending the embedder decision.
