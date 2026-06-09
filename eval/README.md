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
