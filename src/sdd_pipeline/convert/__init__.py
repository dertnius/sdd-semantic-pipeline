"""Confluence / HTML / docx → GitLab-flavoured Markdown conversion (flow B).

The converter is independent of the indexing/search pipeline (flow A). Public
surface:

- :func:`convert_file` — convert one rendered-HTML export to Markdown.
- :func:`convert_docx_file` — convert one Word ``.docx`` to Markdown
  (pandoc-native; no bs4/panflute machinery).
- :func:`resolve_pandoc`, :func:`postprocess`, :func:`stats` — shared helpers.
- :class:`ConversionError`, :class:`ConversionNotes` — error / report contracts.

The HTML path (:mod:`html_to_gitlab_md`) and the docx path
(:mod:`docx_to_md`) both reuse the engine-agnostic shared layer in
:mod:`sdd_pipeline.convert.base`; importing one never pulls in the other's
engine-specific deps.
"""

from .base import (
    ConversionError,
    ConversionNotes,
    postprocess,
    resolve_pandoc,
    stats,
)
from .diagram_model import DiagramModel, Edge, Node
from .docx_to_md import convert_docx_file, harvest_docx_metadata
from .drawio import convert_gliffy_to_drawio_file, drawio_to_model, model_to_drawio
from .fidelity import compare_models, roundtrip_check
from .gliffy_to_svg import parse_gliffy, render_gliffy, resolve_gliffy_file
from .html_to_gitlab_md import convert_file

__all__ = [
    "ConversionError",
    "ConversionNotes",
    "DiagramModel",
    "Edge",
    "Node",
    "compare_models",
    "convert_docx_file",
    "convert_file",
    "convert_gliffy_to_drawio_file",
    "drawio_to_model",
    "harvest_docx_metadata",
    "model_to_drawio",
    "parse_gliffy",
    "postprocess",
    "render_gliffy",
    "resolve_gliffy_file",
    "resolve_pandoc",
    "roundtrip_check",
    "stats",
]
