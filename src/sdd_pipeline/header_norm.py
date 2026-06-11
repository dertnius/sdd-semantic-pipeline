"""
Header / column-label normalisation for template-derived taxonomy.

A single deterministic spec, applied **before** taxonomy extraction and again
when matching a live document's table headers to the taxonomy, so spelling and
formatting variants of the same column collapse to one canonical form.

Spec (in order), see :func:`normalise_header`:
1. lowercase
2. strip + collapse internal whitespace to a single space
3. strip parenthetical qualifiers — ``consumer (system)`` → ``consumer``
4. split on ``/`` and keep the first token — ``client/consumer`` → ``client``
5. naive singularise of each token (drop a trailing ``s``), guarded against
   ``ss``/``us``/``is``/``as`` endings — ``consumers`` → ``consumer``,
   ``related components`` → ``related component`` (``status`` is left intact)

The spec is intentionally conservative: it is meant to merge obvious variants
(``Consumer``/``Consumers``/``Consumer (system)``), not to do real lemmatisation.
"""

from __future__ import annotations

import re

_PAREN = re.compile(r"\([^)]*\)")
_WS = re.compile(r"\s+")
# Endings where a trailing 's' is not a plural marker.
_KEEP_S = ("ss", "us", "is", "as", "os")


def _singularise_token(tok: str) -> str:
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(_KEEP_S):
        return tok[:-1]
    return tok


def normalise_header(s: str) -> str:
    """Normalise a column header / field label to its canonical form.

    Returns ``""`` for an empty or whitespace/parenthetical-only input (used by
    the taxonomy extractor to detect empty header cells).
    """
    s = s.lower()
    s = _PAREN.sub(" ", s)
    s = s.split("/", 1)[0]
    s = _WS.sub(" ", s).strip()
    if not s:
        return ""
    return " ".join(_singularise_token(t) for t in s.split(" "))
