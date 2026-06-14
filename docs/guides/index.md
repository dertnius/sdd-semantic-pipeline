# Wiki Index

_Last updated: 2026-06-12_

| Page | Summary | Last Updated |
|------|---------|--------------|
| [pipeline-101](pipeline-101.md) | Step-by-step operator runbook: onboard a doc to chunks, update without full re-index, vocabulary/taxonomy (single + connected docs), evaluate semantic quality, and the troubleshooting loop | 2026-06-14 |
| [confluence-conversion-rules](../confluence-conversion-rules.md) | Definitive Confluence Server/DC 8.0–10.x → GitLab-Markdown conversion rules for the embedding pipeline (storage-format + rendered-HTML input; supersedes the storage-format wiki page) | 2026-06-12 |
| [confluence-storage-format-gitlab-markdown](confluence-storage-format-gitlab-markdown.md) | **Superseded** by confluence-conversion-rules — kept for history | 2026-06-12 |
| [convert-html-gitlab-markdown-linux](convert-html-gitlab-markdown-linux.md) | Linux instructions for running the HTML to GitLab Markdown converter | 2026-06-06 |
| [convert-html-gitlab-markdown-windows](convert-html-gitlab-markdown-windows.md) | Windows instructions for running the HTML to GitLab Markdown converter | 2026-06-06 |

## Learning KB (docs/learn/)

