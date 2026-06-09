"""
CLI entry point: sdd-pipeline index | search | check | convert | export | scan
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import track
from rich.table import Table

app = typer.Typer(
    name="sdd-pipeline",
    help="Semantic search pipeline for Confluence SDD documents.",
    add_completion=False,
)
console = Console()


# ── index ─────────────────────────────────────────────────────────────────────


@app.command()
def index(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Directory containing .md files."
    ),
    output_dir: str = typer.Option(
        "./data/chroma", "--output", "-o", help="ChromaDB persistence path."
    ),
    model: str = typer.Option(
        "BAAI/bge-large-en-v1.5",
        "--model",
        "-m",
        help="Local embedding model. Ignored when --provider azure (deployment from env).",
    ),
    provider: str = typer.Option("local", "--provider", help="Embedding backend: local | azure."),
    glob: str = typer.Option("**/*.md", "--glob", "-g", help="File glob pattern."),
    merge_prose: bool = typer.Option(
        False,
        "--merge-prose",
        help="Pack each section's prose into one chunk (code/tables stay separate).",
    ),
    merge_definitions: bool = typer.Option(
        False,
        "--merge-definitions",
        help="Pack each section's prose AND code into one chunk (tables stay separate). "
        "Overrides --merge-prose.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse without indexing."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Index Confluence markdown files into the vector store."""
    from .config import PipelineConfig
    from .pipeline import SemanticPipeline

    config = PipelineConfig(
        chroma_persist_dir=output_dir,
        embedding_model=model,
        embedding_provider=provider,
        chunk_merge_prose=merge_prose,
        chunk_merge_definitions=merge_definitions,
    )
    pipeline = SemanticPipeline(config=config)

    md_files = list(input_dir.glob(glob))
    if not md_files:
        console.print("[yellow]No markdown files found.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[cyan]Found {len(md_files)} markdown files in {input_dir}[/cyan]")

    # Cross-corpus scan (config/env only) needs all docs before enrichment, so it
    # delegates to the pipeline's two-pass index_directory rather than the per-file
    # loop. Honoured only for real index runs (a dry run never indexes).
    if config.entity_vocab_path and not dry_run:
        console.print(f"[cyan]Corpus scan enabled → {config.entity_vocab_path}[/cyan]")
        results = pipeline.index_directory(input_dir, glob)
        total = sum(c for c in results.values() if c > 0)
        errors = sum(1 for c in results.values() if c < 0)
        if verbose:
            for path_str, count in results.items():
                mark = "[red]✗[/red]" if count < 0 else "[green]✓[/green]"
                console.print(f"  {mark} {Path(path_str).name} → {max(count, 0)} chunks")
        console.print(
            f"\n[green]Done.[/green] {total} chunks indexed "
            f"from {len(md_files)} files ({errors} errors)."
        )
        return

    total, errors = 0, 0
    for path in track(md_files, description="Processing…"):
        try:
            if dry_run:
                count = len(pipeline.process_file(path))
            else:
                count = pipeline.index_file(path)
            total += count
            if verbose:
                console.print(f"  [green]✓[/green] {path.name} → {count} chunks")
        except Exception as exc:
            errors += 1
            console.print(f"  [red]✗[/red] {path.name}: {exc}")

    action = "processed" if dry_run else "indexed"
    console.print(
        f"\n[green]Done.[/green] {total} chunks {action} "
        f"from {len(md_files)} files ({errors} errors)."
    )


# ── convert ─────────────────────────────────────────────────────────────────

# Report fields surfaced per file (in display order).
_METRIC_FIELDS = ("sections", "pictures", "code_snippets", "lists", "tables", "urls")


