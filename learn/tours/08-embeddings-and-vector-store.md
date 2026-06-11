# Tour 08 — Embeddings & vector store: the two Protocol seams

**Modules:** [embeddings.py](../../src/sdd_pipeline/embeddings.py),
[vector_store.py](../../src/sdd_pipeline/vector_store.py)

## Role in the pipeline

Stage 7: turn chunks into vectors and persist them. These are the system's two
swappable seams — everything upstream depends only on `EmbedderProtocol` and
`VectorStoreProtocol`, so tests inject mocks and backends switch via config.
A Python `Protocol` is like a C# interface that classes never declare they
implement — conformance is purely structural (duck typing, checked by shape).

## Reading order: embeddings.py

1. `embeddings.py::EmbedderProtocol` — two methods, `embed_chunks` / `embed_query`.
   That's the whole contract the pipeline sees.
2. `embeddings.py::EmbeddingModel` — note `_model: SentenceTransformer | None = None`
   in `__init__` and the `model` property that calls `_load()` on first access
   (≈ `Lazy<T>.Value`). **Nothing downloads until the first embed** — this is why
   [dump.py](../../src/sdd_pipeline/dump.py) and the `export`/`scan` commands are
   fast and model-free. Also: `embed_chunks` embeds `c.to_embed_text()`, never raw
   `content`. *What would silently break if it embedded `content`?*
3. Skim `embeddings.py::AzureOpenAIEmbedder` — same shape, lazy `openai` SDK
   import (optional `[azure]` extra), batched calls, defensive sort by
   `row.index`.
4. `embeddings.py::make_embedder` — the factory switching on
   `config.embedding_provider` (`local` | `azure`), unknown value raises.
5. `embeddings.py::embedder_identity` — returns `(provider, model_or_deployment)`;
   this tuple is what provenance (below) records and verifies.

## Reading order: vector_store.py

1. `vector_store.py::SearchResult` — read the `score` property:

   ```python
   if self.fused_score is not None:
       return self.fused_score
   return 1.0 - self.distance
   ```

   Cosine similarity by default; the hybrid path ([tour 09](09-retrieval-and-hybrid-search.md))
   overwrites it with an RRF score.
2. `vector_store.py::VectorStoreProtocol` — `add_chunks`, `search`, `get_corpus`,
   `delete_document`, `reset`, provenance get/set, `count`.
3. `vector_store.py::MemoryVectorStore` (the default backend) — langchain-core's
   `InMemoryVectorStore` persisted as `<persist_dir>/<collection>.json` plus a
   `<collection>.provenance.json` sidecar. Two details worth pausing on:
   - `MemoryVectorStore.add_chunks` writes `self._store.store[chunk.chunk_id] = {...}`
     **directly** instead of calling `add_documents` — the pipeline supplies
     precomputed vectors, and `add_documents` would re-embed via the store's
     Embeddings object.
   - `vector_store.py::_precomputed_embeddings` returns a stub `Embeddings` whose
     methods `raise NotImplementedError` — any accidental embedding path fails
     loudly instead of silently re-embedding raw text. *Why is a loud failure
     better than a working fallback here?*
   - `_dump` persists atomically (write `.json.tmp`, then `replace`).
4. Skim `vector_store.py::ChromaVectorStore` — same protocol against ChromaDB
   (`hnsw:space=cosine`); provenance lives in collection metadata via
   `collection.modify`, excluding reserved `hnsw:*` keys.
5. `vector_store.py::make_vector_store` — factory on `config.vector_store_backend`
   (`memory` | `chroma`).

## Provenance: refusing to search a foreign index

`set_provenance`/`get_provenance` record `(provider, model, dimension)` at index
time (called from `pipeline.py::SemanticPipeline.index_doc`). Before any search,
`pipeline.py::SemanticPipeline._verify_provenance` compares the stored identity
with `embedder_identity(self.config)` and raises `ValueError` on mismatch.
Why: different models (or providers) produce **incompatible vector spaces** —
a query embedded with model B against an index built with model A returns
confidently wrong nearest neighbours, with no error. Empty provenance (legacy
index, mocks) passes through.

## get_corpus

Both backends expose `get_corpus(...)`: every stored chunk, filters applied,
`distance=0.0`. It exists purely so hybrid search can build a BM25 index over
the same filtered corpus — see [tour 09](09-retrieval-and-hybrid-search.md).

## Executable documentation

- `tests/test_embeddings.py::TestAzureOpenAIEmbedder::test_preserves_input_order_despite_shuffled_response`
  and `TestMakeEmbedder::test_unknown_provider_raises`.
- `tests/test_memory_vector_store.py::TestRoundtrip` — uses the **real**
  langchain store (pure Python, fast): `test_nearest_result_first`,
  `test_upsert_replaces_same_chunk_id`. Doubles as a tripwire for layout changes
  in the library.
- `tests/test_vector_store.py` — Chroma fully mocked. Worth reading the
  `patched_store` fixture: `ChromaVectorStore.__new__(ChromaVectorStore)`
  allocates the instance **without running `__init__`**, so the
  `import chromadb` guard is never reached (≈ C#'s
  `RuntimeHelpers.GetUninitializedObject` — construct without the ctor), then
  wires `_client`/`_collection` to MagicMocks.

## Self-check

1. You run `sdd-pipeline search` with `--model all-MiniLM-L6-v2` against an index
   built with `BAAI/bge-large-en-v1.5`. What happens, and where?
   <details><summary>Answer</summary><code>_verify_provenance</code> in
   pipeline.py raises <code>ValueError: Embedding provenance mismatch…</code>
   before any embedding happens — the stored
   <code>embedding_model</code> doesn't equal the configured one. Fix: re-index
   or align <code>--provider</code>/<code>--model</code>.</details>

2. Why does `MemoryVectorStore.__init__` deliberately let a corrupt index file
   raise instead of starting empty?
   <details><summary>Answer</summary>The comment in the code: a broken index must
   never be <em>silently replaced by an empty one</em> — the next
   <code>add_chunks</code> would persist the empty store and destroy the data.
   Loud failure preserves the evidence.</details>

3. `SemanticPipeline.__init__` accepts `embedding_model` and `vector_store`
   arguments typed as the two protocols. What C# pattern is this, and what do
   the lazy `embedder`/`store` properties add?
   <details><summary>Answer</summary>Constructor injection against interfaces.
   The lazy properties (≈ <code>Lazy&lt;T&gt;</code> resolved by the factories
   <code>make_embedder</code>/<code>make_vector_store</code>) mean tests inject
   mocks with zero side effects, while production builds the real backends only
   on first use — so model-free commands never download anything.</details>
