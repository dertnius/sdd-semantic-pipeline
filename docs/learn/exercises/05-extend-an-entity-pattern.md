# Exercise 05 — Extend the service-entity pattern (and measure the blast radius)

**Goal.** `enrichment.py::_SERVICE_PATTERN` recognizes PascalCase component names
by a fixed suffix list. Today that alternation is exactly:
`Service|Controller|Manager|Handler|Client|Server|Worker|Processor|Repository|Store|Cache|Queue|Bus|Gateway|Proxy|Registry|Resolver|Scheduler|Engine|Provider|Factory|Adapter|Decorator|Facade|Bridge|Middleware|Filter|Interceptor`.
`Orchestrator` and `Dispatcher` are missing, so `OrderOrchestrator` is invisible
to `extract_entities`. Add them, test it, then re-run the dump on a real
document to see what actually changed corpus-wide. Background:
[tour 03](../tours/03-enrichment.md).

**Difficulty:** medium

**You will learn**
- How a single regex alternation defines an extraction "schema" — and how to
  read one before touching it.
- The verify-before/verify-after loop: prove the gap, make the change, then
  measure the blast radius on real artifacts instead of assuming it.

## Before you start

```powershell
git checkout learn-exercises
```

Prove the gap (verified against the current code):

```powershell
.\.venv\Scripts\python.exe -c "from sdd_pipeline.enrichment import extract_entities; print(extract_entities('The OrderOrchestrator calls PaymentService.'))"
# prints: ['PaymentService']        <- OrderOrchestrator is missing
```

## Files

- `src/sdd_pipeline/enrichment.py` — `_SERVICE_PATTERN`
- `tests/test_enrichment.py` — `TestExtractEntities`

## Steps

1. Read `_SERVICE_PATTERN` and its comment. Note the shape: leading word +
   zero-or-more middle words + the suffix group. Your edit goes only in the
   suffix group; keep the alternation style of the existing lines.
2. Add `Orchestrator` and `Dispatcher`. Think about ordering inside the
   alternation: does it matter here? (The suffixes are anchored by a trailing
   `\b` and none is a prefix of another in a harmful way — but convince
   yourself.)
3. Add a test to `tests/test_enrichment.py::TestExtractEntities` in the style of
   `test_extracts_service_name`. The real signature is
   `extract_entities(text: str, extra_terms: Iterable[str] | None = None)`, so
   `extract_entities("The OrderOrchestrator calls PaymentService.")` is enough —
   assert **both** `"OrderOrchestrator"` and `"PaymentService"` are in the
   result. Expected after your change: `['OrderOrchestrator', 'PaymentService']`
   (the function returns a sorted list).
4. **Blast radius.** Re-dump the biggest corpus doc into a *fresh* directory and
   diff the entity lists against the pre-change artifacts from exercise 01:

   ```powershell
   $env:PYTHONUTF8 = "1"
   .\.venv\Scripts\python.exe src\sdd_pipeline\dump.py eval\corpus\sad-retailnexus-oms.md out\retailnexus-after
   git diff --no-index out\retailnexus\chunks.json out\retailnexus-after\chunks.json
   ```

   Predict the outcome before running. Then explain what you see.

<details>
<summary>Hint (blast-radius outcome)</summary>

The diff is **empty** — verified: no document in `eval/corpus/` contains a
PascalCase `*Orchestrator` or `*Dispatcher` token. RetailNexus's
`saga-orchestrator` is kebab-case, which the PascalCase-only `_SERVICE_PATTERN`
can never match (check `out\retailnexus\chunks.json`: it shows up only in the
`metadata.raw_entities` audit bucket, not in `entities`). That *is* the lesson: a change can be correct, tested, and still have
zero effect on your current corpus — you know that because you measured, not
because you assumed.
</details>

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_enrichment.py -q
```

Success: all green including your new test. Re-run the *Before you start*
one-liner — it now prints `['OrderOrchestrator', 'PaymentService']`.

## Cleanup

```powershell
Remove-Item -Recurse -Force out\retailnexus-after   # scratch artifact (out/ is gitignored anyway)
git add -A && git commit -m "learn: Orchestrator/Dispatcher service suffixes (exercise 05)"
# or: git checkout -- src/sdd_pipeline/enrichment.py tests/test_enrichment.py
```