@app.command()
def convert(
    input_dir: Path = typer.Argument(
        Path("docs"),
        exists=True,
        file_okay=False,
        help="Directory to scan recursively for HTML files.",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Where to write .md files (mirrors input tree). Default: alongside each HTML file.",
    ),
    glob: str = typer.Option("**/*.html", "--glob", "-g", help="HTML file glob pattern."),
    report: Path = typer.Option(
        Path("conversion-report.json"),
        "--report",
        "-r",
        help="Path for the JSON conversion report.",
    ),
    selector: str | None = typer.Option(None, "--selector", help="CSS selector for main content."),
    space: str = typer.Option(
        "", "--space", help="Confluence space key, written to frontmatter for provenance."
    ),
    source_url: str = typer.Option(
        "", "--source-url", help="Canonical source URL, written to frontmatter for provenance."
    ),
    labels: str = typer.Option(
        "", "--labels", help="Comma-separated labels, written to frontmatter for provenance."
    ),
    no_frontmatter: bool = typer.Option(False, "--no-frontmatter", help="Skip YAML front matter."),
    no_toc: bool = typer.Option(False, "--no-toc", help="Skip [[_TOC_]] directive."),
    keep_diagrams: bool = typer.Option(
        False, "--keep-diagrams", help="Keep SVG diagram HTML as-is."
    ),
    pandoc_path: str | None = typer.Option(None, "--pandoc-path", help="Path to pandoc binary."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Convert all HTML files under a directory to Markdown and emit a JSON report."""
    import json
    from datetime import UTC, datetime

    from .html_to_gitlab_md import ConversionError, convert_file, resolve_pandoc

    # Fail fast if pandoc is missing — same error for every file otherwise.
    try:
        resolve_pandoc(pandoc_path)
    except ConversionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    label_list = [s.strip() for s in labels.split(",") if s.strip()]

    html_files = sorted(input_dir.glob(glob))
    if not html_files:
        console.print(f"[yellow]No HTML files matching {glob!r} under {input_dir}[/yellow]")
        raise typer.Exit(0)

    console.print(f"[cyan]Found {len(html_files)} HTML files in {input_dir}[/cyan]")

    file_entries: list[dict] = []
    totals = dict.fromkeys(_METRIC_FIELDS, 0)
    macro_totals: dict[str, int] = {}
    warnings_total = 0
    succeeded = 0

    for src in track(html_files, description="Converting..."):
        # Mirror the source tree under output_dir when one is given.
        if output_dir is not None:
            rel = src.relative_to(input_dir).with_suffix(".md")
            out_target: Path | None = output_dir / rel
        else:
            out_target = None

        try:
            out_path, _md, metrics, notes = convert_file(
                src,
                out_target,
                selector=selector,
                add_frontmatter=not no_frontmatter,
                add_toc=not no_toc,
                keep_diagrams=keep_diagrams,
                pandoc_path=pandoc_path,
                space=space,
                source_url=source_url,
                labels=label_list,
            )
            slim = {k: metrics[k] for k in _METRIC_FIELDS}
            for k in _METRIC_FIELDS:
                totals[k] += slim[k]
            for key, n in notes.get("macro_counts", {}).items():
                macro_totals[key] = macro_totals.get(key, 0) + n
            warnings_total += len(notes.get("warnings", []))
            succeeded += 1
            file_entries.append(
                {
                    "source": str(src),
                    "output": str(out_path),
                    "status": "ok",
                    "metrics": slim,
                    "notes": notes,
                    "error": None,
                }
            )
            if verbose:
                summary = ", ".join(f"{slim[k]} {k}" for k in _METRIC_FIELDS)
                nw = len(notes.get("warnings", []))
                suffix = f" ({nw} warning(s))" if nw else ""
                console.print(f"  [green]ok[/green]   {src.name} -> {summary}{suffix}")
        except (ConversionError, OSError, ValueError) as exc:
            file_entries.append(
                {
                    "source": str(src),
                    "output": None,
                    "status": "error",
                    "metrics": None,
                    "notes": None,
                    "error": str(exc),
                }
            )
            console.print(f"  [red]fail[/red] {src.name}: {exc}")

    failed = len(html_files) - succeeded
    report_doc = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_dir": str(input_dir),
        "glob": glob,
        "total_files": len(html_files),
        "succeeded": succeeded,
        "failed": failed,
        "warnings_total": warnings_total,
        "totals": totals,
        "macro_counts": macro_totals,
        "files": file_entries,
    }

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(report_doc, indent=2, ensure_ascii=False), encoding="utf-8")

    table = Table(title="Conversion totals", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="green")
    for k in _METRIC_FIELDS:
        table.add_row(k, str(totals[k]))
    console.print(table)
    # ASCII-safe summary line (cp1252 consoles choke on emoji when redirected).
    console.print(
        f"\n[green]Done.[/green] {succeeded}/{len(html_files)} files converted "
        f"({failed} failed, {warnings_total} warning(s)). Report -> {report}"
    )
    raise typer.Exit(1 if failed else 0)


# ── export ────────────────────────────────────────────────────────────────────


@app.command()
def export(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Directory containing .md files."
    ),
    output_dir: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Directory for .chunks.json/.jsonl artifacts (mirrors input tree).",
    ),
    fmt: str = typer.Option("json", "--format", "-f", help="Output format: json | jsonl."),
    glob: str = typer.Option("**/*.md", "--glob", "-g", help="Markdown file glob pattern."),
    merge_prose: bool = typer.Option(
        False,
        "--merge-prose",
        help="Pack each section's prose into one chunk (code/tables stay separate).",
    ),
    merge_definitions: bool = typer.Option(
        False,
        "--merge-definitions",
        help="Pack each section's prose AND code into one chunk (tables stay separate); "
        "co-locates an instruction's explanation with its syntax. Overrides --merge-prose.",
    ),
    report: Path | None = typer.Option(
        None,
        "--report",
        "-r",
        help="JSON report path. Default: <output_dir>/export-report.json",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Export SemanticChunks for each markdown file to JSON/JSONL for other pipelines.

    Runs the deterministic stages (pandoc → structural → enrich → chunk) only;
    no embedding model is loaded. When PIPELINE_ENTITY_VOCAB_PATH is set, a two-pass
    cross-corpus scan runs first (discover + persist the vocabulary, then enrich each
    doc with it) so the exported chunks carry cross-corpus entities.
    """
    import json
    from datetime import UTC, datetime

    from .config import PipelineConfig
    from .pipeline import SemanticPipeline

    fmt = fmt.lower()
    if fmt not in {"json", "jsonl"}:
        console.print(f"[red]Invalid --format {fmt!r}; expected 'json' or 'jsonl'.[/red]")
        raise typer.Exit(2)

    report_path = report if report is not None else output_dir / "export-report.json"

    config = PipelineConfig(
        chunk_merge_prose=merge_prose, chunk_merge_definitions=merge_definitions
    )
    pipeline = SemanticPipeline(config=config)

    md_files = sorted(input_dir.glob(glob))
    if not md_files:
        console.print(f"[yellow]No markdown files matching {glob!r} under {input_dir}[/yellow]")
        raise typer.Exit(0)

    console.print(f"[cyan]Found {len(md_files)} markdown files in {input_dir}[/cyan]")

    suffix = ".chunks.jsonl" if fmt == "jsonl" else ".chunks.json"
    file_entries: list[dict] = []
    total_chunks = 0
    succeeded = 0
    vocab_terms = 0  # >0 only when a corpus scan ran

    def _write(src: Path, chunks: list) -> None:
        nonlocal total_chunks, succeeded
        # Mirror the input tree; append the multi-dot suffix manually so dotted
        # or extensionless stems are handled correctly.
        rel = src.relative_to(input_dir).with_suffix("")
        out = output_dir / rel.with_name(rel.name + suffix)
        out.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            payload = json.dumps([c.to_dict() for c in chunks], indent=2, ensure_ascii=False)
        else:
            payload = "\n".join(json.dumps(c.to_dict(), ensure_ascii=False) for c in chunks)
        out.write_text(payload, encoding="utf-8")
        total_chunks += len(chunks)
        succeeded += 1
        file_entries.append(
            {
                "source": str(src),
                "output": str(out),
                "chunks": len(chunks),
                "status": "ok",
                "error": None,
            }
        )
        if verbose:
            console.print(f"  [green]ok[/green]   {src.name} -> {len(chunks)} chunks")

    def _fail(src: Path, exc: Exception) -> None:
        file_entries.append(
            {"source": str(src), "output": None, "chunks": 0, "status": "error", "error": str(exc)}
        )
        console.print(f"  [red]fail[/red] {src.name}: {exc}")

    if config.entity_vocab_path:
        # Two-pass: discover + persist the cross-corpus vocabulary, then enrich
        # each doc with it. Pandoc-only — no embedding model is loaded.
        console.print(f"[cyan]Corpus scan enabled -> {config.entity_vocab_path}[/cyan]")
        vocabulary, parsed, failed_parses = pipeline.scan_and_persist(md_files)
        vocab_terms = len(vocabulary)
        for src in failed_parses:
            _fail(src, RuntimeError("parse failed (see logs)"))
        for src, doc in track(parsed, description="Exporting..."):
            try:
                _write(src, pipeline.enrich_and_chunk(doc, vocabulary))
            except Exception as exc:
                _fail(src, exc)
    else:
        for src in track(md_files, description="Exporting..."):
            try:
                _write(src, pipeline.process_file(src))
            except Exception as exc:
                _fail(src, exc)

    failed = len(md_files) - succeeded
    report_doc = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "glob": glob,
        "format": fmt,
        "total_files": len(md_files),
        "total_chunks": total_chunks,
        "succeeded": succeeded,
        "failed": failed,
        "entity_vocab_path": config.entity_vocab_path or None,
        "vocab_terms": vocab_terms,
        "files": file_entries,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_doc, indent=2, ensure_ascii=False), encoding="utf-8")

    console.print(
        f"\n[green]Done.[/green] {succeeded}/{len(md_files)} files exported "
        f"({total_chunks} chunks, {failed} failed). Report -> {report_path}"
    )
    raise typer.Exit(1 if failed else 0)