Self-study curriculum for the codebase (C#-developer-oriented). Pages live outside `docs/guides/` and do not follow the guide page template.

| Page | Summary | Last Updated |
|------|---------|--------------|
| [learn-index](../learn/README.md) | Curriculum index, 5-day intensive study plan, and the freshness table mapping pages to source files | 2026-06-10 |
| [project-anatomy-and-tooling](../learn/bridge/01-project-anatomy-and-tooling.md) | C#→Python bridge: pyproject.toml vs csproj, venv, pip editable installs, pytest/ruff/mypy | 2026-06-10 |
| [dataclasses-vs-csharp-records](../learn/bridge/02-dataclasses-vs-csharp-records.md) | C#→Python bridge: @dataclass vs record, default_factory trap, StrEnum, frozen + __post_init__ | 2026-06-10 |
| [protocols-typing-and-unions](../learn/bridge/03-protocols-typing-and-unions.md) | C#→Python bridge: Protocol vs interface (structural typing), str-or-None vs string?, TYPE_CHECKING, constructor injection | 2026-06-10 |
| [iteration-comprehensions-generators](../learn/bridge/04-iteration-comprehensions-generators.md) | C#→Python bridge: comprehensions vs LINQ, yield/yield from, sorted(key=), defaultdict, slicing | 2026-06-10 |
| [modules-imports-and-lazy-patterns](../learn/bridge/05-modules-imports-and-lazy-patterns.md) | C#→Python bridge: modules vs namespaces, @property as Lazy<T>, lazy imports, logging, pathlib, escape-sequence gotcha | 2026-06-10 |
| [pydantic-settings-and-typer](../learn/bridge/06-pydantic-settings-and-typer.md) | C#→Python bridge: BaseSettings vs IOptions, the dual-branch config trap, typer vs System.CommandLine | 2026-06-10 |
| [pytest-for-xunit-developers](../learn/bridge/07-pytest-for-xunit-developers.md) | C#→Python bridge: fixtures vs constructor injection, parametrize vs Theory, markers vs Trait, monkeypatch/mocker vs Moq | 2026-06-10 |
| [tour-models-and-config](../learn/tours/01-models-and-config.md) | Reading guide for models.py (contract layer, content vs embed_text) and config.py | 2026-06-10 |
| [tour-ast-parser-and-structural](../learn/tours/02-ast-parser-and-structural.md) | Reading guide for ast_parser.py (pandoc AST) and structural.py (heading stack → section tree) | 2026-06-10 |
| [tour-enrichment](../learn/tours/03-enrichment.md) | Reading guide for enrichment.py: section rules, first-match-wins, precision vs recall entity patterns | 2026-06-10 |
| [tour-vocabulary-and-two-pass-scan](../learn/tours/04-vocabulary-and-two-pass-scan.md) | Reading guide for the cross-corpus vocabulary: scan_corpus, scan_and_persist, two-pass index flow | 2026-06-10 |
| [tour-taxonomy-modules](../learn/tours/05-taxonomy-modules.md) | Reading guide for header_norm, template_taxonomy, corpus_taxonomy, doc_router | 2026-06-10 |
| [tour-inventory-extraction](../learn/tours/06-inventory-extraction-modules.md) | Reading guide for extract_structural/prose, direction, reconcile, and _build_inventory routing | 2026-06-10 |
| [tour-chunking](../learn/tours/07-chunking.md) | Reading guide for chunking.py: split cascade, merge strategies, embed budget, entity_fn injection | 2026-06-10 |
| [tour-embeddings-and-vector-store](../learn/tours/08-embeddings-and-vector-store.md) | Reading guide for embeddings.py and vector_store.py: the two Protocol seams, factories, provenance | 2026-06-10 |
| [tour-retrieval-and-hybrid-search](../learn/tours/09-retrieval-and-hybrid-search.md) | Reading guide for retrieval.py (BM25, RRF) and pipeline._hybrid_search | 2026-06-10 |
| [tour-pipeline-and-cli](../learn/tours/10-pipeline-orchestrator-and-cli.md) | Reading guide for pipeline.py (composition root) and cli.py (the eight typer commands) | 2026-06-11 |
| [tour-quality-linter](../learn/tours/11-quality-linter.md) | Reading guide for quality.py and the lint command: raw-.md quality lint, fence-aware checks, report-only diagnostics | 2026-06-11 |
| [life-of-a-document](../learn/walkthroughs/01-life-of-a-document.md) | Flagship walkthrough: one real SAD traced through every stage with actual dump.py JSON and live search results | 2026-06-10 |
| [architecture-map](../learn/walkthroughs/02-architecture-map.md) | The whole system on one page: dependency graph, layering rules, data-model diagram, reading order | 2026-06-10 |
| [test-suite-tour](../learn/walkthroughs/03-test-suite-tour.md) | The test suite as documentation: conftest fixtures, marker tiers, e2e tests, eval harness | 2026-06-10 |
| [exercise-trace-a-document](../learn/exercises/01-trace-a-document.md) | Kata: trace two corpus docs with dump.py and answer five questions (with answer key) | 2026-06-10 |
| [exercise-add-a-section-keyword](../learn/exercises/02-add-a-section-keyword.md) | Kata: add a keyword to _SECTION_RULES plus a test | 2026-06-10 |
| [exercise-parametrize-header-norm](../learn/exercises/03-parametrize-header-norm.md) | Kata: parametrized tests for normalise_header, predict-from-spec-first | 2026-06-10 |
| [exercise-add-a-config-field](../learn/exercises/04-add-a-config-field.md) | Kata: add a PipelineConfig field to BOTH pydantic branches plus an env-override test | 2026-06-10 |
| [exercise-extend-an-entity-pattern](../learn/exercises/05-extend-an-entity-pattern.md) | Kata: extend _SERVICE_PATTERN suffixes plus a test and blast-radius check | 2026-06-10 |
| [exercise-add-a-cli-flag](../learn/exercises/06-add-a-cli-flag.md) | Kata: add --json output to the search command plus a CliRunner test | 2026-06-10 |
| [exercise-tune-hybrid-search](../learn/exercises/07-tune-hybrid-search-and-measure.md) | Kata: measure hybrid on/off and rrf_k sweep with the eval harness (recall@5, MRR) | 2026-06-10 |
| [exercise-use-the-library](../learn/exercises/08-use-the-library-from-scratch.md) | Kata: write a standalone script consuming SemanticPipeline as a library | 2026-06-10 |
