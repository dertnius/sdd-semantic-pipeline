# learn/ — understanding this codebase for real

A self-study curriculum for a **senior C# developer who is new to Python** and wants to genuinely own this codebase (it was originally AI-generated). The goal is not to read *about* the code — it's to read *the* code, with these pages as your guide rails.

**How to use it:** always have the cited source file open beside the page. Every page routes you into the code with questions; if you only read the pages, you've missed the point. Do the exercises — they are the spine of each day, not optional extras.

## The four kinds of material

| Folder | What it is | When to use |
|---|---|---|
| [bridge/](bridge/) | C# → Python concept maps, grounded in this repo's code | When a Python idiom looks alien |
| [tours/](tours/) | Per-module reading guides (reading order + why + tests) | Before/while reading a module |
| [walkthroughs/](walkthroughs/) | Data-flow narratives with real intermediate artifacts | To see how the pieces connect |
| [exercises/](exercises/) | Katas with verification commands (work on a `learn-exercises` git branch) | To prove to yourself you got it |

**Canonical references** (linked, never duplicated here): [README.md](../README.md) — CLI flags & setup · [CLAUDE.md](../CLAUDE.md) — architecture & guardrails · [ADR-0001](../docs/adr/adr-0001-modular-semantic-pipeline.md) — why it's modular · [eval/README.md](../eval/README.md) — retrieval evaluation. *Those say what the system does; learn/ teaches how the code works.*

## The 5-day intensive plan

Hours are estimates — the reading **order** is the contract, not the clock. Compressing to 3 days: merge Days 1+2 and 4+5, defer exercises 02/03/05 to evenings.

### Day 1 — Foundations: tooling, idioms, the map (~7h)
1. [bridge/01 project anatomy & tooling](bridge/01-project-anatomy-and-tooling.md) — and actually DO the setup ritual (venv, `pip install -e ".[dev]"`, `sdd-pipeline check`, `pytest -m "not slow"`)
2. [walkthroughs/02 architecture map](walkthroughs/02-architecture-map.md) — the whole system on one page
3. [bridge/02 dataclasses vs records](bridge/02-dataclasses-vs-csharp-records.md) with [models.py](../src/sdd_pipeline/models.py) open
4. [bridge/03 protocols, typing, unions](bridge/03-protocols-typing-and-unions.md) with [embeddings.py](../src/sdd_pipeline/embeddings.py)
5. [tours/01 models & config](tours/01-models-and-config.md) + [bridge/06 pydantic & typer](bridge/06-pydantic-settings-and-typer.md) (pydantic half)

### Day 2 — Parse & structure (~8h)
1. [bridge/04 iteration & generators](bridge/04-iteration-comprehensions-generators.md), [bridge/05 modules & lazy patterns](bridge/05-modules-imports-and-lazy-patterns.md)
2. [tours/02 ast_parser & structural](tours/02-ast-parser-and-structural.md)
3. **[exercise 01 — trace a document](exercises/01-trace-a-document.md)** (dump.py is your microscope from here on)
4. [tours/03 enrichment](tours/03-enrichment.md)
5. [bridge/07 pytest for xUnit devs](bridge/07-pytest-for-xunit-developers.md) (fixtures/parametrize half) → **[exercise 02 — add a section keyword](exercises/02-add-a-section-keyword.md)**

### Day 3 — Vocabulary, taxonomy, inventory, chunking (~8h)
1. [tours/04 vocabulary & two-pass scan](tours/04-vocabulary-and-two-pass-scan.md)
2. [tours/05 taxonomy modules](tours/05-taxonomy-modules.md)
3. [tours/06 inventory extraction](tours/06-inventory-extraction-modules.md)
4. **[exercise 03 — parametrize header_norm](exercises/03-parametrize-header-norm.md)** + **[exercise 05 — extend an entity pattern](exercises/05-extend-an-entity-pattern.md)**
5. [tours/07 chunking](tours/07-chunking.md) + first half of [walkthroughs/01 life of a document](walkthroughs/01-life-of-a-document.md) (through stage 6)

