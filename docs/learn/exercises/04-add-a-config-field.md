# Exercise 04 — Add a config field (the dual-branch trap)

**Goal.** Add a new setting `search_default_results: int = 5` to
`PipelineConfig` so it can be overridden via `PIPELINE_SEARCH_DEFAULT_RESULTS`.
The catch this exercise exists for: `src/sdd_pipeline/config.py` defines
`PipelineConfig` **twice** — a pydantic-settings v2 class in the `try:` branch
and a pydantic-v1 fallback in the `except ImportError:` branch. A field added to
only one branch works on your machine and silently vanishes on another. CLAUDE.md
calls this out as a hard rule. Background:
[bridge 06](../bridge/06-pydantic-settings-and-typer.md) and
[tour 01](../tours/01-models-and-config.md).

**Difficulty:** medium

**You will learn**
- The try/except-ImportError dual-class pattern and why both branches must stay
  in sync ([bridge 05](../bridge/05-modules-imports-and-lazy-patterns.md)).
- How `env_prefix = "PIPELINE_"` maps a field name to an env var, and how to
  test that mapping with `monkeypatch.setenv`.

## Before you start

```powershell
git checkout learn-exercises
```

## Files

- `src/sdd_pipeline/config.py` — **both** `PipelineConfig` branches
- `tests/test_config.py`
- (stretch) `src/sdd_pipeline/cli.py` — `search`

## Steps

1. In the v2 branch, add the field with a `Field(default=5, description=…)` in
   the style of its neighbours (a "Search" comment banner keeps the file tidy —
   `hybrid_candidate_pool` is a good model). In the v1 fallback branch, add the
   plain `search_default_results: int = 5` line. Same name, same default, both
   branches.
2. Add tests to `tests/test_config.py`. The house pattern for env overrides is
   `tests/test_config.py::TestEntityTerms::test_env_json_array_parsed` — it
   takes the `monkeypatch` fixture and calls
   `monkeypatch.setenv("PIPELINE_ENTITY_TERMS", '["KPO", "XCom"]')` before
   constructing `PipelineConfig()`. Copy that shape: one test for the default
   (`== 5`), one with `monkeypatch.setenv("PIPELINE_SEARCH_DEFAULT_RESULTS", "9")`
   asserting `== 9` (pydantic coerces the string env value to `int`).
3. **Stretch (optional):** wire it into `cli.py::search`, whose `top_k` option
   is currently `typer.Option(5, "--top-k", "-k")`. The config object is only
   built *inside* the function, so the typer default can't read it — the usual
   trick is to default the option to `None` and resolve
   `top_k if top_k is not None else config.search_default_results` after
   `PipelineConfig(**overrides)` is constructed. Mind the type annotation
   (`int | None`) so mypy stays clean.

<details>
<summary>Hint</summary>

- Why does only one test run per machine? Only one branch is importable at
  runtime (the module docstring of `tests/test_config.py` says exactly this) —
  which is why forgetting the fallback branch isn't caught by your local tests.
  Sync is enforced by review, not by the suite.
- `monkeypatch.setenv` auto-undoes itself after the test — no `finally` needed
  (this is pytest's `IDisposable`-per-test, see
  [bridge 07](../bridge/07-pytest-for-xunit-developers.md)).
</details>

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
.\.venv\Scripts\python.exe -m mypy src
```

Success: all config tests pass including your two new ones; mypy still reports
`Success: no issues found in 23 source files` (it does today — keep it that
way). Quick manual proof of the env mapping:

```powershell
$env:PIPELINE_SEARCH_DEFAULT_RESULTS = "9"
.\.venv\Scripts\python.exe -c "from sdd_pipeline.config import PipelineConfig; print(PipelineConfig().search_default_results)"
Remove-Item Env:PIPELINE_SEARCH_DEFAULT_RESULTS
```

## Cleanup

```powershell
git add -A && git commit -m "learn: search_default_results config field (exercise 04)"
# or: git checkout -- src/sdd_pipeline/config.py tests/test_config.py src/sdd_pipeline/cli.py
```
