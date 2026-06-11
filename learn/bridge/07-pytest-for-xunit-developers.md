# 07 — pytest for xUnit developers

## Discovery by naming, assertion by `assert`

No `[Fact]`. pytest collects files matching `test_*.py` under `testpaths = ["tests"]`
([pyproject.toml](../../pyproject.toml)), then functions/methods named `test_*` (classes named
`Test*` are just grouping — no shared instance state by default, unlike xUnit's
per-test-class-instance). This repo keeps tests 1:1 with modules: `pipeline.py` ↔
`tests/test_pipeline.py`, etc.

Assertions are the bare keyword: `assert result == fake_chunks`. pytest rewrites the bytecode so a
failure prints both operands, diffs of lists/dicts, and intermediate values — `Assert.Equal`'s
expected/actual output, but for *any* expression. Exceptions:
`with pytest.raises(ValueError, match="provenance mismatch"):` ≈ `Assert.Throws<ValueError>` plus
a message regex (real use: `tests/test_pipeline.py::TestSearch.test_search_raises_on_provenance_mismatch`).

## Fixtures ≈ constructor injection, resolved by parameter *name*

Where xUnit injects via constructor + `IClassFixture<T>`, pytest matches **test parameter names**
to registered fixture functions. Open [tests/conftest.py](../../tests/conftest.py): module-level
sample data (`SAMPLE_MARKDOWN`, a hand-crafted `SAMPLE_AST` matching pandoc 3.x output) and four
fixtures — `sample_md_file`, `sample_ast`, `sample_document_model`, `sample_chunks`:

```python
@pytest.fixture
def sample_md_file(tmp_path: Path) -> Path:
    """Write SAMPLE_MARKDOWN to a temp file and return its path."""
    p = tmp_path / "auth-service.md"
    p.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    return p
```

Any test declaring a `sample_md_file` parameter gets that value; fixtures compose (this one itself
requests `tmp_path`, a **built-in** fixture giving a unique temp directory per test — disposable
`TestContext` directory, cleaned up for you). `conftest.py` is auto-discovered for its directory
tree: every file under `tests/` can use these fixtures with **no import** — a per-directory shared
fixture assembly, by convention.

## `parametrize` ≈ `[Theory]`/`[InlineData]`; markers ≈ `[Trait]`

[tests/test_enrichment.py](../../tests/test_enrichment.py)::`TestClassifySectionType.test_known_titles`
runs ~35 title→type cases off one function:

```python
@pytest.mark.parametrize(
    "title, expected",
    [
        ("Overview", SectionType.OVERVIEW),
        ("ADR-004: Use JWT", SectionType.DECISION),
        ...
    ],
)
def test_known_titles(self, title: str, expected: SectionType):
```

Each tuple is an `[InlineData(...)]` row, reported as a separate test. Markers are `[Trait]` +
filterability: `slow` and `integration` are *declared* in `[tool.pytest.ini_options] markers` and
applied like `@pytest.mark.slow` on `tests/test_pipeline.py::TestProcessFileIntegration` (note it
stacks with `@pytest.mark.skipif(not _pandoc_ok(), ...)` — a runtime skip condition). `-m "not slow"`
is your `dotnet test --filter`.

## monkeypatch and mocker — the Moq corner

`monkeypatch` (built-in fixture) is scoped, auto-reverting mutation of env/attributes — things C#
would need abstraction seams for. Real uses to read:

- `tests/test_config.py::TestEntityTerms.test_env_json_array_parsed` —
  `monkeypatch.setenv("PIPELINE_ENTITY_TERMS", '["KPO", "XCom"]')`, then constructs the config.
- `tests/test_ast_parser.py::TestPandocVersion.test_raises_when_not_found` —
  `monkeypatch.setenv("PATH", "")` to simulate missing pandoc (reverted after the test, so the
  rest of the suite still finds it).
- `tests/test_html_to_gitlab_md.py::_install_fake_converter` —
  `monkeypatch.setattr(h2m, "convert_file", fake_convert_file)`: swapping a *module-level
  function*, the move that replaces an interface-extraction refactor in C#.

`mocker` comes from the `pytest-mock` dev dependency, wrapping `unittest.mock` ≈ Moq:
`mocker.MagicMock()` ≈ `new Mock<T>().Object` (auto-stubbing every member),
`.assert_called_once()` ≈ `mock.Verify(..., Times.Once)`. The showcase fixture is
`tests/test_vector_store.py::patched_store`, which builds a `ChromaVectorStore` via
`ChromaVectorStore.__new__` (allocate **without running `__init__`**) and wires `MagicMock`
client/collection in — so Chroma tests run with chromadb not even installed. Many tests here also
use `unittest.mock.patch` directly as a context manager
(`with patch("sdd_pipeline.pipeline.generate_ast") as mock_ast:` in
`tests/test_pipeline.py::TestProcessFile.test_calls_all_stages`) — same machinery, no fixture.

## The keystone: inject mocks at the seam

`tests/test_pipeline.py::_make_pipeline` is the pattern everything else builds on:

```python
def _make_pipeline(tmp_path: Path, **config_overrides) -> SemanticPipeline:
    config = PipelineConfig(
        chroma_persist_dir=str(tmp_path / "chroma"),
        embedding_model="all-MiniLM-L6-v2",
        **config_overrides,
    )
    return SemanticPipeline(
        config=config,
        embedding_model=_mock_embedder(),
        vector_store=_mock_store(),
    )
```

`_mock_embedder()` is a `MagicMock` whose `embed_chunks.side_effect` (≈ Moq's
`.Returns((chunks) => ...)`) fabricates zero-vectors of the right count. Because
`SemanticPipeline.__init__` accepts protocol-typed optionals (page 03) and only lazily creates
real ones (page 05), the entire orchestration layer — indexing, provenance checks, hybrid fusion
(`TestSearch.test_hybrid_fuses_lexical_signal`) — is tested without pandoc, a model, or a vector
DB. Then verification reads naturally: `pipeline._store.add_chunks.assert_called_once()`.

## Self-check

1. A test method signature is `def test_x(self, tmp_path, sample_chunks):`. Where do those two
   arguments come from, given the test file contains no import for either?

<details><summary>Answer</summary>

By name-based fixture resolution: `tmp_path` is pytest's built-in temp-directory fixture;
`sample_chunks` is found in `tests/conftest.py`, which pytest auto-discovers for everything under
`tests/` — no imports, no registration. The closest C# mental model is DI resolving constructor
parameters, keyed by parameter *name* instead of type.
</details>

2. `tests/test_vector_store.py::patched_store` creates the store with
   `ChromaVectorStore.__new__(ChromaVectorStore)` instead of `ChromaVectorStore(...)`. Why is that
   necessary, and what's the C#-world analogue of what it skips?

<details><summary>Answer</summary>

`__init__` contains the guarded `import chromadb` plus real client construction — calling it would
require chromadb installed and would create a persistent client. `__new__` allocates the instance
without running the constructor (≈ `FormatterServices.GetUninitializedObject` /
`RuntimeHelpers.GetUninitializedObject`), letting the fixture wire `_client`/`_collection` to
MagicMocks directly and test the store's logic in isolation.
</details>