### Day 4 — Embed, store, search (~8h)
1. [tours/08 embeddings & vector store](tours/08-embeddings-and-vector-store.md)
2. [tours/09 retrieval & hybrid search](tours/09-retrieval-and-hybrid-search.md)
3. Second half of [walkthroughs/01](walkthroughs/01-life-of-a-document.md) — run the real index + searches
4. **[exercise 04 — add a config field](exercises/04-add-a-config-field.md)** + **[exercise 07 — tune hybrid search & measure](exercises/07-tune-hybrid-search-and-measure.md)**

### Day 5 — Orchestration, CLI, tests (~6h)
1. [tours/10 pipeline & CLI](tours/10-pipeline-orchestrator-and-cli.md) — re-read [pipeline.py](../src/sdd_pipeline/pipeline.py) top to bottom; it all clicks now, then [tours/11 quality linter](tours/11-quality-linter.md) (the read-only `lint` command — a Roslyn-analyzer analogy)
2. [walkthroughs/03 test-suite tour](walkthroughs/03-test-suite-tour.md) + rest of bridge/07 (monkeypatch/mocker)
3. **[exercise 06 — add a CLI flag](exercises/06-add-a-cli-flag.md)** + **[exercise 08 — use the library from scratch](exercises/08-use-the-library-from-scratch.md)**
4. Wrap-up: skim the freshness table below; write down your Phase-2 questions

## Phase 2 (deferred)

The `sdd_pipeline/convert/` subpackage (the Confluence-HTML→Markdown converter — `base` shared layer + `html_to_gitlab_md` HTML path + `confluence_pf_filter` Stage-C filter) is deliberately **out of scope** here. It is standalone — zero imports from the pipeline — and the hardest read in the repo (BeautifulSoup walking + heavy regex). Tackle it only after you're fluent in flow A; the converter wiki pages (`wiki/convert-html-gitlab-markdown-*.md`) cover *using* it.

## Freshness — keeping learn/ honest as the code evolves

Pages cite code as `module.py::symbol` (greppable). After changing a module, check this table, grep `learn/` for that module's symbols, fix stale claims, and log the update in `wiki/log.md`.

| Page(s) | Source files cited |
|---|---|
| bridge/01 | pyproject.toml |
| bridge/02 | models.py, dump.py |
| bridge/03 | embeddings.py, vector_store.py, pipeline.py, models.py |
| bridge/04 | retrieval.py, enrichment.py, template_taxonomy.py, corpus_taxonomy.py, pipeline.py |
| bridge/05 | pipeline.py, embeddings.py, config.py, vector_store.py, dump.py, `__init__.py` |
| bridge/06 | config.py, cli.py |
| bridge/07 | tests/conftest.py, tests/test_pipeline.py, tests/test_config.py, pyproject.toml |
| tours/01 | models.py, config.py |
| tours/02 | ast_parser.py, structural.py, pipeline.py |
| tours/03 | enrichment.py |
| tours/04 | vocabulary.py, enrichment.py, pipeline.py, cli.py |
| tours/05 | header_norm.py, template_taxonomy.py, corpus_taxonomy.py, doc_router.py |
| tours/06 | extract_structural.py, extract_prose.py, direction.py, reconcile.py, pipeline.py, enrichment.py |
| tours/07 | chunking.py, models.py, config.py |
| tours/08 | embeddings.py, vector_store.py, pipeline.py |
| tours/09 | retrieval.py, pipeline.py, config.py |
| tours/10 | pipeline.py, cli.py |
| tours/11 | quality.py, cli.py |
| walkthroughs/01 | dump.py + **regenerate `out/` excerpts after any stage change** (the command is in the page) |
| walkthroughs/02 | all of src (dependency graph), CLAUDE.md guardrails |
| walkthroughs/03 | tests/, pyproject.toml, scripts/eval_retrieval.py |
| exercises/* | the module each exercise modifies (see each page's Files section) |

Most drift-prone: **walkthroughs/01** (quotes real JSON) and **exercise answer keys** (quote real outputs). Re-run their commands after pipeline changes.
