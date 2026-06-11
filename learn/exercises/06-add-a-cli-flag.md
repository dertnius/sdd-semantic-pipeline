# Exercise 06 — Add a `--json` flag to the search command

**Goal.** `cli.py::search` always renders results as a rich table — fine for a
human, useless for piping into `jq` or another tool. Add a `--json` flag that
prints the results as a JSON array instead. You'll touch a typer command
signature, decide what a `SearchResult` should look like as JSON, and test the
command without ever loading an embedding model. Background:
[tour 10](../tours/10-pipeline-orchestrator-and-cli.md) and
[bridge 06](../bridge/06-pydantic-settings-and-typer.md).

**Difficulty:** medium-hard

**You will learn**
- How typer boolean options are declared (read a real one first).
- How to test a CLI command whose heavy dependency you must fake — typer's
  `CliRunner` + `monkeypatch.setattr`.

## Before you start

```powershell
git checkout learn-exercises
```

## Files

- `src/sdd_pipeline/cli.py` — `search`
- `tests/test_cli.py`

## Steps

1. Read `cli.py::search`. The flag style to copy is the existing
   `hybrid: bool = typer.Option(False, "--hybrid", "-H", help=…)` parameter.
   Add `json_out: bool = typer.Option(False, "--json", help=…)` (the Python
   name can't be `json` — the command body does `import json`-style work and
   you'd shadow it).
2. Decide the JSON shape. `vector_store.py::SearchResult` has fields
   `chunk_id`, `content`, `metadata` (a dict), `distance`,
   `fused_score`, plus the computed `score` property (fused score when hybrid,
   else `1 - distance`). A reasonable record: `score`, `breadcrumb` and
   `section_type` (both live in `r.metadata`), `content`, `chunk_id`.
3. In the command body, branch *before* the rich table is built. Two output
   rules: print with `print()` or `console.print_json()`, and keep the output
   machine-clean — no banner lines mixed into stdout. Note `json.dumps`
   defaults to `ensure_ascii=True`, which conveniently sidesteps the Windows
   cp1252 console problem documented in CLAUDE.md. Decide what `--json` prints
   when there are no results (`[]` is kinder to a pipe than "No results.").
4. Test it in `tests/test_cli.py`. The house pattern: a module-level
   `runner = CliRunner()` and `result = runner.invoke(app, [...])` (see
   `TestExportValidation::test_rejects_unknown_format`). There are **no**
   existing `search` tests — the export tests get away without mocks because
   `export` is model-free; `search` is not, so you must fake the pipeline:
   - The command body does `from .pipeline import SemanticPipeline` *inside the
     function*, so patching the source attribute works:
     `monkeypatch.setattr("sdd_pipeline.pipeline.SemanticPipeline", FakePipeline)`.
     In-repo precedent for fake-out-the-heavy-call-then-invoke:
     `tests/test_html_to_gitlab_md.py::_install_fake_converter` does
     `monkeypatch.setattr(h2m, "convert_file", fake_convert_file)` before the
     `TestConvertCli` tests call `runner.invoke(app, ["convert", …])`.
   - Your fake needs exactly what the command touches: a `store` attribute with
     a `count` (non-zero, to skip the empty-index warning) and a
     `search(...)` method returning a list of real
     `sdd_pipeline.vector_store.SearchResult` objects (build one with a
     `metadata={"breadcrumb": …, "section_type": …}` and a `distance`).
   - Assert `json.loads(result.output)` round-trips to your expected list —
     parsing the output *is* the test that nothing else leaked into stdout.

<details>
<summary>Hint</summary>

A minimal fake, accepting-and-ignoring the constructor kwargs the command passes
(`config=…`):

```python
class _FakeStore:
    count = 1

class _FakePipeline:
    def __init__(self, *a, **kw): self.store = _FakeStore()
    def search(self, *a, **kw): return [SearchResult(chunk_id="c1", content="hello",
        metadata={"breadcrumb": "A > B", "section_type": "api"}, distance=0.25)]
```

`SectionType(section_type)` and the overrides dict run before your fake is
constructed — pass no `--section-type` and the defaults are all safe.
</details>

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -q
.\.venv\Scripts\sdd-pipeline.exe search --help
```

Success: tests green (5 fast tests today, plus yours), and `--help` lists your
`--json` flag alongside `--hybrid`.

## Cleanup

```powershell
git add -A && git commit -m "learn: --json output for search (exercise 06)"
# or: git checkout -- src/sdd_pipeline/cli.py tests/test_cli.py
```
