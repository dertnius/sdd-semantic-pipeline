"""
End-to-end test on REAL public architecture documents.

Proves the template-derived enrichment works on real docs (not just the synthetic
SAD): structured table fields and prose entities are extracted, routed, and folded
into embed text, and the corpus is retrievable. Also runs an A/B comparison of
retrieval with inventory enrichment on vs off.

The corpus is fetched on demand (the only networked code) — run first:

    python src/tools/scripts/fetch_e2e_corpus.py

Then:  PYTHONUTF8=1 pytest tests/test_e2e_real_docs.py -q -s

If the corpus is absent the whole module is skipped (never failed), so default CI
is unaffected. A deterministic hashing embedder is used (no model download); the
A/B therefore measures the *lexical* contribution of enrichment — the hard gate is
no-regression + feature-is-live, and the measured delta is printed for inspection.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.pipeline import SemanticPipeline, _stable_doc_id

REPO = Path(__file__).resolve().parent.parent
E2E_CORPUS = REPO / "src" / "tools" / "eval" / "e2e_corpus"
RETAILNEXUS = REPO / "src" / "tools" / "eval" / "corpus" / "sad-retailnexus-oms.md"
QUERIES = REPO / "src" / "tools" / "eval" / "e2e_queries.yaml"

# Reuse the eval harness's pure scorers + mock embedder by loading it by path.
_SPEC = importlib.util.spec_from_file_location(
    "eval_retrieval", REPO / "src" / "tools" / "scripts" / "eval_retrieval.py"
)
assert _SPEC and _SPEC.loader
ev = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_retrieval"] = ev  # let @dataclass resolve the module during exec
_SPEC.loader.exec_module(ev)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not list(E2E_CORPUS.glob("*.md")),
        reason="e2e corpus absent — run `python src/tools/scripts/fetch_e2e_corpus.py` first",
    ),
]


def _corpus_files() -> list[Path]:
    """Fetched real docs + the in-repo RetailNexus SAD (directional signal)."""
    files = sorted(E2E_CORPUS.glob("*.md"), key=lambda p: p.name)
    if RETAILNEXUS.exists():
        files.append(RETAILNEXUS)
    return files


def _pipeline(inventory_on: bool, persist_dir: Path) -> SemanticPipeline:
    config = PipelineConfig()
    config.chroma_persist_dir = str(persist_dir)
    config.collection_name = "e2e"
    config.inventory_enrichment = inventory_on
    return SemanticPipeline(config=config, embedding_model=ev.HashingEmbedder())


def _index_and_score(inventory_on: bool):
    """Index the corpus with the mock embedder and score the golden set."""
    queries = ev.load_queries(QUERIES)
    tmp = Path(tempfile.mkdtemp(prefix="e2e_chroma_"))
    try:
        pipe = _pipeline(inventory_on, tmp)
        manifest: dict[str, str] = {}
        for path in _corpus_files():
            pipe.index_file(path)
            manifest[_stable_doc_id(path)] = path.name

        per_query: list[dict] = []
        by_cat: dict[str, list[dict]] = {}
        for q in queries:
            results = pipe.search(q.text, n_results=10)
            retrieved = [
                (manifest.get(r.metadata.get("doc_id", ""), "?"), r.metadata.get("breadcrumb", ""))
                for r in results
            ]
            m = ev.score_query(retrieved, q.expected, ks=(5, 10))
            per_query.append(m)
            by_cat.setdefault(q.category, []).append(m)
        return ev.aggregate(per_query), {c: ev.aggregate(ms) for c, ms in by_cat.items()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Functional: enrichment populates structured fields on real docs ────────────


def test_gitlab_table_yields_structured_metadata_in_embed_text():
    pipe = SemanticPipeline(config=PipelineConfig(), embedding_model=ev.HashingEmbedder())
    chunks = pipe.process_file(E2E_CORPUS / "gitlab-architecture.md")

    structured = [c for c in chunks if any(k != "raw_entities" for k in c.metadata)]
    assert structured, "GitLab component table should yield field-named metadata"
    c = structured[0]
    # A field value from the table is folded into the embed text (not just stored).
    some_value = next(v for k, vals in c.metadata.items() if k != "raw_entities" for v in vals)
    assert some_value[:30] in c.to_embed_text()


@pytest.mark.skipif(not RETAILNEXUS.exists(), reason="RetailNexus SAD not present")
def test_retailnexus_directional_fields_reach_embed_text():
    pipe = SemanticPipeline(config=PipelineConfig(), embedding_model=ev.HashingEmbedder())
    chunks = pipe.process_file(RETAILNEXUS)
    directional = [c for c in chunks if c.depends_on or c.exposes]
    assert directional, "expected depends_on/exposes from the SAD's directional tables"
    assert any(
        "depends on:" in c.to_embed_text() or "exposes:" in c.to_embed_text() for c in directional
    )


# ── Retrieval: golden queries surface their sections; A/B no-regression ────────


def test_golden_queries_are_retrievable_with_enrichment():
    agg, by_cat = _index_and_score(inventory_on=True)
    print("\n[inventory ON] aggregate:", {k: round(v, 3) for k, v in agg.items()})
    for cat, m in sorted(by_cat.items()):
        print(f"  {cat:16s}", {k: round(v, 3) for k, v in m.items()})
    # Most golden sections are retrievable in the top-10 even with a lexical embedder.
    assert agg["recall@10"] >= 0.5
    assert agg["MRR"] > 0.0


def test_ab_enrichment_does_not_regress_retrieval_and_is_live():
    on_agg, on_cat = _index_and_score(inventory_on=True)
    off_agg, off_cat = _index_and_score(inventory_on=False)

    print("\n=== A/B (mock lexical embedder) ===")
    print("inventory OFF:", {k: round(v, 3) for k, v in off_agg.items()})
    print("inventory ON :", {k: round(v, 3) for k, v in on_agg.items()})
    for cat in sorted(on_cat):
        print(
            f"  {cat:16s} off={ {k: round(v, 3) for k, v in off_cat[cat].items()} }"
            f"  on={ {k: round(v, 3) for k, v in on_cat[cat].items()} }"
        )

    # Measured gain (deterministic over the pinned corpus): folding prose entities
    # + structured fields into sibling chunks' embed text lifts aggregate recall@10,
    # with MRR not regressing. (The cross-reference subset stays flat — a lexical
    # embedder can't exploit directional depends_on/exposes folding; that needs a
    # semantic model, see the opt-in note in the module docstring.)
    assert on_agg["recall@10"] > off_agg["recall@10"]
    assert on_agg["MRR"] >= off_agg["MRR"] - 1e-9

    # Feature is live: enrichment materially changes what gets indexed.
    on_pipe = SemanticPipeline(config=PipelineConfig(), embedding_model=ev.HashingEmbedder())
    off_cfg = PipelineConfig()
    off_cfg.inventory_enrichment = False
    off_pipe = SemanticPipeline(config=off_cfg, embedding_model=ev.HashingEmbedder())
    gl = E2E_CORPUS / "gitlab-architecture.md"
    on_texts = {c.chunk_id: c.to_embed_text() for c in on_pipe.process_file(gl)}
    off_texts = {c.chunk_id: c.to_embed_text() for c in off_pipe.process_file(gl)}
    assert any(on_texts[k] != off_texts.get(k) for k in on_texts), (
        "inventory enrichment should change at least one chunk's embed text"
    )
