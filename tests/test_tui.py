"""
Tests for the interactive search TUI (``sdd_pipeline.tui``).

Skipped entirely when the optional ``textual`` extra is absent. The pure helpers
are tested directly; the app behaviour is exercised through Textual's headless
``run_test()`` pilot with a stubbed pipeline (no embedding model is loaded).
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from sdd_pipeline.config import PipelineConfigfrom sdd_pipeline.models import SectionTypefrom sdd_pipeline.tui import (    SearchApp,
    format_preview,
    parse_top_k,
    resolve_section_type,
)
from sdd_pipeline.vector_store import SearchResult

def _result(content: str = "hello world", **meta) -> SearchResult:
    metadata = {"breadcrumb": "Service > Auth", "section_type": "api", "title": "Doc"}
    metadata.update(meta)
    return SearchResult(chunk_id="c1", content=content, metadata=metadata, distance=0.25)


# ── pure helpers ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5", 5), ("0", 1), ("-3", 1), ("", 10), ("abc", 10), ("  7  ".strip(), 7)],
)
def test_parse_top_k(raw, expected):
    assert parse_top_k(raw) == expected


def test_resolve_section_type():
    assert resolve_section_type("api") == SectionType.API
    assert resolve_section_type("") is None
    assert resolve_section_type(None) is None
    assert resolve_section_type("not-a-type") is None


def test_format_preview_contains_metadata_and_content():
    text = format_preview(_result(content="body text here", source_url="http://x/y"))
    plain = text.plain
    assert "Doc" in plain
    assert "Service > Auth" in plain
    assert "type=api" in plain
    assert "score=0.750" in plain  # 1 - distance(0.25)
    assert "http://x/y" in plain
    assert "body text here" in plain


def test_format_preview_does_not_parse_brackets_as_markup():
    # Content with bracket-y text must survive verbatim (no Rich markup parsing).
    text = format_preview(_result(content="config = [default: 5] and [red]x[/red]"))
    assert "[default: 5]" in text.plain
    assert "[red]x[/red]" in text.plain


# ── app behaviour (headless pilot) ───────────────────────────────────────────────


def test_search_populates_table_and_preview():
    canned = [_result(content="first"), _result(content="second", title="Other")]

    async def scenario():
        app = SearchApp(PipelineConfig())
        # Stub the (otherwise model-loading) search; keeps this fast and offline.
        app.pipeline.search = lambda *a, **k: canned
        async with app.run_test() as pilot:
            await pilot.press(*"auth")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            from textual.widgets import DataTable, Static

            assert app.query_one("#results", DataTable).row_count == 2
            assert "first" in app.query_one("#preview", Static).renderable.plain

    asyncio.run(scenario())


def test_search_error_shows_status_and_clears():
    def boom(*a, **k):
        raise ValueError("provenance mismatch")

    async def scenario():
        app = SearchApp(PipelineConfig())
        app.pipeline.search = boom
        async with app.run_test() as pilot:
            await pilot.press(*"auth")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            from textual.widgets import DataTable, Static

            assert app.query_one("#results", DataTable).row_count == 0
            assert "provenance mismatch" in app.query_one("#status", Static).renderable.plain

    asyncio.run(scenario())
