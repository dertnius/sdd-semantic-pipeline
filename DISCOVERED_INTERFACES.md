# Discovered interfaces — enrichment overhaul

Real attribute/function names read from the code (not assumed). All later tasks
reference these. Verified at the file:line refs below.

## Data model ([src/sdd_pipeline/models.py](src/sdd_pipeline/models.py))

| Concept | Real name / type | Ref |
|---|---|---|
| Section identifier | `Section.section_id: str` | models.py:118 |
| Section text | **No single field.** Text lives in `Section.blocks: list[ContentBlock]`; each `ContentBlock.text: str` | models.py:120, 107 |
| Section hierarchy | `Section.breadcrumb: list[str]`, `Section.subsections: list[Section]`, `Section.level: int` | models.py:116-121 |
| Dependency fields | `Section.depends_on: list[str]`, `Section.exposes: list[str]` (mutable lists, default empty) | models.py:125-126 |
| Other enrichment | `Section.entities: list[str]`, `Section.tags: list[str]`, `Section.section_type: SectionType` | models.py:122-124 |
| Block | `ContentBlock(block_id, content_type: ContentType, text: str, language, raw: dict\|None)` | models.py:101-109 |
| **Tables** | A table is a `ContentBlock` with `content_type == ContentType.TABLE` and `text` = a **GFM pipe-table string**. `raw` is **None** (never populated). No structured cell/column access survives. | structural.py:261-269 |
| Document | `DocumentModel.root_sections: list[Section]` (sections are NOT nested under a single field) | models.py:142 |
| Chunk | `SemanticChunk` (mutable `@dataclass`): `chunk_id, doc_id, breadcrumb, content, content_type, language, section_type, entities, tags, depends_on, exposes, space, labels, title, source_url` | models.py:162-187 |
| Chunk metadata | `SemanticChunk.to_metadata()` → scalar dict; `breadcrumb` joined with `" > "`; lists JSON-encoded; **no `metadata` dict field** (it's a method) | models.py:245 |
| Embed text | `SemanticChunk.to_embed_text()` — includes section_type, breadcrumb, entities (as `keywords:`), tags. **Does NOT include `depends_on`/`exposes`** (the T8 gap) | models.py:189 |
| Section→chunk copy | `chunk_document` already copies `depends_on`/`exposes` from Section to each chunk | chunking.py:155-156 |

All dataclasses are **mutable** (`@dataclass`, not frozen).

## enrichment.py — real functions (there is NO `enrich()`)

| Function | Signature | Behaviour | Ref |
|---|---|---|---|
| `enrich_section` | `(section: Section, entity_terms: Iterable[str] \| None = None) -> None` | **Mutates in place**, returns None; recurses into subsections | enrichment.py:354 |
| `enrich_document` | `(doc: DocumentModel, entity_terms=None) -> DocumentModel` | Mutates each root section in place, returns the **same** object | enrichment.py:366 |
| `extract_entities` | `(text, extra_terms=None) -> list[str]` | regex/term entity extraction | enrichment.py:309 |
| `extract_tags`, `classify_section_type`, `scan_corpus` | — | helpers / corpus vocab discovery | enrichment.py:335,284,420 |

> Plan implication: T6 adds an `inventory` path to `enrich_section`/`enrich_document`
> and keeps the current body as `_enrich_legacy`. The functions must keep their
> **in-place / return-same** contract — do not switch to frozen/return-new.

## enrich call sites (T0.2 migration scope for T6)

| Caller | Call | Breaks on new `inventory` param? |
|---|---|---|
| [pipeline.py:96](src/sdd_pipeline/pipeline.py#L96) | `enrich_document(doc, entity_terms=...)` in `enrich_and_chunk` | **Yes — primary migration.** Becomes the inventory-driven path. |
| [dump.py:51](src/sdd_pipeline/dump.py#L51) | `enrich_document(doc, entity_terms=terms)` | No-break if `inventory` is keyword/optional on the legacy path; otherwise update. |
| [tests/test_enrichment.py:201-254](tests/test_enrichment.py#L201) | `enrich_section(section)`, `enrich_document(sample_document_model)` direct | Update: new path needs an inventory; pass an empty one to exercise legacy fallback. |
| [tests/test_pipeline.py:113-242](tests/test_pipeline.py#L113) | `patch("sdd_pipeline.pipeline.enrich_document", side_effect=lambda d, **kw: d)` | No-break (mock accepts `**kw`); verify the patched signature still matches. |
| [\_\_init\_\_.py:9](src/sdd_pipeline/__init__.py#L9) | docstring mention only | No-break. |

## T0.3 — retrieval baseline harness

**Already built and committed** this session (branch history: `eval-retrieval-harness`,
now on `template-enrichment`): [scripts/eval_retrieval.py](scripts/eval_retrieval.py),
[eval/queries.yaml](eval/queries.yaml), [RETRIEVAL_LOG.md](RETRIEVAL_LOG.md).
Section-granularity recall@5/@10 + MRR, model-agnostic embedder. Reuse it; the real
Baseline is pending template-conforming docs + a configured embedder.
