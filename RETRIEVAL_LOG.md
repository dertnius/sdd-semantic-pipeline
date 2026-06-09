# Retrieval evaluation log

Append-only record of retrieval quality on the frozen golden set
(`eval/queries.yaml`) over the corpus (`eval/corpus/`). Produced by
`scripts/eval_retrieval.py`. This is the number the enrichment overhaul must move:
**"After M5" must beat "Baseline"** or the overhaul has not delivered.

## How to read this

- **Unit / relevance:** retrieval is over chunks; a query is credited when a
  retrieved chunk's *section* matches the golden set (see the harness header).
- **Metrics:** `recall@5`, `recall@10` (macro-averaged across queries) and `MRR`.
- **Same embedder both sides.** A delta is only meaningful when baseline and the
  later run used the *same* `embedder` line below. Mock runs are wiring checks,
  **not** quality baselines.
- **Interpretation rule:** a positive aggregate that hides a `lexical-control`
  regression is not a win. Treat a move smaller than the run-to-run noise band as
  noise — run the baseline twice unchanged to size that band.

---

## Wiring check — mock embedder (NOT a baseline)

- embedder: `mock/hashing-md5`  **(deterministic lexical hash — proves plumbing only)**
- corpus: 5 docs, 162 chunks; 22 queries; hybrid=False
- **aggregate**: recall@5=0.432  recall@10=0.477  MRR=0.348
- by category: cross-reference (recall@5=0.083 recall@10=0.083 MRR=0.167); lexical-control (recall@5=0.571 recall@10=0.714 MRR=0.405); paraphrase (recall@5=0.556 recall@10=0.556 MRR=0.426)

> Confirms the instrument works and is *sensitive*: a purely lexical embedder
> scores highest on `lexical-control` and collapses on `cross-reference` — exactly
> the gap the enrichment overhaul targets. recall@10=0.48 over 162 chunks also
> shows the metric has headroom (not saturated near 1.0). The absolute numbers are
> meaningless for quality; only the real-embedder Baseline below counts.

---

## Baseline (pre-overhaul) — PENDING

Not yet recorded: per your "no model" choice the harness prescribes no embedding
model, so the real baseline runs with **your** configured embedder over **your**
full corpus. To record it:

1. Drop your additional SDD docs into `eval/corpus/` (markdown; convert HTML via
   `sdd-pipeline convert` first). Add golden queries for them in
   `eval/queries.yaml`, then **freeze the file**.
2. Configure the embedder (whichever you'll use in production), e.g. Azure:
   ```powershell
   $env:PIPELINE_EMBEDDING_PROVIDER = "azure"
   # + PIPELINE_AZURE_OPENAI_ENDPOINT / _DEPLOYMENT / _API_KEY
   ```
   or a local model: `$env:PIPELINE_EMBEDDING_MODEL = "all-MiniLM-L6-v2"`.
3. Run (UTF-8 mode avoids the Windows cp1252 pandoc crash):
   ```powershell
   $env:PYTHONUTF8 = "1"
   python scripts/eval_retrieval.py --heading "Baseline (pre-overhaul)"
   ```
   This appends the Baseline block here with the embedder identity recorded.

Every later milestone re-runs the same command with a new `--heading`
(`"After M4"`, `"After M5"`, …) and compares back to this Baseline.
