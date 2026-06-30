"""Minimal standalone error type for the vendored Gliffy converter.

The in-pipeline source imports ``ConversionError`` from the engine-agnostic
``convert.base`` layer (which also pulls in PyYAML). This Gliffy path only needs
the exception class, so the vendored copy defines it locally — keeping the
``.gliffy`` -> SVG converter pure-stdlib (no third-party dependency at all).
"""

from __future__ import annotations


class ConversionError(RuntimeError):
    """Raised when a diagram conversion cannot be completed."""
