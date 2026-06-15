"""
Per-file pipeline report (the ``sdd-pipeline report`` command).

For each HTML source it runs the FULL pipeline — convert (HTML→Markdown, 4 stages)
then index (AST → structural → enrich → chunk → gate) — capturing every stage's
intermediate artifact, measuring information loss vs the original HTML, building a
section→block→chunk + entity relationship graph, and surfacing the taxonomy and
vocabulary *adapted for that file*. It renders a self-contained HTML report per
file plus an index.

Deterministic and **model-free**: no embedder is constructed and nothing is
downloaded. Requires pandoc on PATH (convert + AST). All non-ASCII content goes
only into UTF-8 HTML/JSON artifacts; stdout stays ASCII.
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .ast_parser import generate_ast
from .chunking import chunk_document
from .config import PipelineConfig
from .convert.base import (
    ConversionError,
    ConversionNotes,
    _run_pandoc,
    resolve_pandoc,
)
from .convert.confluence_pf_filter import apply_confluence_filter
from .convert.html_to_gitlab_md import (
    _reject_if_storage_format,
    convert_file,
    preprocess,
)
from .doc_router import SAD_FINGERPRINT, _heading_keys, detect_doc_type, load_taxonomy, taxonomy_for
from .enrichment import enrich_document, extract_entities, extract_keyphrases, scan_corpus
from .pipeline import SemanticPipeline
from .quality import check_markdown
from .vocabulary import load_vocabulary

# ── Data contracts ─────────────────────────────────────────────────────────────


@dataclass
class StageArtifact:
    """One pipeline stage's verifiable output (dumped to a file + HTML digest)."""

    name: str  # original_html | stage_a_clean_html | stage_b_ast | ... | quality
    label: str
    filename: str  # relative artifact filename in the per-file dir
    summary: dict[str, Any]  # small HTML-embeddable digest (counts/sizes)
    preview: str = ""  # truncated text preview shown inline


@dataclass
class LossMetrics:
    visible_text_retention: float = 1.0  # 0..1 token-set overlap (approx.)
    dropped_text_chars: int = 0
    dropped_token_sample: list[str] = field(default_factory=list)
    stage_size_deltas: dict[str, int] = field(default_factory=dict)
    lossy_macro_counts: dict[str, int] = field(default_factory=dict)
    convert_warnings: list[str] = field(default_factory=list)
    convert_errors: list[str] = field(default_factory=list)
    md_quality_issues: list[dict[str, str]] = field(default_factory=list)
    block_distribution: dict[str, int] = field(default_factory=dict)
    section_count: int = 0
    chunk_poison: int = 0
    chunk_weak: int = 0
    embed_budget_overflows: int = 0
    low_signal_chunks: int = 0  # hollow prose chunks (< 3 word tokens) — index noise
    tiers: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class GraphNode:
    id: str
    kind: str  # section | block | chunk | entity
    label: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    src: str
    dst: str
    kind: str  # contains | chunked_as | entity | depends_on | exposes


@dataclass
class GraphModel:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


@dataclass
class FileReport:
    source: Path
    out_dir: Path
    status: str = "ok"  # ok | rejected | error
    reason: str = ""
    stages: list[StageArtifact] = field(default_factory=list)
    loss: LossMetrics | None = None
    graph: GraphModel | None = None
    taxonomy: dict[str, Any] = field(default_factory=dict)
    vocabulary: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    chunk_count: int = 0


# ── Helpers ────────────────────────────────────────────────────────────────────

_WORD = re.compile(r"[a-z0-9]{3,}")
_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
# Macro-count keys that denote a lossy/degrading transform, mapped to (tier, desc).
_LOSSY_MACROS: dict[str, tuple[str, str]] = {
    "diagram": ("tier1", "diagram image/SVG reduced to caption text"),
    "data_uri": ("tier1", "data-URI image dropped (entropy)"),
    "data_uri_image": ("tier1", "data-URI image dropped (entropy)"),
    "gallery": ("tier1", "image gallery collapsed to filenames"),
    "merged_table": ("tier2", "merged table cells flattened (spans reset)"),
    "merged_table_simplified": ("tier2", "merged table simplified"),
    "nested_table": ("tier2", "nested table unwrapped"),
    "multi_header_collapsed": ("tier2", "tiered table header collapsed into body"),
    "layout": ("tier2", "multi-column layout flattened"),
    "dropped_tag": ("tier3", "unrecognised tag dropped"),
}
_TIER_LABELS = {
    "tier1": "Tier 1 — silent drop",
    "tier2": "Tier 2 — degradation (flagged)",
    "tier3": "Tier 3 — added noise",
}


def _write_json(path: Path, obj: object) -> None:
    # newline="\n": keep artifacts LF-only so they are byte-identical across
    # platforms (Windows would otherwise translate \n -> \r\n on write).
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