# ── scan ──────────────────────────────────────────────────────────────────────


@app.command()
def scan(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Directory containing .md files."
    ),
    vocab: Path | None = typer.Option(
        None,
        "--vocab",
        help="Output JSON vocabulary file. Overrides PIPELINE_ENTITY_VOCAB_PATH.",
    ),
    glob: str = typer.Option("**/*.md", "--glob", "-g", help="Markdown file glob pattern."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Discover and persist the cross-corpus entity vocabulary (no embedding model).

    Parses every markdown file (pandoc), scans for entity candidates across the
    whole set, merges the previously persisted vocabulary + PIPELINE_ENTITY_TERMS,
    and writes the sorted result to the vocabulary JSON — for review/editing before
    an index run. Pandoc-only; no model is loaded.
    """
    from .config import PipelineConfig
    from .pipeline import SemanticPipeline

    config = PipelineConfig(entity_vocab_path=str(vocab)) if vocab is not None else PipelineConfig()
    if not config.entity_vocab_path:
        console.print(
            "[red]No vocabulary path. Pass --vocab PATH or set PIPELINE_ENTITY_VOCAB_PATH.[/red]"
        )
        raise typer.Exit(2)

    pipeline = SemanticPipeline(config=config)
    md_files = sorted(input_dir.glob(glob))
    if not md_files:
        console.print(f"[yellow]No markdown files matching {glob!r} under {input_dir}[/yellow]")
        raise typer.Exit(0)

    console.print(f"[cyan]Scanning {len(md_files)} markdown files in {input_dir}[/cyan]")
    vocabulary, parsed, failed = pipeline.scan_and_persist(md_files)

    console.print(
        f"\n[green]Done.[/green] {len(vocabulary)} terms from {len(parsed)} files "
        f"({len(failed)} failed) -> {config.entity_vocab_path}"
    )
    if verbose and vocabulary:
        console.print(", ".join(vocabulary))
    for p in failed:
        console.print(f"  [red]x[/red] {p.name}")


# ── scan-taxonomy ───────────────────────────────────────────────────────────────


@app.command()
def scan_taxonomy(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Directory containing .md files."
    ),
    out: Path = typer.Option(
        Path("data/taxonomy.json"), "--out", "-o", help="Output taxonomy JSON."
    ),
    vocab_out: Path = typer.Option(
        Path("data/field_vocabulary.json"),
        "--vocab-out",
        help="Output field-frequency vocabulary JSON (review artifact).",
    ),
    min_docs: int = typer.Option(
        2, "--min-docs", "-n", help="Keep a field only if seen in >= this many documents."
    ),
    glob: str = typer.Option("**/*.md", "--glob", "-g", help="Markdown file glob pattern."),
) -> None:
    """Derive a data-aligned section->field taxonomy by scanning the corpus's tables.

    Aggregates table field names across all documents by document-frequency,
    keeps fields seen in >= --min-docs documents, and writes a canonical
    taxonomy.json plus a frequency-ranked field vocabulary for review (used to
    fill config/field_directions.yaml). Pandoc-only; no model is loaded.
    """
    from .corpus_taxonomy import build_corpus_taxonomy, taxonomy_to_json, vocabulary_to_json

    md_files = sorted(input_dir.glob(glob))
    if not md_files:
        console.print(f"[yellow]No markdown files matching {glob!r} under {input_dir}[/yellow]")
        raise typer.Exit(0)

    console.print(f"[cyan]Scanning {len(md_files)} markdown files in {input_dir}[/cyan]")
    taxonomy, vocab = build_corpus_taxonomy(input_dir, min_docs=min_docs, glob=glob)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(taxonomy_to_json(taxonomy) + "\n", encoding="utf-8")
    vocab_out.parent.mkdir(parents=True, exist_ok=True)
    vocab_out.write_text(vocabulary_to_json(vocab) + "\n", encoding="utf-8")

    console.print(
        f"\n[green]Done.[/green] {len(taxonomy)} sections (min_docs={min_docs}), "
        f"{len(vocab)} distinct fields -> {out}, {vocab_out}"
    )


# ── search ────────────────────────────────────────────────────────────────────


@app.command()
def search(
    query: str = typer.Argument(..., help="Natural-language search query."),
    index_dir: str = typer.Option("./data/chroma", "--index", "-i"),
    model: str = typer.Option("BAAI/bge-large-en-v1.5", "--model", "-m"),
    provider: str = typer.Option(
        "local", "--provider", help="Embedding backend: local | azure (must match the index)."
    ),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    section_type: str | None = typer.Option(
        None,
        "--section-type",
        "-s",
        help="Filter: overview | architecture | api | decision | alternative | tradeoff | "
        "consequence | done_criteria | deployment | data_model | security",
    ),
    space: str | None = typer.Option(None, "--space", help="Confluence space key filter."),
    hybrid: bool = typer.Option(
        False,
        "--hybrid",
        "-H",
        help="Fuse dense + lexical (BM25) rankings via Reciprocal Rank Fusion.",
    ),
) -> None:
    """Search the indexed SDD documents."""
    from .config import PipelineConfig
    from .models import SectionType
    from .pipeline import SemanticPipeline

    config = PipelineConfig(
        chroma_persist_dir=index_dir, embedding_model=model, embedding_provider=provider
    )
    pipeline = SemanticPipeline(config=config)

    st = SectionType(section_type) if section_type else None
    try:
        results = pipeline.search(
            query, n_results=top_k, section_type=st, space=space, hybrid=hybrid
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if not results:
        console.print("[yellow]No results.[/yellow]")
        raise typer.Exit(0)

    table = Table(title=f"Results for: {query!r}", show_lines=True)
    table.add_column("Score", width=6, style="green")
    table.add_column("Section path", style="cyan")
    table.add_column("Type", width=13)
    table.add_column("Content preview", max_width=58)

    for r in results:
        table.add_row(
            f"{r.score:.3f}",
            r.metadata.get("breadcrumb", ""),
            r.metadata.get("section_type", ""),
            r.content[:220].replace("\n", " "),
        )

    console.print(table)


# ── check ─────────────────────────────────────────────────────────────────────


@app.command()
def check() -> None:
    """Verify all runtime dependencies are installed."""
    import subprocess

    rows: list[tuple[str, str, bool]] = []

    rows.append(
        (
            "Python",
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            sys.version_info >= (3, 11),
        )
    )

    try:
        out = subprocess.check_output(["pandoc", "--version"]).decode().split("\n")[0]
        rows.append(("pandoc", out, True))
    except Exception as exc:
        rows.append(("pandoc", str(exc)[:60], False))

    for pkg in ["panflute", "chromadb", "sentence_transformers", "pydantic", "typer", "rich"]:
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "installed")
            rows.append((pkg, ver, True))
        except ImportError:
            rows.append((pkg, "NOT INSTALLED", False))

    # Optional Azure provider — informational, never gates the check.
    import os

    try:
        import openai

        rows.append(("openai (azure, optional)", getattr(openai, "__version__", "installed"), True))
    except ImportError:
        rows.append(("openai (azure, optional)", "not installed", True))

    for var in ("PIPELINE_AZURE_OPENAI_ENDPOINT", "PIPELINE_AZURE_OPENAI_DEPLOYMENT"):
        rows.append((var, "set" if os.environ.get(var) else "unset", True))
    # Never print the key value — only whether it is present.
    rows.append(
        (
            "PIPELINE_AZURE_OPENAI_API_KEY",
            "set" if os.environ.get("PIPELINE_AZURE_OPENAI_API_KEY") else "unset",
            True,
        )
    )

    table = Table(title="Environment check")
    table.add_column("Dependency")
    table.add_column("Version")
    table.add_column("OK?")
    all_ok = True
    for name, ver, ok in rows:
        table.add_row(name, ver, "[green]✓[/green]" if ok else "[red]✗[/red]")
        all_ok = all_ok and ok

    console.print(table)
    raise typer.Exit(0 if all_ok else 1)


if __name__ == "__main__":
    app()
