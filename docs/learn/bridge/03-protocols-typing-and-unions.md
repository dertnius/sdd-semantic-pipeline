# 03 — Protocols, typing, and unions

## `Protocol` ≈ interface, but structural (Go-style)

A C# `interface` is *nominal*: a class implements `IEmbedder` only if it declares `: IEmbedder`.
A Python `Protocol` is *structural*, like Go interfaces: anything with matching method shapes
satisfies it, no declaration anywhere. This repo has exactly two such seams — open both:

[embeddings.py](../../../src/sdd_pipeline/embeddings.py)::`EmbedderProtocol`:

```python
@runtime_checkable
class EmbedderProtocol(Protocol):
    def embed_chunks(self, chunks: list[SemanticChunk]) -> list[list[float]]: ...
    def embed_query(self, query: str) -> list[float]: ...
```

and [vector_store.py](../../../src/sdd_pipeline/vector_store.py)::`VectorStoreProtocol`
(`add_chunks`, `search`, `get_corpus`, `delete_document`, `reset`, `set_provenance`,
`get_provenance`, plus a `count` property). Now grep the implementers:
`embeddings.py::EmbeddingModel` and `embeddings.py::AzureOpenAIEmbedder` never mention
`EmbedderProtocol` — neither do `ChromaVectorStore`/`MemoryVectorStore` mention
`VectorStoreProtocol`. They conform purely by shape; mypy checks conformance at the call sites
(e.g. the return type of `embeddings.py::make_embedder`). `@runtime_checkable` additionally
allows `isinstance(x, EmbedderProtocol)` — without it, a Protocol exists only for the type
checker. This is also why a `MagicMock` works as an embedder in tests: structural typing + duck
typing means "has the methods" is the entire contract.

## `str | None` ≈ `string?` — but nobody enforces it at runtime

In `models.py::ContentBlock` you saw `language: str | None = None`. The `T | None` union is the
nullable annotation, but unlike C#'s NRT warnings backed by the compiler, **CPython ignores
annotations entirely at runtime** — you can assign an `int` to `language` and nothing fires until
something downstream chokes. mypy (`mypy src/`, configured in
[pyproject.toml](../../../pyproject.toml)) is the only enforcement, and it's a separate, opt-in pass.
Generics map directly: `list[SemanticChunk]` ≈ `List<SemanticChunk>`,
`dict[str, list[str]]` ≈ `Dictionary<string, List<string>>` (see `Section.metadata`), and
`tuple[str, str]` ≈ a value tuple `(string, string)` (see `embeddings.py::embedder_identity`).

## `TYPE_CHECKING` ≈ a compile-time-only reference (cycle breaker)

Both seam modules start with:

```python
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

    from .config import PipelineConfig
```

`TYPE_CHECKING` is `False` at runtime and `True` only while mypy analyzes the file, so these
imports never execute. Two payoffs visible here: (1) `embeddings.py` can annotate
`-> SentenceTransformer` without importing the heavy ML package at module load; (2) it avoids
runtime import cycles — `pipeline.py` imports `embeddings.py`, which needs `PipelineConfig` only
for signatures. Think "reference needed by the type system but stripped from the executable". The
price: those names don't exist at runtime, which is why every module here also has
`from __future__ import annotations` (annotations become lazily-evaluated strings).

## Constructor injection without a container

Open [pipeline.py](../../../src/sdd_pipeline/pipeline.py)::`SemanticPipeline.__init__`:

```python
def __init__(
    self,
    config: PipelineConfig | None = None,
    embedding_model: EmbedderProtocol | None = None,
    vector_store: VectorStoreProtocol | None = None,
) -> None:
    self.config = config or PipelineConfig()
    self._embedder: EmbedderProtocol | None = embedding_model
    self._store: VectorStoreProtocol | None = vector_store
```

This is plain constructor injection — protocol-typed optional parameters with production
fall-backs (`make_embedder`/`make_vector_store`, created lazily; page 05) instead of an
`IServiceCollection` registration. See it exploited in
[tests/test_pipeline.py](../../../tests/test_pipeline.py)::`_make_pipeline`, which passes two
`MagicMock`s — no model download, no vector DB, and `TestLazyProperties.test_injected_embedder_used_directly`
proves the injected instance is used as-is. The two factory functions
(`embeddings.py::make_embedder`, `vector_store.py::make_vector_store`) are the "composition root".

## Type aliases ≈ `global using` alias

The last line of [models.py](../../../src/sdd_pipeline/models.py):

```python
EntityInventory = dict[str, list[EntityRecord]]
```

is `global using EntityInventory = Dictionary<string, List<EntityRecord>>;` — a readable name for
a shape, importable anywhere. Note `models.py::EntitySource` just above it: a `Literal[...]` alias
that constrains a `str` field to a closed set of values — the role a small enum would play in C#,
but checked only by mypy. Read its inline comments for the trust ordering.

## Self-check

1. `tests/test_pipeline.py::_mock_embedder` returns a bare `MagicMock`, which obviously never
   declares `EmbedderProtocol`. Why does `SemanticPipeline` accept and use it without any cast or
   adapter, in both the runtime and (with a caveat) the type checker's eyes?

<details><summary>Answer</summary>

Runtime: Python is duck-typed — the pipeline only ever calls `embed_chunks`/`embed_query`, and a
`MagicMock` synthesizes any attribute. Type-wise: `Protocol` conformance is structural, so no
declaration is needed; `MagicMock` itself is typed as `Any`, which mypy lets satisfy any
parameter. With `@runtime_checkable`, even `isinstance(mock, EmbedderProtocol)` would pass, since
the mock materializes the required attributes on access.
</details>

2. Move `from .config import PipelineConfig` out of the `if TYPE_CHECKING:` block in
   `vector_store.py`. The code still runs today. What did you lose, and what future change could
   it break?

<details><summary>Answer</summary>

You made the import real: `config.py` (and pydantic) now loads whenever `vector_store.py` does,
and you've created the *potential* for an import cycle — if `config.py` ever needed anything from
`vector_store.py` (even indirectly), module initialization would fail with a partially-initialized
module error. Under `TYPE_CHECKING` the dependency exists only for mypy, which resolves cycles
statically.
</details>
