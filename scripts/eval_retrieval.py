#!/usr/bin/env python
"""
Retrieval-evaluation harness (pre-overhaul baseline).

Measures whether a change to the pipeline moves *retrieval quality* on a frozen
golden set, so the enrichment overhaul can be judged on a number instead of a
checkbox. See ``eval/README.md`` and ``RETRIEVAL_LOG.md``.

Design (mirrors plan ``grill-this-plan-fluffy-quilt.md``):

* **Unit = chunk; relevance judged at section granularity.** A query's golden
  answer is a list of *section matchers* — ``(doc, section)`` where ``doc`` is a
  POSIX path relative to the corpus root and ``section`` is a case-insensitive
  substring of the chunk breadcrumb (empty ``section`` ⇒ any chunk in that doc).
  This is robust to chunk-splitting and to the non-portable ``chunk_id``
  (``chunk_id`` embeds ``md5(absolute_path)``).
* **Model-agnostic.** The embedder comes from ``PipelineConfig`` via
  ``make_embedder`` — whatever provider/model you configured (local or Azure).
  No model is named here. ``--mock`` swaps in a deterministic hashing embedder so
  the harness *wiring* can be exercised with no model download (the resulting
  numbers are not a quality baseline — they only prove the plumbing).
* **Fresh index every run.** Enrichment changes embeddings, so the index is
  rebuilt into a throwaway temp dir each run; comparing against a stale index
  would be apples-to-oranges.

Usage:
    python scripts/eval_retrieval.py --corpus eval/corpus --queries eval/queries.yaml
    python scripts/eval_retrieval.py --mock        # wiring smoke-test, no model
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ── Pure scoring core (no pipeline/model imports — unit-tested directly) ───────

# A retrieved chunk is reduced to the (doc, breadcrumb) of the section it came
# from. A matcher is the (doc, needle) the golden set asked for.
Retrieved = tuple[str, str]  # (doc_relpath, breadcrumb)
Matcher = tuple[str, str]  # (doc_relpath, section-substring or "")


def matches(result: Retrieved, matcher: Matcher) -> bool:
    """True if a retrieved (doc, breadcrumb) satisfies a golden (doc, needle)."""
    doc, breadcrumb = result
    want_doc, needle = matcher
    if doc != want_doc:
        return False
    return needle.lower() in breadcrumb.lower()  # "" ⇒ any section in the doc


def recall_at_k(retrieved: list[Retrieved], expected: list[Matcher], k: int) -> float:
    """Fraction of expected matchers satisfied by the top-*k* retrieved chunks."""
    if not expected:
        return 0.0
    topk = retrieved[:k]
    satisfied = sum(1 for m in expected if any(matches(r, m) for r in topk))
    return satisfied / len(expected)


def reciprocal_rank(retrieved: list[Retrieved], expected: list[Matcher]) -> float:
    """1/rank of the first retrieved chunk that satisfies *any* expected matcher."""
    for rank, r in enumerate(retrieved, start=1):
        if any(matches(r, m) for m in expected):
            return 1.0 / rank
    return 0.0


def score_query(
    retrieved: list[Retrieved], expected: list[Matcher], ks: tuple[int, ...] = (5, 10)
) -> dict[str, float]:
    """recall@k for each k plus reciprocal rank, for one query."""
    out: dict[str, float] = {f"recall@{k}": recall_at_k(retrieved, expected, k) for k in ks}
    out["rr"] = reciprocal_rank(retrieved, expected)
    return out


def aggregate(per_query: list[dict[str, float]]) -> dict[str, float]:
    """Macro-average each metric across queries (rr → MRR)."""
    if not per_query:
        return {}
    keys = per_query[0].keys()
    agg = {k: sum(q[k] for q in per_query) / len(per_query) for k in keys}
    if "rr" in agg:  # report the macro-mean of reciprocal rank as MRR
        agg["MRR"] = agg.pop("rr")
    return agg


# ── Golden-set model ───────────────────────────────────────────────────────────


@dataclass
class Query:
    id: str
    text: str
    category: str  # cross-reference | paraphrase | lexical-control | ...
    expected: list[Matcher] = field(default_factory=list)


def load_queries(path: Path) -> list[Query]:
    """Load the frozen golden set. YAML if available, else JSON (same shape)."""
    raw = path.read_text(encoding="utf-8")
    data: object
    if path.suffix in (".yaml", ".yml"):
        import yaml  # pyyaml; ships transitively with the pipeline deps

        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)
    assert isinstance(data, dict), "queries file must map 'queries:' to a list"
    queries: list[Query] = []
    for item in data["queries"]:
        expected = [(e["doc"], e.get("section", "")) for e in item["expected"]]
        queries.append(
            Query(
                id=str(item["id"]),
                text=item["text"],
                category=item.get("category", "uncategorized"),
                expected=expected,
            )
        )
    return queries


# ── Deterministic mock embedder (wiring smoke-test only; no model download) ────


class HashingEmbedder:
    """Hashing bag-of-words embedder. Lexically-overlapping texts get higher
    cosine similarity, so the harness wiring (index → search → score) can be
    exercised end-to-end with no model. NOT a quality baseline."""

    DIM = 512

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.DIM
        for tok in text.lower().split():
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_chunks(self, chunks: list) -> list[list[float]]:  # type: ignore[type-arg]
        return [self._vec(c.to_embed_text()) for c in chunks]

    def embed_query(self, query: str) -> list[float]:
        return self._vec(query)


# ── Harness orchestration (needs pandoc + an embedder) ─────────────────────────


def build_index(pipeline, corpus_dir: Path) -> dict[str, str]:
    """Index every ``*.md`` under *corpus_dir* in sorted order into the pipeline's
    (throwaway) store. Returns the ``doc_id → relative-POSIX-path`` manifest the
    scorer needs because chunk metadata stores only the irreversible ``doc_id``."""
    from sdd_pipeline.pipeline import _stable_doc_id

    manifest: dict[str, str] = {}
    md_files = sorted(corpus_dir.rglob("*.md"), key=lambda p: p.as_posix())
    if not md_files:
        raise SystemExit(f"No markdown files found under {corpus_dir}")
    for path in md_files:
        n = pipeline.index_file(path)
        manifest[_stable_doc_id(path)] = path.relative_to(corpus_dir).as_posix()
        print(f"  indexed {path.relative_to(corpus_dir).as_posix()} ({n} chunks)")
    return manifest


def run_eval(
    corpus_dir: Path,
    queries: list[Query],
    *,
    use_mock: bool,
    top_k: int,
    hybrid: bool,
    ks: tuple[int, ...],
) -> dict:
    """Build a fresh index, run every query, return a results dict."""
    from sdd_pipeline.config import PipelineConfig
    from sdd_pipeline.embeddings import embedder_identity
    from sdd_pipeline.pipeline import SemanticPipeline

    tmp = Path(tempfile.mkdtemp(prefix="eval_chroma_"))
    try:
        config = PipelineConfig()
        config.chroma_persist_dir = str(tmp)
        config.collection_name = "eval"
        provider, model = ("mock", "hashing-md5") if use_mock else embedder_identity(config)
        pipeline = SemanticPipeline(
            config=config,
            embedding_model=HashingEmbedder() if use_mock else None,
        )

        print(f"Embedder: provider={provider} model={model}")
        print(f"Indexing corpus: {corpus_dir}")
        manifest = build_index(pipeline, corpus_dir)

        max_k = max(ks)
        per_query: list[dict[str, float]] = []
        rows: list[dict] = []
        for q in queries:
            results = pipeline.search(q.text, n_results=max(max_k, top_k), hybrid=hybrid)
            retrieved: list[Retrieved] = [
                (manifest.get(r.metadata.get("doc_id", ""), "?"), r.metadata.get("breadcrumb", ""))
                for r in results
            ]
            metrics = score_query(retrieved, q.expected, ks)
            per_query.append(metrics)
            rows.append(
                {
                    "id": q.id,
                    "category": q.category,
                    **metrics,
                    "top_hit": retrieved[0] if retrieved else None,
                }
            )

        by_cat: dict[str, list[dict[str, float]]] = {}
        for q, m in zip(queries, per_query, strict=True):
            by_cat.setdefault(q.category, []).append(m)

        return {
            "embedder": {"provider": provider, "model": model},
            "manifest": manifest,
            "corpus": {
                "dir": corpus_dir.as_posix(),
                "docs": len(manifest),
            },
            "query_count": len(queries),
            "hybrid": hybrid,
            "aggregate": aggregate(per_query),
            "by_category": {c: aggregate(ms) for c, ms in sorted(by_cat.items())},
            "per_query": rows,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Reporting ──────────────────────────────────────────────────────────────────


def _fmt(metrics: dict[str, float]) -> str:
    order = [k for k in metrics if k.startswith("recall@")] + ["MRR"]
    return "  ".join(f"{k}={metrics[k]:.3f}" for k in order if k in metrics)


def print_report(results: dict) -> None:
    print("\n=== Retrieval evaluation ===")
    emb = results["embedder"]
    print(f"embedder: {emb['provider']}/{emb['model']}")
    print(f"corpus:   {results['corpus']['docs']} docs   queries: {results['query_count']}")
    print(f"hybrid:   {results['hybrid']}")
    print(f"\nAGGREGATE  {_fmt(results['aggregate'])}")
    print("\nby category:")
    for cat, m in results["by_category"].items():
        print(f"  {cat:18s} {_fmt(m)}")


def append_log(results: dict, log_path: Path, heading: str) -> None:
    emb = results["embedder"]
    agg = results["aggregate"]
    lines = [
        f"\n## {heading}",
        "",
        f"- embedder: `{emb['provider']}/{emb['model']}`"
        + (
            "  **(mock — wiring only, not a quality baseline)**"
            if emb["provider"] == "mock"
            else ""
        ),
        f"- corpus: {results['corpus']['docs']} docs, {results['query_count']} queries, "
        f"hybrid={results['hybrid']}",
        f"- **aggregate**: {_fmt(agg)}",
        "- by category: "
        + "; ".join(f"{c} ({_fmt(m)})" for c, m in results["by_category"].items()),
        "",
    ]
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nAppended '{heading}' to {log_path}")


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Retrieval evaluation harness")
    ap.add_argument("--corpus", type=Path, default=repo / "eval" / "corpus")
    ap.add_argument("--queries", type=Path, default=repo / "eval" / "queries.yaml")
    ap.add_argument("--manifest", type=Path, default=repo / "eval" / "corpus_manifest.json")
    ap.add_argument("--log", type=Path, default=repo / "RETRIEVAL_LOG.md")
    ap.add_argument("--out", type=Path, default=None, help="Write full JSON results here.")
    ap.add_argument("--heading", default="Baseline (pre-overhaul)", help="RETRIEVAL_LOG heading.")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--hybrid", action="store_true")
    ap.add_argument(
        "--mock",
        action="store_true",
        help="Use the deterministic hashing embedder (no model download; wiring test only).",
    )
    ap.add_argument("--no-log", action="store_true", help="Print only; do not append to the log.")
    args = ap.parse_args(argv)

    # Make 'src' importable without installing (mirrors pyproject pythonpath=["src"]).
    sys.path.insert(0, str(repo / "src"))

    queries = load_queries(args.queries)
    results = run_eval(
        args.corpus,
        queries,
        use_mock=args.mock,
        top_k=args.top_k,
        hybrid=args.hybrid,
        ks=(5, 10),
    )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(results["manifest"], indent=2, sort_keys=True), encoding="utf-8"
    )
    print_report(results)
    if args.out:
        args.out.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    if not args.no_log:
        append_log(results, args.log, args.heading)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
