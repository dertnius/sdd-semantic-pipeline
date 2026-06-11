# Exercise 07 — Tune hybrid search and measure it honestly

**Goal.** Stop guessing whether hybrid retrieval helps and produce a results
table: dense-only vs hybrid at three `rrf_k` values, scored with recall@5 and
MRR by the eval harness (`scripts/eval_retrieval.py` + the frozen golden set
`eval/queries.yaml`). No source files change — this is an experiment, and the
discipline is the deliverable. Background:
[tour 09](../tours/09-retrieval-and-hybrid-search.md) and
[eval/README.md](../../eval/README.md).

**Difficulty:** meaty

**You will learn**
- The harness's real interface: `--mock`, `--hybrid`, `--no-log`, `--top-k`,
  `--corpus`, `--queries`, `--out`, `--heading`, `--log`, `--manifest`.
- Which knob is a flag and which is an env var — and one wiring subtlety that
  makes `$env:PIPELINE_HYBRID_SEARCH` a no-op here.

## Before you start

```powershell
git checkout learn-exercises
$env:PYTHONUTF8 = "1"
```

Two rules for every run in this exercise:
- **Always pass `--no-log`.** Without it the harness appends to
  `RETRIEVAL_LOG.md` — that file is the project's honest score history; your
  experiments go in your own scratch notes, not in it.
- Hybrid on/off is the **`--hybrid` flag**, not the env var. Read
  `scripts/eval_retrieval.py::run_eval`: it calls
  `pipeline.search(..., hybrid=hybrid)` with an explicit `False` when the flag
  is absent, and `SemanticPipeline.search` only falls back to
  `config.hybrid_search` when `hybrid is None` — so `PIPELINE_HYBRID_SEARCH`
  is overridden. `rrf_k`, by contrast, has **no** harness flag and is reached
  only via `$env:PIPELINE_RRF_K` (the harness builds a fresh `PipelineConfig()`).

## Files

None to edit. Your numbers go in your own scratch notes.

## Steps

1. **Prove the wiring with the mock embedder** (deterministic hashing, no model):

   ```powershell
   .\.venv\Scripts\python.exe scripts\eval_retrieval.py --mock --no-log
   .\.venv\Scripts\python.exe scripts\eval_retrieval.py --mock --no-log --hybrid
   ```

2. Sweep `rrf_k` (still mock — seconds per run):

   ```powershell
   foreach ($k in 20, 60, 200) {
     $env:PIPELINE_RRF_K = "$k"
     .\.venv\Scripts\python.exe scripts\eval_retrieval.py --mock --no-log --hybrid
   }
   Remove-Item Env:PIPELINE_RRF_K
   ```

3. **Real numbers** with the small local model (cached from earlier work; ~80 MB
   download on first use otherwise):

   ```powershell
   $env:PIPELINE_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
   # repeat step 1 and step 2 WITHOUT --mock
   Remove-Item Env:PIPELINE_EMBEDDING_MODEL
   ```

4. Fill this table in your notes (recall@5 / MRR from the `AGGREGATE` line):

   | run | recall@5 | MRR |
   |---|---|---|
   | hybrid off | | |
   | hybrid on, rrf_k=20 | | |
   | hybrid on, rrf_k=60 (default) | | |
   | hybrid on, rrf_k=200 | | |

5. Interpret: (a) Did hybrid help the `lexical-control` category (queries that
   literally contain corpus terms) more than `paraphrase`? Why would BM25 do
   that? (b) Why does varying `rrf_k` barely move the numbers on this corpus?
   Think about what RRF's `1/(k + rank)` does when each scorer ranks only ~160
   chunks from 5 docs and the golden answers sit near the top of both lists.

<details>
<summary>Hint — expected output shape (real mock run, today's tree)</summary>

```
=== Retrieval evaluation ===
embedder: mock/hashing-md5
corpus:   5 docs   queries: 22
hybrid:   False

AGGREGATE  recall@5=0.386  recall@10=0.477  MRR=0.292

by category:
  cross-reference    recall@5=0.083  recall@10=0.083  MRR=0.083
  lexical-control    recall@5=0.429  recall@10=0.714  MRR=0.298
  paraphrase         recall@5=0.556  recall@10=0.556  MRR=0.426
```

Mock with `--hybrid` (rrf_k=60): `recall@5=0.614  MRR=0.572`, and
`lexical-control` jumps to `recall@5=1.000`. rrf_k sweep under mock:
MRR 0.580 (k=20) / 0.572 (k=60) / 0.572 (k=200) — recall identical. Mock
numbers prove plumbing only, **not** quality; your real-model numbers will
differ.
</details>

## Verification

Each run ends with the `=== Retrieval evaluation ===` report shown in the hint
(an `AGGREGATE` line plus three category lines), and `git status` shows **no
change to `RETRIEVAL_LOG.md`** (the regenerated `eval/corpus_manifest.json` is
gitignored).

## Cleanup

Nothing to commit — verify with `git status` that the tree is clean, and
`Remove-Item` any `PIPELINE_*` env vars you set.
