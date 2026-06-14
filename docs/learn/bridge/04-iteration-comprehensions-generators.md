# 04 — Iteration: comprehensions, generators, and friends

## Comprehensions ≈ LINQ `Select`/`Where` — but eager

A list comprehension builds the whole list immediately (like `.Select(...).ToList()`), it is not
a deferred query. Open [retrieval.py](../../../src/sdd_pipeline/retrieval.py)::`BM25Index.__init__`:

```python
self.ids = [doc_id for doc_id, _ in documents]
self.term_freqs = [Counter(tokenize(text)) for _, text in documents]
self.doc_len = [sum(tf.values()) for tf in self.term_freqs]
```

Read: `documents.Select(d => d.Item1).ToList()` — with tuple deconstruction in the loop variable
(`doc_id, _` ≈ `var (docId, _)`). A dict comprehension is `ToDictionary`: three lines later,

```python
self.idf = {
    term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
}
```

Comprehensions also run at module load to build constants — see
[enrichment.py](../../../src/sdd_pipeline/enrichment.py)::`_SECTION_PATTERNS` (~line 172), which
compiles `_SECTION_RULES` into regex pairs once at import:

```python
_SECTION_PATTERNS: list[tuple[SectionType, re.Pattern[str]]] = [
    (st, re.compile(r"\b(" + "|".join(re.escape(kw) for kw in keywords) + r")", re.IGNORECASE))
    for st, keywords in _SECTION_RULES.items()
]
```

The inner `re.escape(kw) for kw in keywords` (no brackets) is a *generator expression* — lazy,
consumed once by `join`, like passing an un-materialized `IEnumerable<string>` to `string.Join`.

## Generators ≈ `IEnumerable<T>` with `yield return`

[template_taxonomy.py](../../../src/sdd_pipeline/template_taxonomy.py)::`_walk` is the textbook
recursive iterator:

```python
def _walk(sections: list[Section]):
    for s in sections:
        yield s
        yield from _walk(s.subsections)
```

`yield` ≈ `yield return`; `yield from` ≈ `foreach (var x in Walk(...)) yield return x;` — it
flattens a nested generator. Same laziness rules as C# iterators: nothing runs until someone
iterates. Contrast with `models.py::DocumentModel.iter_sections`, which does the same walk
*eagerly* into a list (BFS with an explicit queue) — both styles coexist in this repo. Another
real consumer: `pipeline.py::SemanticPipeline.scan_and_persist` passes the generator expression
`(doc for _, doc in parsed)` into `scan_corpus` — a one-shot lazy sequence.

## `sorted(key=lambda)` ≈ `OrderBy(...)`

The final line of `retrieval.py::reciprocal_rank_fusion`:

```python
return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
```

≈ `fused.OrderByDescending(kv => kv.Value).ToList()`. `sorted` always returns a new list;
`key=` extracts the sort key (there is no `IComparer` overload in common use — you map to a
comparable key instead). Same pattern in `BM25Index.top` one screen up.

## `Counter` / `defaultdict` ≈ `GetValueOrDefault` patterns, packaged

`retrieval.py::BM25Index` uses `collections.Counter` — a `Dictionary<string,int>` where missing
keys read as 0 and `df.update(tf.keys())` increments in bulk (the `TryGetValue`+increment dance
you'd hand-write). [corpus_taxonomy.py](../../../src/sdd_pipeline/corpus_taxonomy.py)::`build_corpus_taxonomy`
shows `defaultdict`, including the nested form:

```python
section_field_docs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
field_docs: dict[str, set[str]] = defaultdict(set)
```

Reading a missing key *creates* it via the factory — `ConcurrentDictionary.GetOrAdd` semantics for
plain dicts, eliminating every `if (!d.ContainsKey(k)) d[k] = new(...)` guard.

## Slicing and `enumerate`

Slicing `seq[a:b]` is a copy of the half-open range — `Take`/`Skip` (or `list[a..b]` ranges)
without allocation ceremony. Two live examples:

- `pipeline.py::SemanticPipeline._hybrid_search` — `for chunk_id, fused_score in fused[:n_results]:`
  (take top-k of the fused ranking; also note the tuple unpacking).
- `embeddings.py::AzureOpenAIEmbedder.embed` — `batch = texts[start : start + self.batch_size]`
  inside `for start in range(0, len(texts), self.batch_size)` — the manual `Chunk(batchSize)`.

`enumerate` ≈ LINQ `Select((x, i) => ...)`, but as unpacked loop variables. From
`retrieval.py::reciprocal_rank_fusion`:

```python
for rank, doc_id in enumerate(ranking):
    fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
```

(`dict.get(key, default)` is literally `GetValueOrDefault(key, default)`.) Also
`BM25Index.scores`: `for i, doc_id in enumerate(self.ids):` to walk parallel lists.

## Self-check

1. In `_SECTION_PATTERNS`, why does `"|".join(re.escape(kw) for kw in keywords)` use a generator
   expression rather than a list comprehension, and would the behavior differ?

<details><summary>Answer</summary>

Behavior is identical — `join` consumes either fully. The generator just skips materializing a
temporary list (`Select` streamed into `string.Join` vs `.ToList()` first). Convention: when a
lazy sequence is consumed exactly once by one call, drop the brackets.
</details>

2. `template_taxonomy.py::_walk` and `models.py::DocumentModel.iter_sections` both flatten a
   section tree. One returns immediately even for a huge tree; for the other, all the work happens
   before the first element is available. Which is which, and what is the C# distinction?

<details><summary>Answer</summary>

`_walk` is a generator (`yield`/`yield from`): calling it does nothing until iteration — like a
C# iterator method returning `IEnumerable<T>` with `yield return` (deferred). `iter_sections`
builds and returns a complete `list` (eager) — like a method returning `List<T>` it filled with a
loop. Also note the order differs: `_walk` is depth-first, `iter_sections` is BFS.
</details>
