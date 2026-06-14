"""
Interactive search browser (Textual TUI) for the indexed SDD corpus.

A thin *presentation* layer over :class:`sdd_pipeline.pipeline.SemanticPipeline`:
it keeps the embedding model and vector store warm in one process, so you can
iterate on queries and filters without paying the model-load cost on every run.

This module imports ``textual`` at import time, so it is loaded lazily from the
``sdd-pipeline tui`` CLI command — the core indexing/search/convert flows never
import it. Install with the optional extra::

    pip install ".[tui]"

The blocking search call runs in a worker thread (``asyncio.to_thread``) so the
UI stays responsive while the model embeds the query.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
)

from .models import SectionType
from .pipeline import SemanticPipeline

if TYPE_CHECKING:
    from .config import PipelineConfig
    from .vector_store import SearchResult

_SECTION_VALUES = [st.value for st in SectionType]


# ── Pure helpers (unit-testable without launching the app) ──────────────────────


def parse_top_k(raw: str, default: int = 10) -> int:
    """Coerce the top-k input box to a positive int, falling back on garbage."""
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def resolve_section_type(value: object) -> SectionType | None:
    """Map the section-type Select value (or blank) to a ``SectionType`` filter."""
    if not value or value is Select.BLANK:
        return None
    try:
        return SectionType(str(value))
    except ValueError:
        return None


def format_preview(result: SearchResult) -> Text:
    """Render a result's metadata + full content for the preview pane.

    Content is appended as a plain (markup-free) segment so stray ``[...]`` in the
    chunk text is never mis-parsed as Rich markup.
    """
    m = result.metadata
    text = Text()
    if m.get("title"):
        text.append(f"{m['title']}\n", style="bold")
    if m.get("breadcrumb"):
        text.append(f"{m['breadcrumb']}\n", style="cyan")
    bits = []
    if m.get("section_type"):
        bits.append(f"type={m['section_type']}")
    bits.append(f"score={result.score:.3f}")
    if m.get("content_type"):
        bits.append(str(m["content_type"]))
    if m.get("language"):
        bits.append(f"lang={m['language']}")
    text.append("  ".join(bits) + "\n", style="dim")
    if m.get("source_url"):
        text.append(f"{m['source_url']}\n", style="dim")
    text.append("\n")
    text.append(result.content or "")
    return text


# ── App ─────────────────────────────────────────────────────────────────────────


class SearchApp(App):
    """Live search over an indexed SDD corpus."""

    TITLE = "sdd-pipeline search"

    CSS = """
    #query { height: 3; }
    #filters { height: 3; }
    #filters > Select { width: 34; }
    #filters > Input { width: 16; margin-left: 1; }
    #filters > Switch { margin-left: 2; }
    #filters > #hybrid_label { width: auto; padding: 1 0; }
    #body { height: 1fr; }
    #results { width: 1fr; }
    #preview-scroll { width: 1fr; border-left: solid $accent; padding: 0 1; }
    #status { height: 1; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("escape", "focus_query", "Search box"),
    ]

    def __init__(self, config: PipelineConfig, hybrid: bool = False) -> None:
        super().__init__()
        self.config = config
        self._initial_hybrid = hybrid
        # Lazy wiring: constructing the pipeline does not load the model; the first
        # search does, and then it stays warm for every subsequent query.
        self.pipeline = SemanticPipeline(config=config)
        self._results: list[SearchResult] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Input(placeholder="Search query — press Enter to run", id="query")
        with Horizontal(id="filters"):
            yield Select(
                [(v, v) for v in _SECTION_VALUES],
                prompt="(any section type)",
                allow_blank=True,
                id="section",
            )
            yield Input(placeholder="space key", id="space")
            yield Input(value="10", placeholder="top-k", type="integer", id="topk")
            yield Switch(value=self._initial_hybrid, id="hybrid")
            yield Label("hybrid", id="hybrid_label")
        with Horizontal(id="body"):
            yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="preview-scroll"):
                yield Static("", id="preview")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.add_columns("Score", "Section path", "Type")
        self.query_one("#query", Input).focus()
        self._set_status(
            f"index={self.config.chroma_persist_dir}  "
            f"backend={self.config.vector_store_backend}  "
            f"model={self.config.embedding_model}"
        )

    # ── actions / events ──────────────────────────────────────────────────────

    def action_focus_query(self) -> None:
        self.query_one("#query", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._search()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._maybe_rerun()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._maybe_rerun()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if 0 <= event.cursor_row < len(self._results):
            self.query_one("#preview", Static).update(
                format_preview(self._results[event.cursor_row])
            )

    # ── search ────────────────────────────────────────────────────────────────

    def _search(self) -> None:
        query = self.query_one("#query", Input).value.strip()
        if query:
            self.run_search(query)

    def _maybe_rerun(self) -> None:
        query = self.query_one("#query", Input).value.strip()
        if query:
            self.run_search(query)

    @work(exclusive=True)
    async def run_search(self, query: str) -> None:
        self._set_status(f"Searching for {query!r}…")
        section = resolve_section_type(self.query_one("#section", Select).value)
        space = self.query_one("#space", Input).value.strip() or None
        hybrid = self.query_one("#hybrid", Switch).value
        top_k = parse_top_k(self.query_one("#topk", Input).value.strip())

        try:
            results = await asyncio.to_thread(
                self.pipeline.search, query, top_k, section, None, space, hybrid
            )
        except Exception as exc:  # provenance mismatch, empty/missing index, etc.
            self._results = []
            self._fill_table([])
            self.query_one("#preview", Static).update("")
            self._set_status(str(exc), style="red")
            return

        self._results = results
        self._fill_table(results)
        if results:
            self.query_one("#preview", Static).update(format_preview(results[0]))
            self._set_status(f"{len(results)} result(s) for {query!r}.")
        else:
            self.query_one("#preview", Static).update("")
            self._set_status(f"No results for {query!r}.")

    def _fill_table(self, results: list[SearchResult]) -> None:
        table = self.query_one("#results", DataTable)
        table.clear()
        for r in results:
            table.add_row(
                f"{r.score:.3f}",
                r.metadata.get("breadcrumb", ""),
                r.metadata.get("section_type", ""),
            )

    def _set_status(self, message: str, style: str = "") -> None:
        self.query_one("#status", Static).update(Text(message, style=style))


def run_search_tui(config: PipelineConfig, hybrid: bool = False) -> None:
    """Construct and run the interactive search app (blocks until quit)."""
    SearchApp(config, hybrid=hybrid).run()
