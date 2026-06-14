# Retrieval evaluation

Measurement foundation for the enrichment overhaul. The overhaul's definition of
done is *"After M5 retrieval beats Baseline"* — this directory is how that number
gets produced honestly, **before** any enrichment code changes.

## Layout

| Path | What it is |
|---|---|
| `corpus/` | The eval corpus — real SDD markdown. Indexed fresh on every run. |
| `queries.yaml` | **Frozen** golden set: queries + the sections that should surface. |
| `corpus_manifest.json` | Generated `doc_id → relative-path` map (regenerated each run; `doc_id` is an absolute-path MD5, so it is *not* portable — the golden set keys on relative path instead). |
| `../scripts/eval_retrieval.py` | The harness. |
| `../RETRIEVAL_LOG.md` | Append-only score log; Baseline + each milestone. |

## Run

```powershell
$env:PYTHONUTF8 = "1"                       # avoid the cp1252 pandoc crash on Windows
python scripts/eval_retrieval.py            # real embedder from PipelineConfig
python scripts/eval_retrieval.py --mock --no-log   # wiring check, no model download
```

## Corpus provenance & disclosure

The seed corpus was produced by converting the SDD-shaped HTML in `.tmp_dc/`
(a sample Software Architecture Document, an Airflow AIP, plus dev guides) with
`sdd-pipeline convert`, plus the committed `adr-0001`. **Committing internal SDDs
is a disclosure decision you own.** If any corpus doc is confidential, add
`eval/corpus/` to `.gitignore` — the golden set references relative paths and
still works locally; it just won't run in CI without the files.

## Adding documents (recommended — grows the metric from directional to robust)

1. Convert HTML → markdown into `corpus/` (`sdd-pipeline convert`), or drop
   markdown in directly.
2. Add queries to `queries.yaml`. Each `expected` entry is `{doc, section}` where
   `doc` is the path relative to `corpus/` and `section` is a case-insensitive
   substring of the chunk breadcrumb (omit `section` for a doc-level match).
3. Keep the mix balanced: `cross-reference` (where enrichment should help),
   `paraphrase` (semantic lift), `lexical-control` (must not regress).
4. **Freeze** `queries.yaml` before recording a baseline — never edit it to chase
   a score.

## E2E test on real public documents

`tests/test_e2e_real_docs.py` proves the inventory-driven enrichment works on
**real** architecture docs (not just the synthetic SAD) and measures an A/B
retrieval comparison (enrichment on vs off). The corpus is fetched on demand —
nothing third-party is committed.

```powershell
$env:PYTHONUTF8 = "1"
python scripts/fetch_e2e_corpus.py          # downloads pinned docs -> eval/e2e_corpus/ (gitignored)
pytest tests/test_e2e_real_docs.py -q -s    # functional asserts + A/B score tables
```

| Path | What it is |
|---|---|
| `e2e_sources.yaml` | Manifest of real docs (pinned URLs + license/attribution). |
| `e2e_queries.yaml` | **Frozen** golden set for the e2e (GitLab / Azure / rcherara + RetailNexus). |
| `e2e_corpus/` | Fetched docs (gitignored — never committed). |
| `../scripts/fetch_e2e_corpus.py` | The only networked code; pipeline code stays local-only. |

The test is `slow` and **skips** when `e2e_corpus/` is empty, so default CI is
unaffected. It uses the deterministic hashing embedder (no download), so the A/B
measures enrichment's *lexical* contribution: it asserts no regression + a
recall@10 gain and prints both score tables. Semantic gain (e.g. directional
`depends_on`/`exposes`) needs a real model — point `PipelineConfig` at one and
reuse `scripts/eval_retrieval.py` to measure it.

## E2E chunk-hygiene proof (model-free, non-skippable)

`tests/test_html_to_gitlab_md_v3.py::TestEndToEndChunkHygiene` runs the **whole
model-free chain** — HTML → `convert` → chunk → Arm-1 hygiene gate — over the
*committed* rendered fixtures in `convert/examples/` (storage-format fixtures are
refused at the door). It asserts every produced chunk is clean (no markup/macro
residue) and that the fixtures still produce chunks. It needs pandoc but **no model
download** and **no fetched corpus**, so unlike the retrieval e2e above it is a
permanent regression net, not a skip-if-absent check.

> The chunk hygiene gate is on by default during `index`, so a *poisoned* chunk now
> **blocks its file** from the index (raises `ChunkQualityError`). When eval-indexing
> a messy corpus, set `PIPELINE_CHUNK_GATE=false` to measure retrieval over everything,
> or leave it on to measure only what passes the gate.
