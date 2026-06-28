"""
Local MCP (Model Context Protocol) server exposing semantic search over the
indexed SDD/Confluence corpus, for GitHub Copilot's ADR-generator agent.

This module imports ``mcp`` at import time, so it is loaded lazily from the
``sdd-pipeline mcp`` CLI command — the core indexing/search/convert flows never
import it. Install with the optional extra::

    pip install ".[mcp]"

It is a CLI-layer presentation wrapper over the public :class:`SemanticPipeline`
API (like ``tui.py``); it touches neither the deterministic core nor the
vector-store/embedding backends directly.

**stdio contract:** the server speaks JSON-RPC on **stdout**, so nothing here may
write to stdout. All diagnostics go to **stderr** (and stay ASCII for the
Windows cp1252-redirect case). Every tool's logic is a plain module-level
function; the ``@server.tool()`` decorator only wraps a thin adapter, so the
behaviour is unit-testable without an MCP runtime.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

from .models import SectionType
from .pipeline import SemanticPipeline

if TYPE_CHECKING:
    from .config import PipelineConfig
    from .vector_store import SearchResult

logger = logging.getLogger("sdd_pipeline.mcp_server")

# The ADR template (Context / Decision / Alternatives / Consequences) maps onto
# these section types. Each is a (bucket name, section-type values) pair; a bucket
# may union more than one section type (``context`` = overview + architecture).
_ADR_BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    ("context", ("overview", "architecture")),
    ("decision", ("decision",)),
    ("alternatives", ("alternative",)),
    ("tradeoffs", ("tradeoff",)),
    ("consequences", ("consequence",)),
    ("done_criteria", ("done_criteria",)),
]

# Map a decision's topical keywords to the SAD section(s) that should record it, so
# find_sad_coverage checks the *expected* section rather than the whole document. The
# first keyword group found in the decision text wins; no match → search any SAD section.
_SAD_SECTION_HINTS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("database", "datastore", "persistence", "schema", "sql", "table"), ("data_model",)),
    (("integration", "kafka", "topic", "queue", "event", "message", "broker"), ("architecture",)),
    (
        ("service", "microservice", "component", "module", "api", "endpoint"),
        ("architecture", "api"),
    ),
    (("security", "auth", "encryption", "tls", "secret", "credential"), ("security",)),
    (("deploy", "infrastructure", "kubernetes", "container", "runtime"), ("deployment",)),
]


def _expected_sad_sections(decision: str) -> tuple[str, ...]:
    """Section-type values where a SAD should record *decision* (``()`` = any).

    Matches on whole word tokens (not substrings) so a hint like ``topic`` does not
    fire on ``topical`` — the substring-collision class this repo guards against.
    """
    tokens = set(re.findall(r"[a-z]+", decision.lower()))
    for keywords, sections in _SAD_SECTION_HINTS:
        if tokens & set(keywords):
            return sections
    return ()


# ── Pure helpers (unit-tested directly, no MCP runtime) ────────────────────────


def resolve_section_type(value: str | None) -> SectionType | None:
    """Coerce a string into a :class:`SectionType`; raise on an unknown value.

    Blank/None → no filter. An invalid value raises ``ValueError`` listing the
    valid options, so the tool returns a clean MCP error instead of silently
    dropping the filter.
    """
    if value is None or not value.strip():
        return None
    try:
        return SectionType(value.strip())
    except ValueError:
        valid = ", ".join(st.value for st in SectionType)
        raise ValueError(f"Unknown section_type {value!r}; valid values: {valid}") from None


def _loads_list(raw: Any) -> list:
    """Decode a metadata list field (JSON-encoded string in the vector store).

    Vector-store metadata is scalar, so list facets (``entities``/``tags``) are
    stored as JSON strings. Accept an already-decoded list too; return ``[]`` on
    anything missing or malformed.
    """
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return decoded if isinstance(decoded, list) else []


def result_to_dict(r: SearchResult, *, truncate: int | None = None) -> dict:
    """Map a :class:`SearchResult` to a JSON-serialisable record for MCP.

    ``chunk_id`` is included so the agent can reference/dedup a passage;
    ``content`` is truncated to *truncate* chars when set (snippet view).
    """
    content = r.content
    if truncate is not None and len(content) > truncate:
        content = content[:truncate].rstrip() + "..."
    md = r.metadata
    return {
        "chunk_id": r.chunk_id,
        "score": round(r.score, 4),
        "title": md.get("title", ""),
        "source_url": md.get("source_url", ""),
        "breadcrumb": md.get("breadcrumb", ""),
        "section_type": md.get("section_type", ""),
        "doc_type": md.get("doc_type", ""),
        "space": md.get("space", ""),
        "entities": _loads_list(md.get("entities")),
        "tags": _loads_list(md.get("tags")),
        "content": content,
    }


def _require_nonempty_index(pipeline: SemanticPipeline) -> None:
    """Raise a clean, actionable error when the index has no chunks.

    An unbuilt/misconfigured index must be loud, not silently return ``[]`` — the
    agent would otherwise draft an ungrounded ADR with no signal that retrieval
    failed.
    """
    if pipeline.store.count == 0:
        persist = pipeline.config.chroma_persist_dir
        backend = pipeline.config.vector_store_backend
        raise ValueError(
            f"Index is empty at {persist!r} (backend {backend!r}). Run 'sdd-pipeline index' "
            "first, or check the backend / persist-dir in .vscode/mcp.json."
        )


def run_search(
    pipeline: SemanticPipeline,
    query: str,
    top_k: int,
    section_type: str | None,
    space: str | None,
    hybrid: bool | None = None,
    *,
    truncate: int | None = None,
) -> list[dict]:
    """Embed *query* and return the top matches as serialisable dicts.

    ``hybrid=None`` defers to the server's configured default (``--hybrid`` /
    ``PIPELINE_HYBRID_SEARCH``) — never force it off here. The provenance
    ``ValueError`` (embedder/model mismatch) propagates unchanged so the MCP
    layer surfaces it as a clean tool error.
    """
    _require_nonempty_index(pipeline)
    st = resolve_section_type(section_type)
    results = pipeline.search(
        query,
        n_results=top_k,
        section_type=st,
        space=space or None,
        hybrid=hybrid,
    )
    return [result_to_dict(r, truncate=truncate) for r in results]


def find_decision_context_impl(
    pipeline: SemanticPipeline,
    topic: str,
    per_bucket: int = 3,
    snippet_chars: int = 600,
) -> dict[str, list[dict]]:
    """Gather grouped corpus context for drafting an ADR about *topic*.

    Returns snippet-truncated results in ADR-template buckets plus a
    guaranteed-recall ``general`` bucket. Each chunk has a single section type, so
    the precision buckets are mutually exclusive; only ``general`` (unfiltered)
    can overlap them, and it is filtered to chunks no precision bucket claimed —
    so every passage appears exactly once.
    """
    _require_nonempty_index(pipeline)

    def bucket(section_types: tuple[str, ...]) -> list[dict]:
        out: list[dict] = []
        seen_local: set[str] = set()
        for st in section_types:
            for r in run_search(pipeline, topic, per_bucket, st, None, truncate=snippet_chars):
                if r["chunk_id"] not in seen_local:
                    seen_local.add(r["chunk_id"])
                    out.append(r)
        return out[:per_bucket]

    grouped: dict[str, list[dict]] = {name: bucket(types) for name, types in _ADR_BUCKETS}

    seen = {r["chunk_id"] for results in grouped.values() for r in results}
    # Over-fetch so the unfiltered pool still yields per_bucket after removing the
    # chunks already claimed by a precision bucket.
    general_pool = run_search(
        pipeline, topic, per_bucket + len(seen), None, None, truncate=snippet_chars
    )
    grouped["general"] = [r for r in general_pool if r["chunk_id"] not in seen][:per_bucket]
    return grouped


def list_section_type_values() -> list[str]:
    """Return the valid ``section_type`` filter values."""
    return [st.value for st in SectionType]


def list_spaces_impl(pipeline: SemanticPipeline) -> list[str]:
    """Return the sorted Confluence space keys present in the index (``[]`` if empty)."""
    if pipeline.store.count == 0:
        return []
    spaces = {r.metadata.get("space", "") for r in pipeline.store.get_corpus()}
    return sorted(s for s in spaces if s)


def find_sad_coverage_impl(
    pipeline: SemanticPipeline,
    decision: str,
    entities: list[str] | None = None,
    *,
    score_threshold: float = 0.3,
    snippet_chars: int = 400,
) -> dict:
    """Check whether *decision* (and its named *entities*) is reflected in the SAD.

    Two-tier coverage, mirroring the agreed design:
      - **hard** — a named entity appears in a SAD chunk in the decision's *expected*
        section (objective; the caller may auto-accept it).
      - **soft** — no entity match (or none supplied): fall back to a section-scoped
        semantic search over the SAD. A top score >= *score_threshold* is *soft*
        coverage the caller must route through the skeptic + a human before trusting.

    The SAD is identified by the ``doc_type="sad"`` facet stamped at index time. Returns
    ``{covered, confidence: hard|soft|none, sad_section, matched_entities,
    missing_entities, score, note}``.
    """
    _require_nonempty_index(pipeline)
    entities = [e for e in (entities or []) if e and e.strip()]
    expected = _expected_sad_sections(decision)

    sad_chunks = [r for r in pipeline.store.get_corpus() if r.metadata.get("doc_type") == "sad"]
    if not sad_chunks:
        return {
            "covered": False,
            "confidence": "none",
            "sad_section": "",
            "matched_entities": [],
            "missing_entities": entities,
            "score": 0.0,
            "note": "No SAD found in the index (no chunk has doc_type='sad').",
        }

    # ── Tier 1: hard entity + expected-section match (objective) ──
    matched: list[str] = []
    missing: list[str] = []
    hard_section = ""
    for ent in entities:
        low = ent.lower()
        hit = next(
            (
                r
                for r in sad_chunks
                if low in r.content.lower()
                and (not expected or r.metadata.get("section_type") in expected)
            ),
            None,
        )
        if hit is not None:
            matched.append(ent)
            hard_section = hard_section or hit.metadata.get("breadcrumb", "")
        else:
            missing.append(ent)

    if entities and not missing:
        return {
            "covered": True,
            "confidence": "hard",
            "sad_section": hard_section,
            "matched_entities": matched,
            "missing_entities": [],
            "score": 1.0,
            "note": "All decision entities are present in the expected SAD section.",
        }

    # ── Tier 2: section-scoped semantic fallback (soft → skeptic + human) ──
    primary = expected[0] if expected else None
    candidates = [
        d
        for d in run_search(pipeline, decision, 5, primary, None, truncate=snippet_chars)
        if d.get("doc_type") == "sad"
    ]
    top = candidates[0] if candidates else None
    score = float(top["score"]) if top else 0.0
    covered = score >= score_threshold
    return {
        "covered": covered,
        "confidence": "soft",
        "sad_section": top["breadcrumb"] if top else "",
        "matched_entities": matched,
        "missing_entities": missing,
        "score": score,
        "note": (
            "Soft semantic match - confirm with the sad-skeptic + a human before trusting."
            if covered
            else "No SAD coverage for this decision; likely drift - propose a SAD patch."
        ),
    }


# ── Server factory ─────────────────────────────────────────────────────────────


def build_server(config: PipelineConfig, *, pipeline: SemanticPipeline | None = None) -> FastMCP:
    """Build the ``sdd-semantic`` MCP server exposing the search tools.

    Constructs a :class:`SemanticPipeline` once (cheap — the embedder/store load
    lazily on first search). The ``pipeline`` seam lets tests inject a model-free
    pipeline. A tool that raises is turned by FastMCP into an ``isError`` result,
    so the agent sees a clean message (e.g. an empty-index or provenance error)
    rather than a dead server.
    """
    pipe = pipeline if pipeline is not None else SemanticPipeline(config=config)
    server = FastMCP("sdd-semantic")

    @server.tool()
    def semantic_search(
        query: str,
        top_k: int = 5,
        section_type: str | None = None,
        space: str | None = None,
        hybrid: bool | None = None,
    ) -> list[dict]:
        """Semantic search over the indexed SDD/Confluence corpus.

        Returns the top_k most relevant chunks with full content, score, title,
        source_url, breadcrumb, section_type, space, entities and tags. Optional
        filters narrow the results:
          - section_type: overview | architecture | api | decision | alternative |
            tradeoff | consequence | done_criteria | deployment | data_model | security
          - space: a Confluence space key (see list_spaces)
          - hybrid: fuse dense + BM25 (omit to use the server default)
        """
        return run_search(pipe, query, top_k, section_type, space, hybrid)

    @server.tool()
    def find_decision_context(topic: str) -> dict:
        """Gather grouped corpus context for drafting an ADR about *topic*.

        Fans the topic across the ADR-template sections and returns snippet-sized
        results grouped as: general (best overall matches), context, decision,
        alternatives, tradeoffs, consequences, done_criteria. Use this first when
        drafting an ADR, then call semantic_search to pull a passage in full.
        """
        return find_decision_context_impl(pipe, topic)

    @server.tool()
    def list_section_types() -> list[str]:
        """List the valid section_type filter values for semantic_search."""
        return list_section_type_values()

    @server.tool()
    def list_spaces() -> list[str]:
        """List the Confluence space keys present in the index."""
        return list_spaces_impl(pipe)

    @server.tool()
    def find_sad_coverage(decision: str, entities: list[str] | None = None) -> dict:
        """Check whether a decision is reflected in the Software Architecture Document (SAD).

        Pass the decision statement and its named entities (service / technology /
        topic names). Returns {covered, confidence, sad_section, matched_entities,
        missing_entities, score, note}. confidence='hard' is an objective entity+section
        match (trust it); 'soft' is a semantic-only match to confirm via the sad-skeptic
        + a human; covered=false means the SAD does not record this decision yet (drift -
        propose a SAD patch). Requires a dense/lexical index built with doc_type stamping.
        """
        return find_sad_coverage_impl(pipe, decision, entities)

    return server


def run_server(config: PipelineConfig) -> None:
    """Eagerly warm the pipeline (logging to stderr), then serve over stdio.

    Warm-up loads the embedding model and runs one query so the first real tool
    call is fast and a provenance mismatch surfaces here (in the VS Code server
    log) rather than as a cryptic first-call error. Nothing is written to stdout.
    """
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(levelname)s sdd-mcp: %(message)s",
    )

    pipe = SemanticPipeline(config=config)
    server = build_server(config, pipeline=pipe)

    persist = config.chroma_persist_dir
    try:
        count = pipe.store.count
    except Exception as exc:  # opening a missing/corrupt index must not crash startup
        logger.error("could not open index at %r: %s", persist, exc)
        count = 0
    logger.info(
        "index: %s chunk(s) at %r (backend=%s)", count, persist, config.vector_store_backend
    )

    lexical = config.lexical_only or pipe._index_is_lexical()
    if count > 0:
        if lexical:
            logger.info("lexical (BM25) mode: no embedding model will be loaded")
        else:
            logger.info(
                "loading embedding model (provider=%s model=%s)...",
                config.embedding_provider,
                config.embedding_model,
            )
        try:
            pipe.search("warmup", n_results=1)
            verb = "index ready (lexical)" if lexical else "model loaded, index verified"
            logger.info("ready: %s (%s chunk(s))", verb, count)
        except ValueError as exc:
            logger.error("index/provenance check failed: %s", exc)
            logger.error("server will start; tool calls will return this error until fixed.")
        except Exception as exc:  # never block startup on a warm-up failure
            logger.error("warm-up failed (%s); model will load lazily on first call.", exc)
    else:
        logger.warning(
            "index is empty - run 'sdd-pipeline index' first; tool calls return an empty-index error."
        )

    server.run(transport="stdio")
