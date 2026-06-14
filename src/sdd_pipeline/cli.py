"""
CLI entry point: sdd-pipeline index | search | tui | export | scan | scan-taxonomy
| lint | convert | check | help
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import typer
from rich.console import Console
from rich.progress import track
from rich.table import Table

app = typer.Typer(
    name="sdd-pipeline",
    help="Semantic search pipeline for Confluence SDD documents.",
    add_completion=False,
    no_args_is_help=True,  # bare `sdd-pipeline` prints the command list instead of erroring
)
console = Console()


def _convert_confidence_reasons(notes: dict, max_unrecognized: int) -> list[str]:
    """Low-confidence reasons from a convert_file ``notes`` dict (Arm 2).

    Returns an empty list when the conversion looks trustworthy. A non-empty list
    means the converter's own signals say it likely mangled the page, so the file
    should be quarantined rather than indexed.
    """
    reasons: list[str] = []
    meta = notes.get("metadata", {}) or {}
    if meta.get("root_fallback") == "true":
        reasons.append("no recognised content container (fell back to <body>)")
    dropped = (notes.get("macro_counts", {}) or {}).get("dropped_tag", 0)
    if dropped > max_unrecognized:
        reasons.append(f"{dropped} leftover storage tag(s) dropped (> {max_unrecognized})")
    return reasons


# ── index ─────────────────────────────────────────────────────────────────────


@app.command()
def index(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Directory containing .md files."
    ),
    output_dir: str = typer.Option(
        "./build/index", "--output", "-o", help="Vector index persistence path."
    ),
    model: str = typer.Option(
        "BAAI/bge-large-en-v1.5",
        "--model",
        "-m",
        help="Local embedding model. Ignored when --provider azure (deployment from env).",
    ),
    provider: str = typer.Option("local", "--provider", help="Embedding backend: local | azure."),
    backend: str | None = typer.Option(
        None,
        "--backend",
        help="Vector store backend: memory (default) | chroma. "
        "Unset falls back to PIPELINE_VECTOR_STORE_BACKEND.",
    ),
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
    chunk_gate: bool | None = typer.Option(
        None,
        "--chunk-gate/--no-chunk-gate",
        help="Block a file from the index when any of its chunks is poisoned "
        "(markup/macro residue, truncation risk, or empty). Unset uses "
        "PIPELINE_CHUNK_GATE (default on).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse without indexing."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Index Confluence markdown files into the vector store."""
    from .config import PipelineConfig
    from .pipeline import SemanticPipeline

    overrides: dict = {
        "chroma_persist_dir": output_dir,
        "embedding_model": model,
        "embedding_provider": provider,
        "chunk_merge_prose": merge_prose,
        "chunk_merge_definitions": merge_definitions,
    }
    # Only override when the flag was given, so PIPELINE_VECTOR_STORE_BACKEND
    # keeps working when --backend is omitted.
    if backend is not None:
        overrides["vector_store_backend"] = backend
    if chunk_gate is not None:
        overrides["chunk_gate"] = chunk_gate
    config = PipelineConfig(**overrides)
    pipeline = SemanticPipeline(config=config)

    # Fail fast on a missing/unknown backend instead of per-file errors
    # (chromadb is an optional extra; a dry run never touches the store).
    if not dry_run:
        try:
            _ = pipeline.store
        except (ImportError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

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
    toc: bool = typer.Option(
        False,
        "--toc",
        help="Inject [[_TOC_]] (human-docs profile; default OFF for the embedding corpus).",
    ),
    keep_diagrams: bool = typer.Option(
        False, "--keep-diagrams", help="Keep SVG diagram HTML as-is."
    ),
    quarantine: bool | None = typer.Option(
        None,
        "--quarantine/--no-quarantine",
        help="Route low-confidence conversions (no recognised content container, or many "
        "leftover storage tags) to an _quarantine/ subdir and exit non-zero, instead of "
        "letting them enter the corpus. Unset uses PIPELINE_CONVERT_QUARANTINE.",
    ),
    max_unrecognized: int | None = typer.Option(
        None,
        "--max-unrecognized",
        help="Quarantine when the dropped/unrecognised-construct count exceeds this. "
        "Unset uses PIPELINE_CONVERT_MAX_UNRECOGNIZED (default 8).",
    ),
    pandoc_path: str | None = typer.Option(None, "--pandoc-path", help="Path to pandoc binary."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Convert all HTML files under a directory to Markdown and emit a JSON report."""
    import json
    from datetime import UTC, datetime

    from .config import PipelineConfig
    from .convert import ConversionError, convert_file, resolve_pandoc

    _cfg = PipelineConfig()
    quarantine = _cfg.convert_quarantine if quarantine is None else quarantine
    max_unrecognized = (
        _cfg.convert_max_unrecognized if max_unrecognized is None else max_unrecognized
    )

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
    quarantined = 0

    for src in track(html_files, description="Converting..."):
        # Mirror the source tree under output_dir when one is given.
        if output_dir is not None:
            rel = src.relative_to(input_dir).with_suffix(".md")
            out_target: Path | None = output_dir / rel
        else:
            out_target = None

        try:
            # Convert in-memory (write=False) so the confidence gate can route a
            # low-confidence result to _quarantine/ before it lands in the corpus.
            out_path, md, metrics, notes = convert_file(
                src,
                out_target,
                selector=selector,
                add_frontmatter=not no_frontmatter,
                add_toc=toc,
                keep_diagrams=keep_diagrams,
                pandoc_path=pandoc_path,
                space=space,
                source_url=source_url,
                labels=label_list,
                write=False,
            )
            reasons = _convert_confidence_reasons(notes, max_unrecognized) if quarantine else []
            if reasons:
                write_path = out_path.parent / "_quarantine" / out_path.name
            else:
                write_path = out_path
            write_path.parent.mkdir(parents=True, exist_ok=True)
            write_path.write_text(md, encoding="utf-8")

            slim = {k: metrics[k] for k in _METRIC_FIELDS}
            for k in _METRIC_FIELDS:
                totals[k] += slim[k]
            for key, n in notes.get("macro_counts", {}).items():
                macro_totals[key] = macro_totals.get(key, 0) + n
            warnings_total += len(notes.get("warnings", []))
            status = "quarantined" if reasons else "ok"
            if reasons:
                quarantined += 1
            else:
                succeeded += 1
            file_entries.append(
                {
                    "source": str(src),
                    "output": str(write_path),
                    "status": status,
                    "metrics": slim,
                    "notes": notes,
                    "quarantine_reasons": reasons,
                    "error": None,
                }
            )
            if reasons:
                console.print(
                    f"  [yellow]quarantine[/yellow] {src.name}: {'; '.join(reasons)} "
                    f"-> {write_path}"
                )
            elif verbose:
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
                    "quarantine_reasons": [],
                    "error": str(exc),
                }
            )
            console.print(f"  [red]fail[/red] {src.name}: {exc}")

    failed = len(html_files) - succeeded - quarantined
    report_doc = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_dir": str(input_dir),
        "glob": glob,
        "total_files": len(html_files),
        "succeeded": succeeded,
        "quarantined": quarantined,
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
        f"({quarantined} quarantined, {failed} failed, {warnings_total} warning(s)). "
        f"Report -> {report}"
    )
    raise typer.Exit(1 if (failed or quarantined) else 0)


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


# ── lint ──────────────────────────────────────────────────────────────────────


@app.command()
def lint(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Directory of .md files (your embedding corpus)."
    ),
    glob: str = typer.Option("**/*.md", "--glob", "-g", help="Markdown file glob pattern."),
    report: Path | None = typer.Option(
        None,
        "--report",
        "-r",
        help="JSON report path. Default: <input_dir>/quality-report.json",
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit non-zero if any file has a block-severity issue."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Lint raw source .md for embedding-harmful syntax/structure (report only).

    Reports leaked HTML, untranslated Confluence macros, whole-doc code dumps,
    TOC/nav link-dumps, near-empty stubs, and empty section headings. Pure text
    analysis -- no pandoc, no embedding model. Point it at your real embedding
    corpus: a docs tree that includes meta-documentation *about* Confluence
    syntax will self-report (those files legitimately contain the flagged tokens).
    """
    import json
    from datetime import UTC, datetime

    from .quality import check_markdown

    report_path = report if report is not None else input_dir / "quality-report.json"

    md_files = sorted(input_dir.glob(glob))
    if not md_files:
        console.print(f"[yellow]No markdown files matching {glob!r} under {input_dir}[/yellow]")
        raise typer.Exit(0)

    console.print(f"[cyan]Linting {len(md_files)} markdown files in {input_dir}[/cyan]")

    file_entries: list[dict] = []
    rule_counts: dict[str, int] = {}
    block_issues = 0
    warn_issues = 0
    files_with_issues = 0
    failed = 0

    for src in track(md_files, description="Linting..."):
        try:
            text = src.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            failed += 1
            file_entries.append(
                {
                    "source": str(src),
                    "is_embeddable": False,
                    "status": "error",
                    "error": str(exc),
                    "issues": [],
                }
            )
            console.print(f"  [red]fail[/red] {src.name}: {exc}")
            continue

        rpt = check_markdown(str(src), text)
        if not rpt.issues:
            if verbose:
                console.print(f"  [green]ok[/green]   {src.name}")
            continue

        files_with_issues += 1
        for issue in rpt.issues:
            rule_counts[issue.rule] = rule_counts.get(issue.rule, 0) + 1
            if issue.severity == "block":
                block_issues += 1
            else:
                warn_issues += 1
        file_entries.append(
            {
                "source": str(src),
                "is_embeddable": rpt.is_embeddable,
                "status": "ok",
                "error": None,
                "issues": [
                    {"rule": i.rule, "severity": i.severity, "detail": i.detail} for i in rpt.issues
                ],
            }
        )
        if verbose:
            tag = "warn" if rpt.is_embeddable else "block"
            console.print(f"  [yellow]{tag}[/yellow] {src.name} -> {len(rpt.issues)} issue(s)")

    clean_files = len(md_files) - files_with_issues - failed
    report_doc = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_dir": str(input_dir),
        "glob": glob,
        "total_files": len(md_files),
        "clean_files": clean_files,
        "files_with_issues": files_with_issues,
        "failed": failed,
        "block_issues": block_issues,
        "warn_issues": warn_issues,
        "rule_counts": rule_counts,
        "files": file_entries,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_doc, indent=2, ensure_ascii=False), encoding="utf-8")

    table = Table(title="Lint summary", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="green")
    table.add_row("files scanned", str(len(md_files)))
    table.add_row("clean", str(clean_files))
    table.add_row("with issues", str(files_with_issues))
    table.add_row("failed to read", str(failed))
    table.add_row("block issues", str(block_issues))
    table.add_row("warn issues", str(warn_issues))
    console.print(table)
    # ASCII-safe summary line (cp1252 consoles choke on emoji when redirected).
    console.print(
        f"\n[green]Done.[/green] {files_with_issues} of {len(md_files)} files have issues "
        f"({block_issues} block, {warn_issues} warn, {failed} unreadable). Report -> {report_path}"
    )

    raise typer.Exit(1 if (failed or (strict and block_issues)) else 0)


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
        Path("config/taxonomy.json"), "--out", "-o", help="Output taxonomy JSON."
    ),
    vocab_out: Path = typer.Option(
        Path("build/field_vocabulary.json"),
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
    index_dir: str = typer.Option("./build/index", "--index", "-i", help="Vector index path."),
    model: str = typer.Option("BAAI/bge-large-en-v1.5", "--model", "-m"),
    provider: str = typer.Option(
        "local", "--provider", help="Embedding backend: local | azure (must match the index)."
    ),
    backend: str | None = typer.Option(
        None,
        "--backend",
        help="Vector store backend: memory (default) | chroma (must match the index). "
        "Unset falls back to PIPELINE_VECTOR_STORE_BACKEND.",
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

    overrides: dict = {
        "chroma_persist_dir": index_dir,
        "embedding_model": model,
        "embedding_provider": provider,
    }
    # Only override when the flag was given, so PIPELINE_VECTOR_STORE_BACKEND
    # keeps working when --backend is omitted.
    if backend is not None:
        overrides["vector_store_backend"] = backend
    config = PipelineConfig(**overrides)
    pipeline = SemanticPipeline(config=config)

    st = SectionType(section_type) if section_type else None
    try:
        # An empty store passes provenance verification and returns [] — usually
        # the index was built with a different --backend or persist dir.
        if pipeline.store.count == 0:
            console.print(
                f"[yellow]Index at {index_dir!r} is empty for backend "
                f"{config.vector_store_backend!r} — was it built with a different "
                f"--backend or persist dir?[/yellow]"
            )
        results = pipeline.search(
            query, n_results=top_k, section_type=st, space=space, hybrid=hybrid
        )
    except (ValueError, ImportError) as exc:
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


# ── tui ─────────────────────────────────────────────────────────────────────


@app.command()
def tui(
    index_dir: str = typer.Option("./build/index", "--index", "-i", help="Vector index path."),
    model: str = typer.Option("BAAI/bge-large-en-v1.5", "--model", "-m"),
    provider: str = typer.Option(
        "local", "--provider", help="Embedding backend: local | azure (must match the index)."
    ),
    backend: str | None = typer.Option(
        None,
        "--backend",
        help="Vector store backend: memory (default) | chroma (must match the index). "
        "Unset falls back to PIPELINE_VECTOR_STORE_BACKEND.",
    ),
    hybrid: bool = typer.Option(
        False, "--hybrid", "-H", help="Start with hybrid (dense + BM25) retrieval enabled."
    ),
) -> None:
    """Launch an interactive search browser (TUI).

    Requires the optional 'tui' install extra. Keeps the embedding model and
    index warm so queries and filters are instant after the first search.
    Needs a real terminal (not a redirected pipe).
    """
    from .config import PipelineConfig

    overrides: dict = {
        "chroma_persist_dir": index_dir,
        "embedding_model": model,
        "embedding_provider": provider,
    }
    if backend is not None:
        overrides["vector_store_backend"] = backend
    config = PipelineConfig(**overrides)

    try:
        from .tui import run_search_tui
    except ImportError as exc:
        console.print(
            r'[red]Textual is not installed.[/red] Install the TUI extra: pip install ".\[tui]"'
        )
        raise typer.Exit(1) from exc

    run_search_tui(config, hybrid=hybrid)


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

    for pkg in ["panflute", "langchain_core", "sentence_transformers", "pydantic", "typer", "rich"]:
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "installed")
            rows.append((pkg, ver, True))
        except ImportError:
            rows.append((pkg, "NOT INSTALLED", False))

    # Optional chroma backend — informational, never gates the check.
    try:
        import chromadb

        rows.append(
            (
                "chromadb (chroma backend, optional)",
                getattr(chromadb, "__version__", "installed"),
                True,
            )
        )
    except ImportError:
        rows.append(
            ("chromadb (chroma backend, optional)", "not installed - pip install '.[chroma]'", True)
        )

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


@app.command("help")
def show_help(
    ctx: typer.Context,
    command: str | None = typer.Argument(
        None, help="Show full options for one command, e.g. 'help search'."
    ),
) -> None:
    """List the available commands and what each is for.

    With no argument, prints a grouped overview. Pass a command name
    (e.g. ``sdd-pipeline help index``) to see that command's full options.
    """
    # `help <command>` -> delegate to that command's own --help text.
    if command:
        group = typer.main.get_command(app)
        sub = group.get_command(ctx, command)
        if sub is None:
            console.print(
                f"[red]No such command: {command!r}.[/red] Run 'sdd-pipeline help' to see the list."
            )
            raise typer.Exit(2)
        sub_ctx = click.Context(sub, info_name=command, parent=ctx.find_root())
        typer.echo(sub.get_help(sub_ctx))
        return

    # Grouped overview. Kept ASCII-only so it survives a redirected cp1252 console.
    groups: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "Indexing & search (flow A: Confluence MD -> vector search)",
            [
                (
                    "index",
                    "Embed and index .md files into the vector store. (needs embedding model)",
                ),
                (
                    "search",
                    "Query the indexed corpus; add --hybrid for BM25+dense fusion. (needs model)",
                ),
                (
                    "tui",
                    "Interactive search browser (TUI); needs the tui extra. (needs model)",
                ),
                ("export", "Write each file's chunks to .chunks.json/.jsonl for other pipelines."),
                ("scan", "Discover and persist the cross-corpus entity vocabulary."),
                ("scan-taxonomy", "Derive a section->field taxonomy from the corpus's tables."),
                ("lint", "Report embedding-harmful syntax in raw .md before indexing."),
            ],
        ),
        (
            "HTML -> Markdown (flow B: independent converter)",
            [
                ("convert", "Convert Confluence-rendered HTML to GitLab Markdown + a JSON report."),
            ],
        ),
        (
            "Diagnostics",
            [
                ("check", "Verify runtime deps (pandoc, langchain-core, chromadb, openai)."),
                ("help", "Show this overview, or 'help <command>' for one command's options."),
            ],
        ),
    ]

    console.print(
        "\n[bold]sdd-pipeline[/bold] - semantic search pipeline for Confluence SDD documents.\n"
    )
    # One table per group; a fixed-width command column keeps descriptions aligned
    # across groups and stops the long group titles from squeezing the second column.
    for title, rows in groups:
        console.print(f"[bold]{title}[/bold]")
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("Command", style="cyan", no_wrap=True, width=16)
        table.add_column("What it does")
        for name, desc in rows:
            table.add_row(f"  {name}", desc)
        console.print(table)
        console.print()
    console.print(
        "\nCommands marked '(no model)' run pandoc-only; the rest load an embedding model."
        "\nRun [cyan]sdd-pipeline <command> --help[/cyan] or "
        "[cyan]sdd-pipeline help <command>[/cyan] for full options.\n"
    )


if __name__ == "__main__":
    app()
