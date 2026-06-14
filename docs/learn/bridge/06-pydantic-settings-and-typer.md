# 06 — pydantic-settings (config) and typer (CLI)

## `BaseSettings` ≈ `IConfiguration` + `IOptions<T>` in one class

Open [config.py](../../../src/sdd_pipeline/config.py)::`PipelineConfig`. Each annotated field is
simultaneously the options-class property, the configuration key, and the validation rule. The
binding chain is declared once at the bottom of the class:

```python
model_config = SettingsConfigDict(
    env_prefix="PIPELINE_",
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)
```

Field name → `PIPELINE_<NAME>` env var → `.env` file → declared default, with type coercion and
validation on construction — what you'd assemble in C# from `ConfigurationBuilder`
(`.AddEnvironmentVariables("PIPELINE_")`, a dotenv provider), `services.Configure<T>()`, and
DataAnnotations validation. Three real fields to study:

- `embedding_model: str = Field(default="BAAI/bge-large-en-v1.5", description=...)` — plain
  string with a default; `PIPELINE_EMBEDDING_MODEL` overrides it.
- `entity_terms: list[str] = Field(default_factory=list, ...)` — a **complex-typed** setting:
  pydantic-settings parses the env var as JSON, so `PIPELINE_ENTITY_TERMS='["KPO", "XCom"]'`
  becomes a real `list[str]`. Proof: `tests/test_config.py::test_env_json_array_parsed`. There is
  no `Environment` provider analogue for this in C# — closest is binding a JSON section.
- `vector_store_backend: str = Field(default="memory", ...)` — note validation of the *value* is
  deferred to `vector_store.py::make_vector_store`, which raises `ValueError` on unknown backends
  (a fail-fast the CLI surfaces; see `cli.py::index`'s `_ = pipeline.store` probe).

`Field(default=..., description=...)` ≈ DataAnnotations (`[Display(Description=...)]` +
default-value initializer): the description is machine-readable metadata, kept next to the field.

## THE DUAL-BRANCH TRAP — read this twice

`config.py` contains **two complete `PipelineConfig` classes**. The whole module is:

```python
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class PipelineConfig(BaseSettings):
        ...  # ~20 Field(...) declarations

except ImportError:
    # Fallback for pydantic v1 or missing pydantic-settings
    from pydantic import BaseSettings  # type: ignore[assignment, no-redef]

    class PipelineConfig(BaseSettings):  # type: ignore[no-redef]
        pandoc_from_format: str = "gfm"
        ...  # the same fields, restated as plain defaults
```

Only one branch ever defines the class on a given machine (your venv has pydantic-settings v2, so
you will *always* exercise the first branch and *never* notice the second drifting). **Every new
config field must be added to BOTH classes**, or the code works for you and silently falls back to
a missing-attribute crash for anyone on the v1 path. [CLAUDE.md](../../../CLAUDE.md) calls this out;
it is also exercise 04's trap. Diff the two field lists now — convince yourself they currently
match (rrf_k, hybrid_candidate_pool, inventory_enrichment... all duplicated).

## typer ≈ System.CommandLine, driven by function signatures

[cli.py](../../../src/sdd_pipeline/cli.py) builds the CLI from decorated functions:
`app = typer.Typer(name="sdd-pipeline", ...)`, then `@app.command()` per verb. Where
System.CommandLine has you construct `Command`/`Option<T>` objects and wire handlers, typer reads
the **signature**: parameter name → option name, annotation → parser/type, default →
`typer.Argument`/`typer.Option` metadata. The real `cli.py::search` (trimmed):

```python
@app.command()
def search(
    query: str = typer.Argument(..., help="Natural-language search query."),
    index_dir: str = typer.Option("./build/index", "--index", "-i", help="Vector index path."),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    ...
    hybrid: bool = typer.Option(False, "--hybrid", "-H", help="Fuse dense + lexical ..."),
) -> None:
```

`...` (Ellipsis) as the default means *required* — `Arity.ExactlyOne` with no default. A `bool`
option becomes a flag. `--help` text is generated from the `help=` strings. Note the body's first
move: build a `PipelineConfig(**overrides)` from the CLI flags — CLI args are just one more
configuration source layered over env/.env, like command-line config providers in .NET. Also note
`raise typer.Exit(1)` ≈ setting the process exit code, and that the heavyweight imports
(`from .pipeline import SemanticPipeline`) happen *inside* each command body — page 05's lazy
import pattern keeping `--help` fast.

The binding from page 01 closes the loop: `[project.scripts] sdd-pipeline = "sdd_pipeline.cli:app"`
makes the installed `sdd-pipeline` executable invoke this `app` object.

`rich` ≈ Spectre.Console, near 1:1: `cli.py`'s `Console()`/`console.print("[red]...[/red]")` is
`AnsiConsole.MarkupLine`, `rich.table.Table` (see the results table in `search`) is Spectre's
`Table`, and `rich.progress.track(md_files, ...)` is `Progress` around a `foreach`.

## Self-check

1. You add `rerank_top_n: int = Field(default=20, description="...")` to the first
   `PipelineConfig`, run the full test suite locally — green — and ship. Who breaks, when, and
   why did no test catch it?

<details><summary>Answer</summary>

Anyone whose environment lacks `pydantic-settings` (the v1 fallback branch): their
`PipelineConfig` has no `rerank_top_n`, so the first read raises `AttributeError` (or
`PipelineConfig(rerank_top_n=...)` fails). No test catches it because only one branch is
importable per interpreter — `tests/test_config.py`'s docstring says exactly this: "these
exercise whichever is active". The fix is discipline: add the field to both classes.
</details>

2. In `cli.py::search`, `backend` is declared `str | None = typer.Option(None, ...)` while
   `provider` is `str = typer.Option("local", ...)`. Read the comment above the
   `if backend is not None:` block — why must `backend`'s default be `None` rather than
   `"memory"`?

<details><summary>Answer</summary>

`None` lets the code distinguish "flag omitted" from "flag given". When omitted, no override is
put into `PipelineConfig(**overrides)`, so the env var `PIPELINE_VECTOR_STORE_BACKEND` (or the
field default) still wins. A `"memory"` default would silently override the user's env
configuration on every run — the classic precedence bug between config sources.
</details>
