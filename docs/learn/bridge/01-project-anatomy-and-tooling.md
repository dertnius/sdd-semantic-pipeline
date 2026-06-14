# 01 — Project anatomy and tooling (for a .csproj native)

Open [pyproject.toml](../../../pyproject.toml) and keep it visible while reading. It is one file
playing the role of `.csproj` + `Directory.Build.props` + `nuget.config` + editorconfig/analyzer
settings combined. Walk it top to bottom.

## `[project]` ≈ the `.csproj` PropertyGroup + PackageReferences

```toml
[project]
name = "sdd-pipeline"
requires-python = ">=3.11"
dependencies = [
    "panflute>=2.3",
    ...
    "typer>=0.12",
]
```

`dependencies` is the `<PackageReference>` list. There is no lock file here (no
`packages.lock.json` equivalent committed) — version ranges resolve at install time.

## `[project.optional-dependencies]` ≈ conditional PackageReferences

Find the `dev`, `azure`, and `chroma` extras in the file. They behave like packages guarded by an
MSBuild `Condition`: installed only when you ask, e.g. `pip install -e ".[dev]"` or
`pip install ".[azure]"`. The code copes with their absence at runtime — see how
`embeddings.py::AzureOpenAIEmbedder._get_client` catches `ImportError` for the optional `openai`
package and prints the exact install command.

## `[project.scripts]` ≈ a `dotnet tool` command

```toml
[project.scripts]
sdd-pipeline = "sdd_pipeline.cli:app"
```

After install, `sdd-pipeline` is an executable shim on PATH (in `.venv\Scripts\`) that calls the
`app` object in [cli.py](../../../src/sdd_pipeline/cli.py) — the same way `<PackAsTool>` +
`<ToolCommandName>` expose a console app. More on `app` in page 06.

## venv ≈ a self-contained, per-project runtime

A virtual environment (`.venv/`) is a private copy of the Python interpreter plus its own
`site-packages` — think self-contained deployment plus a per-project global packages folder. There
is no machine-wide GAC-style resolution: whichever `python.exe` you run determines which packages
exist. That's why [CLAUDE.md](../../../CLAUDE.md) insists on `.\.venv\Scripts\python.exe` —
"activation" just prepends `.venv\Scripts` to PATH so bare `python`/`pytest` hit this copy.

## `pip install -e ".[dev]"` ≈ ProjectReference instead of PackageReference

The `-e` (editable) flag links your working tree into the venv instead of copying a built
artifact — edits to `src/sdd_pipeline/*.py` are live immediately, like a `<ProjectReference>` vs a
published NuGet. Note the *src layout*: `[tool.setuptools.packages.find] where = ["src"]` means
the importable package is `src/sdd_pipeline/`, not the repo root.

## `[tool.*]` tables ≈ analyzer + test settings

- `[tool.pytest.ini_options]` — read it: `testpaths = ["tests"]`, custom `markers` (`slow`,
  `integration`), and `pythonpath = ["src"]` — the line that makes `import sdd_pipeline` work in
  tests *even without* installing (it injects `src/` like adding an assembly probe path).
- `[tool.coverage.report]` — `fail_under = 70` is a hard coverage gate (build fails below 70%),
  and `[tool.coverage.run]` `omit = ["*/cli.py"]` excludes the CLI like `[ExcludeFromCodeCoverage]`.
- `[tool.ruff]` ≈ Roslyn analyzers + `dotnet format` in one tool: `line-length = 100`,
  `target-version = "py311"`, rule `select` list, `quote-style = "double"`.
- `[tool.mypy]` ≈ an *opt-in* static type checker. Python doesn't enforce type annotations at
  runtime (page 03); mypy is the compiler-style pass you must run explicitly. Note
  `strict = false` and `exclude = ["tests/"]` — this repo type-checks `src/` only.

## The commands you'll actually type

[CLAUDE.md](../../../CLAUDE.md) has the full list; the core loop is:

```powershell
sdd-pipeline check          # environment sanity (pandoc, packages, env vars)
pytest -m "not slow"        # fast unit tests — no pandoc, no model download
```

pytest selector cheat-sheet vs xUnit/`dotnet test`:

| pytest | dotnet test analogue |
|---|---|
| `pytest -m "not slow"` | `--filter "Category!=slow"` (markers, page 07) |
| `pytest tests/test_enrichment.py -k "entities"` | `--filter "FullyQualifiedName~entities"` |
| `pytest -v` | detailed verbosity (already on via `addopts = "-v --tb=short"`) |

Why `-m "not slow"` matters here specifically: the `slow` marker gates anything needing the pandoc
binary or a real embedding model (a ~1.3 GB download on first use — see
`embeddings.py::EmbeddingModel`, whose docstring says the model downloads on first use).

## Try it

1. Run `sdd-pipeline check` and map each table row to the dependency that provides it in
   `[project] dependencies` / the extras.
2. Run `pytest -m "not slow" --cov=sdd_pipeline --cov-report=term-missing` and find the
   `fail_under` gate firing (or not) at the bottom of the output.

## Self-check

1. You add `import chromadb` at the top of a new module in `src/sdd_pipeline/`. A teammate who
   installed with plain `pip install -e .` now gets `ImportError` on *every* command. Which
   pyproject section explains why, and what pattern does `vector_store.py::ChromaVectorStore.__init__`
   use to avoid this?

<details><summary>Answer</summary>

`chromadb` lives in `[project.optional-dependencies]` under `chroma` (and `dev`), so a base
install doesn't have it. `ChromaVectorStore.__init__` imports it lazily *inside* the constructor
in a `try/except ImportError` and re-raises with the install hint
(`pip install "sdd-pipeline[chroma]"`), so the module itself always imports cleanly. Page 05
covers the pattern.
</details>

2. Tests import `sdd_pipeline` successfully even on a machine where `pip install -e .` was never
   run. Which single pyproject line makes that possible?

<details><summary>Answer</summary>

`pythonpath = ["src"]` in `[tool.pytest.ini_options]` — pytest adds `src/` to the import path, so
the src-layout package resolves without installation.
</details>
