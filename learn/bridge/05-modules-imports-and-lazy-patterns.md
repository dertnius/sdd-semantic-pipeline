# 05 — Modules, imports, and lazy patterns

## Module = file = a namespace that is also a singleton

A Python module is one `.py` file acting as both a namespace and a static-class-like singleton:
top-level code runs **once** on first import, and the resulting module object is cached
process-wide (`sys.modules`). Module-level constants like `embeddings.py::DEFAULT_MODEL` or
`enrichment.py::_SECTION_PATTERNS` are effectively `static readonly` fields initialized by a
static constructor. The leading-underscore convention (`_walk`, `_stable_doc_id`) is `internal`/
`private` by handshake, not enforcement.

A *package* is a directory with `__init__.py`. Open
[src/sdd_pipeline/__init__.py](../../src/sdd_pipeline/__init__.py): it re-exports the curated
public surface —

```python
from .config import PipelineConfig
from .models import ContentType, DocumentModel, SectionType, SemanticChunk
from .pipeline import SemanticPipeline
```

— so consumers write `from sdd_pipeline import SemanticPipeline` without knowing the file layout.
Think of it as the assembly's public API (`__all__` ≈ the list of `public` types). The `.config`
form is a *relative* import — "sibling module in this package" — used throughout `src/` (e.g. the
import block atop [pipeline.py](../../src/sdd_pipeline/pipeline.py)).

## `@property` lazy-init ≈ `Lazy<T>`

`pipeline.py::SemanticPipeline.embedder` (and the twin `.store`):

```python
@property
def embedder(self) -> EmbedderProtocol:
    if self._embedder is None:
        self._embedder = make_embedder(self.config)
    return self._embedder
```

`@property` makes a method read like a C# get-only property; the null-check-then-create body is
`Lazy<T>.Value` by hand. The *why* is test economics: constructing `SemanticPipeline` must be
free — no 1.3 GB model download, no vector DB touched — so tests can build pipelines casually and
inject mocks (`tests/test_pipeline.py::TestLazyProperties.test_embedder_not_created_at_init`
asserts `_embedder is None` right after construction). Same pattern one level down:
`embeddings.py::EmbeddingModel.model` defers the actual `SentenceTransformer(...)` load to first
use via `_load()`.

## Lazy/optional imports ≈ optional assembly loading with a graceful error

Imports are statements, so they can sit anywhere and be wrapped in `try/except`:

- [config.py](../../src/sdd_pipeline/config.py) wraps `from pydantic_settings import BaseSettings`
  in `try:` and, on `ImportError`, defines a whole *fallback class* using pydantic v1 — two
  alternative type definitions chosen at import time (page 06 covers the trap this creates).
- `vector_store.py::ChromaVectorStore.__init__` does `import chromadb` *inside the constructor*,
  catching `ImportError` and re-raising with the `pip install "sdd-pipeline[chroma]"` hint;
  `MemoryVectorStore.__init__` does the same for `langchain_core`. The module always imports; you
  pay only for the backend you instantiate. C# analogue: probing `Assembly.Load` for an optional
  plugin and failing with a helpful message — except here it's idiomatic and everywhere.

## `logging.getLogger(__name__)` ≈ `ILogger<T>` category convention

Top of `pipeline.py` and `vector_store.py`: `logger = logging.getLogger(__name__)`. `__name__` is
the module's dotted path (`sdd_pipeline.pipeline`), so loggers form the same namespace hierarchy
that `ILogger<SemanticPipeline>` categories give you — filterable by prefix, no DI needed.

## `pathlib.Path` ≈ `System.IO` unified into one object

[dump.py](../../src/sdd_pipeline/dump.py)::`_write` is the whole pitch in two lines:

```python
def _write(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
```

One type covers `Path.Combine` (the `/` operator: `out / "ast.json"`), `File.WriteAllText`
(`write_text`), `Directory.CreateDirectory` (`out.mkdir(parents=True, exist_ok=True)`), and
`File.Exists` (`md.is_file()`) — all visible inside `dump.py::main`.

## `if __name__ == "__main__":` ≈ the `Program.Main` guard

Bottom of dump.py:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

When a file is *run* (`python dump.py`), `__name__` is `"__main__"`; when *imported*, it's the
module path — so the guard makes one file both a library and an entry point.
`raise SystemExit(main())` ≈ `Environment.Exit(Main())` returning the exit code.

## Bonus gotcha, live in this repo: the docstring escape-sequence warning

dump.py's module docstring (the usage text) contains a literal Windows command:

```
    .\.venv\Scripts\python.exe dump.py path\to\your-file.md [out-dir]
```

A docstring is just a string literal, and in a normal string `\.`, `\S`, `\y` are *invalid escape
sequences* — compile it and Python warns: `dump.py:9: SyntaxWarning: invalid escape sequence '\.'`
(verified on this repo's venv). Worse, `\t` in `path\to` is a **valid** escape — it silently
becomes a TAB in the printed usage. The fix is a raw string, `r"""..."""` — the exact analogue of
a C# verbatim string `@"..."`, where backslashes are literal.

## Self-check

1. `vector_store.py` imports neither chromadb nor langchain at the top, yet its docstring promises
   "this module imports cleanly without either installed". Trace how `sdd-pipeline check` can
   still report chroma's availability. Where does each import actually happen?

<details><summary>Answer</summary>

The backend libraries are imported inside the constructors (`ChromaVectorStore.__init__`,
`MemoryVectorStore.__init__`) under `try/except ImportError`. `cli.py::check` independently does
its own `import chromadb` in a try/except just to report the version — availability probing and
lazy construction are separate uses of the same statement-level-import trick.
</details>

2. Why does the embedder live behind a `@property` instead of being built in
   `SemanticPipeline.__init__` (it would be simpler)? Name the two concrete consumers that depend
   on the laziness.

<details><summary>Answer</summary>

Construction must stay side-effect free: (1) unit tests build pipelines with mocks or assert
`_embedder is None` (`tests/test_pipeline.py::TestLazyProperties`); (2) the model-free commands —
`dump.py::main` ("embedder is lazy; nothing below touches it") and the `export`/`scan` CLI paths
via `scan_and_persist` — construct a full `SemanticPipeline` yet must never trigger the model
download. Exactly the deferral `Lazy<T>` exists for.
</details>
