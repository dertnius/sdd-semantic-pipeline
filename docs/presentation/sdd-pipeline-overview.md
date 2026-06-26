---
marp: true
theme: default
paginate: true
size: 16:9
header: 'SDD Semantic Pipeline'
style: |
  section { font-size: 27px; }
  h1 { color: #1f6feb; }
  h2 { color: #1f6feb; border-bottom: 2px solid #d0d7de; padding-bottom: 6px; }
  strong { color: #0a3069; }
  section.lead { text-align: center; }
  section.lead h1 { font-size: 1.7em; }
  .small { font-size: 0.74em; color: #57606a; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 26px; margin-top: 8px; }
  .before { background: #fff1f0; border-left: 7px solid #d1242f; padding: 10px 20px; border-radius: 8px; }
  .after  { background: #eafff0; border-left: 7px solid #1a7f37; padding: 10px 20px; border-radius: 8px; }
  .before h3 { color: #d1242f; margin: 4px 0 6px; }
  .after  h3 { color: #1a7f37; margin: 4px 0 6px; }
  .before ul, .after ul { font-size: 0.9em; line-height: 1.5; padding-left: 18px; }
  .cards { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 14px; }
  .card  { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 10px; padding: 12px 18px; }
  .card b { color: #1f6feb; font-size: 1.05em; }
  .card .small { display: block; margin-top: 4px; }
  .flow { text-align: center; font-size: 1.15em; margin-top: 36px; line-height: 2.2; }
  .box { background: #ddf4ff; border: 2px solid #1f6feb; border-radius: 10px; padding: 10px 18px; }
  .ok { color: #1a7f37; font-weight: 700; }
---

<!-- _class: lead -->
<!-- _paginate: false -->
<!-- _header: '' -->

# From SDD docs to an AI that *knows* them

### Before → After: making our design knowledge usable by agents

<span class="small">Software Design Documents  ·  semantic search  ·  grounded GitHub Copilot</span>

<!-- One sentence to open the room: "We already have the knowledge and we already have the AI agents — this project is the missing wire between them." -->

---

## The goal — connect two things we already have

We **already** own both halves. They just can't talk to each other yet.

<div class="flow">
<span class="box"><b>SDD knowledge</b><br><span class="small">SADs · ADRs · runbooks<br>(Confluence + Word)</span></span>
&nbsp;&nbsp; ➜ &nbsp; <span class="box"><b>This pipeline</b><br><span class="small">clean → enrich → index</span></span> &nbsp; ➜ &nbsp;
<span class="box"><b>AI agents</b><br><span class="small">that cite our<br>real decisions</span></span>
</div>

<br>

**Scope:** ingest our design-doc exports → turn them into one clean, searchable
corpus → expose it to AI agents. *It doesn't write the SDDs for you* — it makes
the ones we have findable and usable.

<!-- Keep scope tight and honest: this is the bridge, not a doc authoring tool. -->

---

## Before → After

<div class="cols">
<div class="before">

### ✖ Before

<ul>
<li>SDD content <b>trapped</b> in Confluence/Word — macros, layout cruft</li>
<li>Copilot writes ADRs with <b>zero grounding</b> → confident guesses</li>
<li>New design doc = <b>re-read 5 old ones</b> by hand first</li>
<li>Finding a past decision = keyword search + scrolling</li>
<li>Onboarding leans on a senior engineer's memory</li>
</ul>

</div>
<div class="after">

### ✔ After

<ul>
<li>Confluence + Word → <b>one clean Markdown corpus</b>, provenance kept</li>
<li>Agents <b>retrieve real, cited decisions</b> before they draft (RAG)</li>
<li>Ask a question → get the <b>exact section</b> (semantic + filtered)</li>
<li>Quality gates keep junk out, so agents ground on <b>good data</b></li>
<li>The corpus answers — <b>self-serve</b>, not a person</li>
</ul>

</div>
</div>

<!-- This is the slide to linger on. Read left, then right, line by line. -->

---

## Why a smart AI still gets *our* architecture wrong

An LLM knows the public world — **not our internal decisions**. Ask
*"how does our checkout saga compensate?"* and it returns a **confident guess**.

| | Path | Result |
|---|---|---|
| **AI alone** | question → the model's memory | ✖ plausible-sounding guess |
| **AI + RAG** | question → **retrieve from our docs** → answer | ✔ grounded, **cited** answer |

> **Why RAG is required:** Retrieval-Augmented Generation injects **our current,
> real** knowledge at answer-time — cheaper than re-training the model, never goes
> stale, and every answer is **auditable** because it shows its sources.

<!-- RAG = the agent looks things up in our corpus before it answers, instead of relying on memory. -->

---

## RAG is only as good as what it retrieves

Retrieve fuzzy or wrong passages → the agent **still hallucinates**. So before
indexing, the pipeline **enriches** every chunk — tagging *what it is* and *what
it connects to*.

| Plain chunk → **weak** retrieval | Enriched chunk → **precise** retrieval |
|---|---|
| just raw text | `type: decision` · breadcrumb · `entities: order.created` · `depends_on` / `exposes` |

> **Why enrichment is required:** it lets retrieval **filter to just the decisions**
> and answer cross-reference questions like *"which services consume
> `order.created`?"* — the precision that makes RAG **trustworthy** on dense SDDs.
> Without it, the agent gets vague context and guesses anyway.

<!-- This is the project's real moat: not "we chunked text", but "we tagged every chunk so retrieval is precise". -->

---

## The benefits

<div class="cards">
<div class="card">
<b>🎯 Grounded agents</b>
<span class="small">Copilot's ADR agent drafts from <b>our</b> decisions, not hallucinations — it cites the source doc.</span>
</div>
<div class="card">
<b>⚡ Answers in seconds</b>
<span class="small">Semantic search across the whole corpus, filterable to <i>just the decisions</i> — no more scrolling Confluence.</span>
</div>
<div class="card">
<b>🧹 One clean source of truth</b>
<span class="small">Confluence HTML <i>and</i> Word .docx → consistent Markdown with author/space/page kept as metadata.</span>
</div>
<div class="card">
<b>✅ Trustworthy &amp; cheap to run</b>
<span class="small">Quality gates block bad data from the index; most of it runs with <b>no AI model</b> — fast, in CI or a container.</span>
</div>
</div>

<!-- Four outcomes. Each maps to something proven on the next slide. -->

---

## It works today — and what we need

<span class="ok">Proven now (real numbers from the repo):</span>

- **Confluence + Word both convert** to clean Markdown, provenance intact.
- **5 real design docs → 107 enriched chunks in ~1 second** — with **no AI model** loaded.
- **664 automated tests passing** — built like a product, not a script.
- Grounding wired into **GitHub Copilot's ADR agent**; live demo runs in seconds.

<br>

> **The ask — a decision, not more code:**
> 1. Choose the embedding engine — **self-hosted (free)** vs **Azure (no setup, per-call cost)**.
> 2. Give us the **full SDD corpus** to ingest. The pipeline is ready for it.

<span class="small">Want the architecture, robustness gates, and test detail? → technical appendix deck (<code>sdd-pipeline-deep-dive.md</code>).</span>

<!-- Close on the ask so the meeting ends in a decision. -->