# Prose-shaped chunk types whose content should carry real meaning; a code/table
# chunk with few tokens is legitimate, a prose chunk with < 3 word tokens is a
# hollow lead-in/label fragment (index noise).
_LOW_SIGNAL_TYPES = frozenset({"paragraph", "list", "blockquote", "definition"})


def _is_low_signal(chunk: Any) -> bool:
    ct = getattr(chunk.content_type, "value", chunk.content_type)
    if ct not in _LOW_SIGNAL_TYPES:
        return False
    return len(re.findall(r"[A-Za-z0-9]+", chunk.content)) < 3


def _visible_text(html: str) -> str:
    """Visible text of *html* with obvious page chrome removed (approximate)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def _md_text(md: str) -> str:
    """Markdown minus YAML frontmatter (treated as plain text for token overlap)."""
    return _FRONTMATTER.sub("", md, count=1)


def _seed_vocab(config: PipelineConfig) -> list[str]:
    """Project seed vocabulary: entity_terms + the persisted vocab file (if set).

    ``load_vocabulary`` must not be called with an empty path — that resolves to
    ``.`` and raises PermissionError trying to read the directory.
    """
    persisted = load_vocabulary(config.entity_vocab_path) if config.entity_vocab_path else []
    return list(config.entity_terms) + persisted


# ── Convert-stage capture ──────────────────────────────────────────────────────


def _capture_convert_stages(
    src: Path, out_dir: Path, pandoc: str, rep: FileReport, html: str
) -> tuple[str, ConversionNotes]:
    """Produce the authoritative final Markdown via ``convert_file`` and dump each
    intermediate stage artifact (reconstructed by replaying the documented stage
    sequence). Returns ``(final_md, notes)``. The caller has already written
    ``original.html`` and cleared the storage front door."""
    # Authoritative conversion FIRST: final.md is exactly what `convert_file`
    # produces (its notes/metrics are authoritative for the loss metrics). The
    # replay below only reconstructs the per-stage intermediate artifacts for the
    # trace — it never feeds final.md, so any replay quirk can't change the corpus.
    _, final_md, metrics, notes_dict = convert_file(src, None, write=False, pandoc_path=pandoc)
    notes = ConversionNotes()
    notes.warnings = list(notes_dict.get("warnings", []))
    notes.errors = list(notes_dict.get("errors", []))
    notes.macro_counts = dict(notes_dict.get("macro_counts", {}))
    notes.languages = list(notes_dict.get("languages", []))
    notes.metadata = dict(notes_dict.get("metadata", {}))

    trace_notes = ConversionNotes()
    clean = preprocess(html, None, False, trace_notes)
    _write_text(out_dir / "stage_a_clean.html", clean)
    rep.stages.append(
        StageArtifact(
            "stage_a_clean_html",
            "2. Stage A — BeautifulSoup pre-clean (PFI HTML)",
            "stage_a_clean.html",
            {"chars": len(clean)},
            _truncate(clean),
        )
    )

    ast_json = _run_pandoc(pandoc, clean, ["--from", "html", "--to", "json", "--strip-comments"])
    _write_text(out_dir / "stage_b_ast.json", ast_json)
    rep.stages.append(
        StageArtifact(
            "stage_b_ast",
            "3. Stage B — pandoc html→json AST",
            "stage_b_ast.json",
            {"chars": len(ast_json)},
            _truncate(ast_json),
        )
    )

    filtered = apply_confluence_filter(ast_json, trace_notes)
    _write_text(out_dir / "stage_c_filtered_ast.json", filtered)
    rep.stages.append(
        StageArtifact(
            "stage_c_filtered_ast",
            "4. Stage C — panflute Confluence filter",
            "stage_c_filtered_ast.json",
            {"chars": len(filtered)},
            _truncate(filtered),
        )
    )

    raw_gfm = _run_pandoc(
        pandoc,
        filtered,
        ["--from", "json", "--to", "gfm", "--wrap=none", "--markdown-headings=atx"],
    )
    _write_text(out_dir / "raw.gfm.md", raw_gfm)
    rep.stages.append(
        StageArtifact(
            "raw_gfm",
            "5. Stage B' — pandoc json→gfm (raw)",
            "raw.gfm.md",
            {"chars": len(raw_gfm)},
            _truncate(raw_gfm),
        )
    )

    _write_text(out_dir / "final.md", final_md)
    rep.stages.append(
        StageArtifact(
            "final_md",
            "6. Stage D — final Markdown (+ frontmatter) [authoritative: convert_file]",
            "final.md",
            metrics,
            _truncate(final_md),
        )
    )
    return final_md, notes


# ── Indexing-stage capture ─────────────────────────────────────────────────────


def _capture_indexing_stages(
    final_md: str,
    out_dir: Path,
    config: PipelineConfig,
    rep: FileReport,
) -> tuple[Any, list[Any], list[Any], list[str]]:
    """Run the model-free indexing flow on final.md, dumping every artifact.
    Returns ``(enriched_doc, chunks, quality_reports, file_vocab)``."""
    pipe = SemanticPipeline(config=config)  # embedder is lazy; never touched here
    md_path = out_dir / "final.md"  # already written by the convert stage

    ast = generate_ast(md_path, config.pandoc_from_format)
    _write_json(out_dir / "ast.json", ast)
    rep.stages.append(
        StageArtifact("ast", "7. Markdown → pandoc AST", "ast.json", {}, _truncate(json.dumps(ast)))
    )

    doc = pipe.parse_file(md_path)  # pandoc -> structural
    _write_json(out_dir / "structural.json", asdict(doc))
    rep.stages.append(
        StageArtifact(
            "structural",
            "8. AST → structural model (sections/blocks)",
            "structural.json",
            {"sections": len(doc.iter_sections())},
            "",
        )
    )

    # Per-file adapted vocabulary: scan THIS doc seeded by the project vocab.
    file_vocab = scan_corpus([doc], seed_terms=_seed_vocab(config))

    inventory = pipe._build_inventory(doc) if config.inventory_enrichment else None
    enriched = enrich_document(doc, entity_terms=file_vocab, inventory=inventory)
    _write_json(out_dir / "enriched.json", asdict(enriched))
    rep.stages.append(
        StageArtifact(
            "enriched", "9. Enrich (type/genre/entities/tags/deps)", "enriched.json", {}, ""
        )
    )

    merge_prose, merge_definitions = pipe._resolve_merge_strategy(enriched)
    chunks = chunk_document(
        enriched,
        config.max_chunk_chars,
        merge_prose=merge_prose,
        entity_fn=lambda t: extract_entities(t, file_vocab),
        merge_definitions=merge_definitions,
        embed_char_budget=config.embed_char_budget,
        keyphrase_fn=extract_keyphrases if config.prose_keyphrases else None,
        overlap_sentences=config.chunk_overlap_sentences,
    )
    _write_json(out_dir / "chunks.json", [c.to_dict() for c in chunks])
    rep.stages.append(
        StageArtifact(
            "chunks",
            "10. Chunk → SemanticChunks",
            "chunks.json",
            {"chunks": len(chunks)},
            "",
        )
    )

    reports = pipe.gate_chunks(chunks)
    quality = [
        {
            "chunk_id": r.chunk_id,
            "issues": [
                {"rule": i.rule, "severity": i.severity, "detail": i.detail} for i in r.issues
            ],
        }
        for r in reports
    ]
    _write_json(out_dir / "quality.json", quality)
    poison = sum(1 for r in reports for i in r.issues if i.severity == "block")
    rep.stages.append(
        StageArtifact(
            "quality",
            "11. Chunk hygiene gate",
            "quality.json",
            {"chunks": len(reports), "poison": poison},
            "",
        )
    )
    rep.chunk_count = len(chunks)
    return enriched, chunks, reports, file_vocab


# ── Loss metrics ───────────────────────────────────────────────────────────────


def _compute_loss(
    original_html: str,
    final_md: str,
    notes: ConversionNotes,
    enriched: Any,
    reports: list[Any],
    src: Path,
) -> LossMetrics:
    orig = _tokens(_visible_text(original_html))
    md = _tokens(_md_text(final_md))
    retention = (len(orig & md) / len(orig)) if orig else 1.0
    dropped = sorted(orig - md)

    loss = LossMetrics(
        visible_text_retention=round(retention, 4),
        dropped_text_chars=max(0, len(_visible_text(original_html)) - len(_md_text(final_md))),
        dropped_token_sample=dropped[:40],
        stage_size_deltas={},  # filled by the caller from the captured stages
        lossy_macro_counts={
            k: v for k, v in notes.macro_counts.items() if k in _LOSSY_MACROS and v
        },
        convert_warnings=list(notes.warnings),
        convert_errors=list(notes.errors),
    )

    # Markdown quality (Tier-3 noise signals).
    mdq = check_markdown(str(src), final_md)
    loss.md_quality_issues = [
        {"rule": i.rule, "severity": i.severity, "detail": i.detail} for i in mdq.issues
    ]

    # Structural block distribution + sections.
    dist: dict[str, int] = {}
    has_table = False
    for sec in enriched.iter_sections():
        for b in sec.blocks:
            key = b.content_type.value
            dist[key] = dist.get(key, 0) + 1
            if key == "table":
                has_table = True
    loss.block_distribution = dist
    loss.section_count = len(enriched.iter_sections())

    # Chunk gate.
    loss.chunk_poison = sum(1 for r in reports for i in r.issues if i.severity == "block")
    loss.chunk_weak = sum(1 for r in reports for i in r.issues if i.severity == "warn")
    loss.embed_budget_overflows = sum(
        1
        for r in reports
        for i in r.issues
        if i.rule in ("chunk_over_budget", "chunk_truncation_risk")
    )

    loss.tiers = _build_tiers(loss, notes, dropped, has_table)
    return loss


def _build_tiers(
    loss: LossMetrics, notes: ConversionNotes, dropped: list[str], has_table: bool
) -> dict[str, list[str]]:
    tiers: dict[str, list[str]] = {"tier1": [], "tier2": [], "tier3": []}
    if dropped:
        sample = ", ".join(dropped[:12])
        tiers["tier1"].append(f"{len(dropped)} source token(s) absent from output (e.g. {sample})")
    for key, count in notes.macro_counts.items():
        if key in _LOSSY_MACROS and count:
            tier, desc = _LOSSY_MACROS[key]
            tiers[tier].append(f"{desc} ×{count} ({key})")
    if has_table:
        tiers["tier2"].append("table cell background-colour meaning lost (silent)")
    for issue in loss.md_quality_issues:
        if issue["severity"] == "block":
            tiers["tier3"].append(f"markdown: {issue['rule']} — {issue['detail']}")
    if loss.chunk_poison:
        tiers["tier3"].append(f"{loss.chunk_poison} poisoned chunk(s) (blocked from index)")
    return tiers


# ── Taxonomy / vocabulary ──────────────────────────────────────────────────────


def _compute_taxonomy(enriched: Any) -> dict[str, Any]:
    doc_type = detect_doc_type(enriched)
    sad_tax = load_taxonomy()
    applied = taxonomy_for(enriched, sad_tax)
    overlap = sorted(_heading_keys(enriched) & SAD_FINGERPRINT)
    return {"doc_type": doc_type, "fingerprint_overlap": overlap, "applied": applied}


def _compute_vocabulary(
    enriched: Any, config: PipelineConfig, file_vocab: list[str]
) -> dict[str, Any]:
    applied_entities: list[str] = []
    applied_depends_on: list[str] = []
    applied_exposes: list[str] = []
    for sec in enriched.iter_sections():
        applied_entities.extend(sec.entities)
        applied_depends_on.extend(sec.depends_on)
        applied_exposes.extend(sec.exposes)
    return {
        "seed_terms": sorted(set(_seed_vocab(config))),
        "scanned_terms": file_vocab,
        "applied_entities": sorted(set(applied_entities)),
        "applied_depends_on": sorted(set(applied_depends_on)),
        "applied_exposes": sorted(set(applied_exposes)),
    }


def _compute_inventory(enriched: Any, config: PipelineConfig) -> dict[str, list[dict[str, Any]]]:
    if not config.inventory_enrichment:
        return {}
    pipe = SemanticPipeline(config=config)
    inv = pipe._build_inventory(enriched)
    out: dict[str, list[dict[str, Any]]] = {}
    title_by_id = {s.section_id: s.title for s in enriched.iter_sections()}
    for section_id, records in inv.items():
        out[title_by_id.get(section_id, section_id)] = [
            {
                "text": r.text,
                "field": r.field,
                "source": r.source,
                "confidence": r.confidence,
            }
            for r in records
        ]
    return out


# ── Graph ──────────────────────────────────────────────────────────────────────


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "x"


def build_graph(enriched: Any, chunks: list[Any]) -> GraphModel:
    g = GraphModel()
    seen_entities: set[str] = set()

    def add_entity(value: str, kind: str, sec_id: str) -> None:
        eid = f"ent:{_slug(value)}"
        if eid not in seen_entities:
            seen_entities.add(eid)
            g.nodes.append(GraphNode(eid, "entity", value, {}))
        g.edges.append(GraphEdge(sec_id, eid, kind))

    def walk(sec: Any, parent_id: str | None) -> None:
        sid = f"sec:{sec.section_id}"
        g.nodes.append(
            GraphNode(
                sid,
                "section",
                sec.title or "(untitled)",
                {"level": sec.level, "type": sec.section_type.value, "genre": sec.genre.value},
            )
        )
        if parent_id:
            g.edges.append(GraphEdge(parent_id, sid, "contains"))
        for b in sec.blocks:
            bid = f"blk:{b.block_id}"
            lbl = b.content_type.value + (f" [{b.language}]" if b.language else "")
            g.nodes.append(GraphNode(bid, "block", lbl, {"preview": b.text[:50]}))
            g.edges.append(GraphEdge(sid, bid, "contains"))
        for e in sec.entities:
            add_entity(e, "entity", sid)
        for d in sec.depends_on:
            add_entity(d, "depends_on", sid)
        for x in sec.exposes:
            add_entity(x, "exposes", sid)
        for sub in sec.subsections:
            walk(sub, sid)

    for root in enriched.root_sections:
        walk(root, None)

    crumb_to_sec = {tuple(s.breadcrumb): f"sec:{s.section_id}" for s in enriched.iter_sections()}
    for idx, c in enumerate(chunks):
        cid = f"chunk:{c.chunk_id}"
        g.nodes.append(GraphNode(cid, "chunk", f"{c.content_type.value} #{idx}", {}))
        sec_id = crumb_to_sec.get(tuple(c.breadcrumb))
        if sec_id:
            g.edges.append(GraphEdge(sec_id, cid, "chunked_as"))
    return g


_KIND_COLOR = {
    "section": "#2563eb",
    "block": "#0891b2",
    "chunk": "#16a34a",
    "entity": "#9333ea",
}
_KIND_X = {"section": 20, "block": 320, "chunk": 590, "entity": 860}
_NODE_W = {"section": 250, "block": 240, "chunk": 240, "entity": 210}
_ROW_H = 26
_MAX_PER_KIND = 70


def render_graph_svg(g: GraphModel) -> str:
    """Layered, self-contained SVG: sections | blocks | chunks | entities."""
    pos: dict[str, tuple[int, int]] = {}
    y_by_kind = dict.fromkeys(_KIND_X, 40)
    shown: set[str] = set()
    dropped: dict[str, int] = dict.fromkeys(_KIND_X, 0)
    for n in g.nodes:
        if y_by_kind[n.kind] > 40 + _MAX_PER_KIND * _ROW_H:
            dropped[n.kind] += 1
            continue
        x = _KIND_X[n.kind]
        y = y_by_kind[n.kind]
        pos[n.id] = (x, y)
        shown.add(n.id)
        y_by_kind[n.kind] += _ROW_H
    height = max(max(y_by_kind.values()) + 20, 120)

    parts: list[str] = [
        f'<svg viewBox="0 0 1100 {height}" width="1100" xmlns="http://www.w3.org/2000/svg" '
        'font-family="system-ui,sans-serif" font-size="11">'
    ]
    # column headers
    for kind, x in _KIND_X.items():
        parts.append(
            f'<text x="{x}" y="22" fill="{_KIND_COLOR[kind]}" font-weight="700">{kind}s</text>'
        )
    # edges first (under nodes)
    for e in g.edges:
        if e.src not in pos or e.dst not in pos:
            continue
        x1, y1 = pos[e.src]
        x2, y2 = pos[e.dst]
        sx = x1 + _NODE_W[_node_kind(g, e.src)]
        sy = y1 + _ROW_H // 2
        ey = y2 + _ROW_H // 2
        mx = (sx + x2) // 2
        parts.append(
            f'<path d="M{sx},{sy} C{mx},{sy} {mx},{ey} {x2},{ey}" '
            'fill="none" stroke="#cbd5e1" stroke-width="1"/>'
        )
    # nodes
    for n in g.nodes:
        if n.id not in pos:
            continue
        x, y = pos[n.id]
        w = _NODE_W[n.kind]
        c = _KIND_COLOR[n.kind]
        label = _esc(n.label[:46])
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{_ROW_H - 6}" rx="4" '
            f'fill="{c}11" stroke="{c}" stroke-width="1"/>'
            f'<text x="{x + 6}" y="{y + 13}" fill="#0f172a">{label}</text>'
        )
    for kind, n_dropped in dropped.items():
        if n_dropped:
            parts.append(
                f'<text x="{_KIND_X[kind]}" y="{height - 8}" fill="#94a3b8">'
                f"+{n_dropped} more {kind}(s) not shown</text>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _node_kind(g: GraphModel, node_id: str) -> str:
    for n in g.nodes:
        if n.id == node_id:
            return n.kind
    return "section"


def render_edge_table(g: GraphModel) -> str:
    label_by_id = {n.id: n.label for n in g.nodes}
    rows = "".join(
        f"<tr><td>{_esc(label_by_id.get(e.src, e.src))}</td>"
        f"<td><code>{_esc(e.kind)}</code></td>"
        f"<td>{_esc(label_by_id.get(e.dst, e.dst))}</td></tr>"
        for e in g.edges
    )
    return (
        "<table class='grid'><thead><tr><th>source</th><th>relation</th><th>target</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


# ── HTML rendering ─────────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    return _html.escape(str(text), quote=True)


def _truncate(text: str, limit: int = 3500) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text) - limit} more chars]"


def _collapsible(title: str, body: str, open_: bool = False) -> str:
    o = " open" if open_ else ""
    return f"<details{o}><summary>{_esc(title)}</summary>{body}</details>"


def _code_block(text: str) -> str:
    return f"<pre class='art'>{_esc(text)}</pre>"


def _kv_table(rows: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><th>{_esc(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f"<table class='grid'>{body}</table>"


_CSS = """
:root{--t1:#dc2626;--t2:#d97706;--t3:#7c3aed;--ok:#16a34a;--bg:#f8fafc;--ink:#0f172a;}
*{box-sizing:border-box}body{font-family:system-ui,Segoe UI,sans-serif;color:var(--ink);
margin:0;padding:24px;background:#fff;line-height:1.45}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:24px 0 8px;border-bottom:2px solid #e2e8f0;padding-bottom:4px}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;font-size:12px;font-weight:700}
.badge.ok{background:var(--ok)}.badge.rejected{background:var(--t1)}.badge.error{background:#475569}
.gauge{height:18px;background:#e2e8f0;border-radius:9px;overflow:hidden;max-width:360px}
.gauge>span{display:block;height:100%;background:var(--ok)}
.tier{border-left:4px solid #ccc;padding:6px 10px;margin:6px 0;background:var(--bg);border-radius:4px}
.tier.tier1{border-color:var(--t1)}.tier.tier2{border-color:var(--t2)}.tier.tier3{border-color:var(--t3)}
.tier h3{margin:0 0 4px;font-size:13px}.tier ul{margin:0;padding-left:18px}
table.grid{border-collapse:collapse;width:100%;font-size:12px;margin:6px 0}
table.grid th,table.grid td{border:1px solid #e2e8f0;padding:4px 8px;text-align:left;vertical-align:top}
table.grid th{background:var(--bg)}
pre.art{background:#0f172a;color:#e2e8f0;padding:10px;border-radius:6px;overflow:auto;font-size:11px;max-height:380px}
details{margin:6px 0;border:1px solid #e2e8f0;border-radius:6px;padding:6px 10px}
summary{cursor:pointer;font-weight:600}
code{background:var(--bg);padding:1px 4px;border-radius:3px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0}
.card{background:var(--bg);border:1px solid #e2e8f0;border-radius:8px;padding:8px 14px;min-width:110px}
.card b{display:block;font-size:20px}.card span{font-size:11px;color:#64748b}
.svgwrap{overflow:auto;border:1px solid #e2e8f0;border-radius:6px;background:#fff}
a{color:#2563eb}
"""


def _tiers_html(tiers: dict[str, list[str]]) -> str:
    out = []
    for key in ("tier1", "tier2", "tier3"):
        items = tiers.get(key, [])
        body = (
            "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in items) + "</ul>"
            if items
            else "<em>none detected</em>"
        )
        out.append(f"<div class='tier {key}'><h3>{_esc(_TIER_LABELS[key])}</h3>{body}</div>")
    return "".join(out)


def render_file_html(rep: FileReport) -> str:
    p: list[str] = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>report: {_esc(rep.source.name)}</title>",
        f"<style>{_CSS}</style>",
        f"<h1>{_esc(rep.source.name)} <span class='badge {rep.status}'>{rep.status}</span></h1>",
    ]
    if rep.reason:
        p.append(f"<p>{_esc(rep.reason)}</p>")

    if rep.status == "rejected":
        p.append(
            "<h2>Why</h2><p>This file is Confluence <b>storage format</b>; the converter "
            "accepts rendered HTML only, so it was refused at the front door "
            "(100% information loss for the pipeline). See <code>rejection.json</code>.</p>"
        )
        p.append(
            _collapsible(
                "original.html",
                _code_block(
                    (rep.out_dir / "original.html").read_text("utf-8")
                    if (rep.out_dir / "original.html").exists()
                    else ""
                ),
            )
        )
        return "".join(p)

    loss = rep.loss
    if loss:
        pct = round(loss.visible_text_retention * 100, 1)
        p.append("<h2>Information loss &amp; deviation</h2>")
        p.append(
            f"<p>Visible-text retention (approx.): <b>{pct}%</b></p>"
            f"<div class='gauge'><span style='width:{pct}%'></span></div>"
        )
        p.append(
            "<div class='cards'>"
            f"<div class='card'><b>{rep.chunk_count}</b><span>chunks</span></div>"
            f"<div class='card'><b>{loss.section_count}</b><span>sections</span></div>"
            f"<div class='card'><b>{loss.chunk_poison}</b><span>poisoned chunks</span></div>"
            f"<div class='card'><b>{loss.chunk_weak}</b><span>weak chunks</span></div>"
            f"<div class='card'><b>{loss.low_signal_chunks}</b><span>low-signal chunks</span></div>"
            f"<div class='card'><b>{len(loss.convert_warnings)}</b><span>convert warnings</span></div>"
            "</div>"
        )
        p.append(_tiers_html(loss.tiers))
        details = []
        if loss.dropped_token_sample:
            details.append(
                _collapsible(
                    f"Dropped source tokens ({len(loss.dropped_token_sample)} sample)",
                    _code_block(", ".join(loss.dropped_token_sample)),
                )
            )
        if loss.lossy_macro_counts:
            details.append(
                _collapsible(
                    "Lossy transform counts",
                    _kv_table([(k, str(v)) for k, v in sorted(loss.lossy_macro_counts.items())]),
                )
            )
        if loss.block_distribution:
            details.append(
                _collapsible(
                    "Structural block distribution",
                    _kv_table([(k, str(v)) for k, v in sorted(loss.block_distribution.items())]),
                )
            )
        if loss.md_quality_issues:
            rows = "".join(
                f"<tr><td>{_esc(i['rule'])}</td><td>{_esc(i['severity'])}</td>"
                f"<td>{_esc(i['detail'])}</td></tr>"
                for i in loss.md_quality_issues
            )
            details.append(
                _collapsible(
                    "Markdown quality issues",
                    f"<table class='grid'><thead><tr><th>rule</th><th>sev</th><th>detail</th></tr>"
                    f"</thead><tbody>{rows}</tbody></table>",
                )
            )
        if loss.convert_warnings:
            details.append(
                _collapsible(
                    f"Convert warnings ({len(loss.convert_warnings)})",
                    "<ul>"
                    + "".join(f"<li>{_esc(w)}</li>" for w in loss.convert_warnings)
                    + "</ul>",
                )
            )
        p.append("".join(details))

    # Graph
    if rep.graph:
        p.append("<h2>Information graph</h2>")
        p.append(f"<div class='svgwrap'>{render_graph_svg(rep.graph)}</div>")
        p.append(
            _collapsible(f"Edge table ({len(rep.graph.edges)} edges)", render_edge_table(rep.graph))
        )

    # Taxonomy / vocabulary / inventory
    p.append("<h2>Taxonomy &amp; vocabulary (adapted for this file)</h2>")
    tax = rep.taxonomy
    applied = tax.get("applied") or {}
    p.append(
        _kv_table(
            [
                ("document type", _esc(tax.get("doc_type", "?"))),
                (
                    "SAD fingerprint matches",
                    _esc(", ".join(tax.get("fingerprint_overlap", [])) or "none"),
                ),
                (
                    "taxonomy applied",
                    _esc(
                        f"{len(applied)} section template(s)"
                        if applied
                        else "none — heading-only enrichment"
                    ),
                ),
            ]
        )
    )
    if applied:
        rows = "".join(
            f"<tr><td>{_esc(k)}</td><td>{_esc(v.get('orientation', ''))}</td>"
            f"<td>{_esc(', '.join(v.get('fields', [])))}</td></tr>"
            for k, v in sorted(applied.items())
        )
        p.append(
            _collapsible(
                "Applied taxonomy fields",
                f"<table class='grid'><thead><tr><th>section</th><th>orientation</th><th>fields</th>"
                f"</tr></thead><tbody>{rows}</tbody></table>",
            )
        )
    voc = rep.vocabulary
    p.append(
        _kv_table(
            [
                (
                    "scanned terms (this file)",
                    _esc(", ".join(voc.get("scanned_terms", [])) or "none"),
                ),
                ("applied entities", _esc(", ".join(voc.get("applied_entities", [])) or "none")),
                ("depends_on", _esc(", ".join(voc.get("applied_depends_on", [])) or "none")),
                ("exposes", _esc(", ".join(voc.get("applied_exposes", [])) or "none")),
            ]
        )
    )
    if rep.inventory:
        inv_html = []
        for section, records in rep.inventory.items():
            rows = "".join(
                f"<tr><td>{_esc(r['text'])}</td><td>{_esc(r['field'] or '(prose)')}</td>"
                f"<td>{_esc(r['source'])}</td><td>{r['confidence']}</td></tr>"
                for r in records
            )
            inv_html.append(
                f"<h4>{_esc(section)}</h4><table class='grid'><thead><tr><th>value</th>"
                f"<th>field</th><th>source</th><th>conf</th></tr></thead><tbody>{rows}</tbody></table>"
            )
        p.append(
            _collapsible("Entity inventory (vocabulary applied per section)", "".join(inv_html))
        )

    # Stage trace
    p.append("<h2>Pipeline stage trace (verifiable artifacts)</h2>")
    for s in rep.stages:
        digest = ", ".join(f"{k}={v}" for k, v in s.summary.items()) if s.summary else ""
        body = f"<p>{_esc(digest)} &middot; <a href='{_esc(s.filename)}'>{_esc(s.filename)}</a></p>"
        if s.preview:
            body += _code_block(s.preview)
        p.append(_collapsible(f"{s.label}", body))

    return "".join(p)


def render_index_html(reps: list[FileReport]) -> str:
    rows = []
    for r in reps:
        pct = f"{round(r.loss.visible_text_retention * 100, 1)}%" if r.loss else "—"
        t1 = len(r.loss.tiers.get("tier1", [])) if r.loss else 0
        t2 = len(r.loss.tiers.get("tier2", [])) if r.loss else 0
        t3 = len(r.loss.tiers.get("tier3", [])) if r.loss else 0
        poison = r.loss.chunk_poison if r.loss else 0
        link = f"{r.source.stem}/report.html"
        rows.append(
            f"<tr><td><a href='{_esc(link)}'>{_esc(r.source.name)}</a></td>"
            f"<td><span class='badge {r.status}'>{r.status}</span></td>"
            f"<td>{pct}</td><td>{r.chunk_count}</td><td>{poison}</td>"
            f"<td>{t1}/{t2}/{t3}</td></tr>"
        )
    return "".join(
        [
            "<!doctype html><meta charset='utf-8'><title>pipeline reports</title>",
            f"<style>{_CSS}</style><h1>Pipeline reports</h1>",
            "<p>Per-file pipeline trace, chunk quality, information loss, relationship graph, "
            "and adapted taxonomy/vocabulary.</p>",
            "<table class='grid'><thead><tr><th>file</th><th>status</th><th>retention</th>"
            "<th>chunks</th><th>poison</th><th>tiers 1/2/3</th></tr></thead><tbody>",
            "".join(rows),
            "</tbody></table>",
        ]
    )


# ── Orchestration ──────────────────────────────────────────────────────────────


def build_file_report(
    src: Path, out_dir: Path, config: PipelineConfig, *, pandoc_path: str | None = None
) -> FileReport:
    """Run the full pipeline for one HTML file. Never raises — failures are
    captured into ``status``/``reason``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = FileReport(source=src, out_dir=out_dir)

    original_html = src.read_text(encoding="utf-8")
    _write_text(out_dir / "original.html", original_html)
    rep.stages.append(
        StageArtifact(
            "original_html",
            "1. Original HTML",
            "original.html",
            {"chars": len(original_html), "visible_chars": len(_visible_text(original_html))},
            _truncate(original_html),
        )
    )

    # Storage-format front door first — pure regex, so a rejection needs no pandoc.
    try:
        _reject_if_storage_format(original_html, src)
    except ConversionError as exc:
        rep.status = "rejected"
        rep.reason = str(exc)
        _write_json(out_dir / "rejection.json", {"status": "rejected", "reason": str(exc)})
        rep.loss = LossMetrics(
            visible_text_retention=0.0,
            tiers={
                "tier1": ["entire document rejected (storage format)"],
                "tier2": [],
                "tier3": [],
            },
        )
        _write_text(out_dir / "report.html", render_file_html(rep))
        return rep

    try:
        pandoc = resolve_pandoc(pandoc_path)
    except ConversionError as exc:
        rep.status = "error"
        rep.reason = str(exc)
        _write_text(out_dir / "report.html", render_file_html(rep))
        return rep

    try:
        final_md, notes = _capture_convert_stages(src, out_dir, pandoc, rep, original_html)
    except ConversionError as exc:  # pandoc failure mid-convert — never raise out
        rep.status = "error"
        rep.reason = str(exc)
        _write_text(out_dir / "report.html", render_file_html(rep))
        return rep

    try:
        enriched, chunks, reports, file_vocab = _capture_indexing_stages(
            final_md, out_dir, config, rep
        )
        rep.loss = _compute_loss(original_html, final_md, notes, enriched, reports, src)
        rep.loss.stage_size_deltas = {
            s.name: int(s.summary.get("chars", 0)) for s in rep.stages if "chars" in s.summary
        }
        rep.loss.low_signal_chunks = sum(1 for c in chunks if _is_low_signal(c))
        rep.graph = build_graph(enriched, chunks)
        _write_json(
            out_dir / "graph.json",
            {
                "nodes": [asdict(n) for n in rep.graph.nodes],
                "edges": [asdict(e) for e in rep.graph.edges],
            },
        )
        rep.taxonomy = _compute_taxonomy(enriched)
        _write_json(out_dir / "taxonomy.json", rep.taxonomy)
        rep.vocabulary = _compute_vocabulary(enriched, config, file_vocab)
        _write_json(out_dir / "vocabulary.json", rep.vocabulary)
        rep.inventory = _compute_inventory(enriched, config)
        _write_json(out_dir / "inventory.json", rep.inventory)
    except Exception as exc:  # keep completed stages; mark the failing point
        rep.status = "error"
        rep.reason = f"{type(exc).__name__}: {exc}"

    _write_text(out_dir / "report.html", render_file_html(rep))
    return rep


def generate_reports(
    input_dir: Path,
    output_dir: Path,
    *,
    glob: str = "*.html",
    config: PipelineConfig | None = None,
    pandoc_path: str | None = None,
) -> list[FileReport]:
    """Build a report for every HTML file under *input_dir* and an index."""
    config = config or PipelineConfig()
    output_dir.mkdir(parents=True, exist_ok=True)
    srcs = sorted(p for p in input_dir.glob(glob) if p.suffix.lower() == ".html")

    reps: list[FileReport] = []
    for src in srcs:
        rep = build_file_report(src, output_dir / src.stem, config, pandoc_path=pandoc_path)
        reps.append(rep)

    _write_text(output_dir / "index.html", render_index_html(reps))
    aggregate = {
        "input_dir": str(input_dir),
        "glob": glob,
        "total_files": len(reps),
        "ok": sum(1 for r in reps if r.status == "ok"),
        "rejected": sum(1 for r in reps if r.status == "rejected"),
        "errored": sum(1 for r in reps if r.status == "error"),
        "files": [
            {
                "source": str(r.source),
                "status": r.status,
                "chunks": r.chunk_count,
                "retention": r.loss.visible_text_retention if r.loss else None,
                "poison": r.loss.chunk_poison if r.loss else 0,
                "low_signal": r.loss.low_signal_chunks if r.loss else 0,
            }
            for r in reps
        ],
    }
    _write_json(output_dir / "report.json", aggregate)
    return reps
