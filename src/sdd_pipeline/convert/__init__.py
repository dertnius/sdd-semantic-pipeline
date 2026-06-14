"""Confluence / HTML → GitLab-flavoured Markdown conversion (flow B).

The converter is independent of the indexing/search pipeline (flow A). Public
surface:

- :func:`convert_file` — convert one rendered-HTML export to Markdown.
- :func:`resolve_pandoc`, :func:`postprocess`, :func:`stats` — shared helpers.
- :class:`ConversionError`, :class:`ConversionNotes` — error / report contracts.

A docx→Markdown path is planned and will live in this package alongside the HTML
one, reusing :mod:`sdd_pipeline.convert.base`.
"""

from .base import (
    ConversionError,
    ConversionNotes,
    postprocess,
    resolve_pandoc,
    stats,
)
from .html_to_gitlab_md import convert_file

__all__ = [
    "ConversionError",
    "ConversionNotes",
    "convert_file",
    "postprocess",
    "resolve_pandoc",
    "stats",
]
