"""
Per-document language detection (optional, model-free).

A thin, import-guarded wrapper over the pure-Python ``langdetect`` library (the ``[lang]``
extra). It is used only when ``config.language == "auto"`` — explicit ``--lang`` runs never
import it. Detection is constrained to :data:`lang_rules.SUPPORTED_LANGUAGES` and degrades
to a configurable default whenever langdetect is absent, unsure, or returns an unsupported
code, so enrichment always has a usable language.

No ML model and no network: langdetect ships its own character-n-gram profiles.
"""

from __future__ import annotations

from .lang_rules import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language

# langdetect is non-deterministic by default (random seed); pin it so the same text always
# detects the same language → reproducible enrichment and stable vectors.
_LANGDETECT_SEED = 0


def langdetect_available() -> bool:
    """True if the optional ``langdetect`` dependency can be imported."""
    try:
        import langdetect  # noqa: F401
    except ImportError:
        return False
    return True


def detect_language(
    text: str,
    *,
    default: str = DEFAULT_LANGUAGE,
    allowed: tuple[str, ...] = SUPPORTED_LANGUAGES,
) -> str:
    """Return a supported ISO code for *text*'s language, else *default*.

    Falls back to *default* when: ``langdetect`` is not installed, *text* is too short/
    empty, detection raises, or the detected code is not in *allowed*. The result is always
    normalised to a supported code (see :func:`lang_rules.normalize_language`).
    """
    if not text or not text.strip():
        return normalize_language(default)
    try:
        from langdetect import DetectorFactory, detect
    except ImportError:
        return normalize_language(default)

    DetectorFactory.seed = _LANGDETECT_SEED
    try:
        code = detect(text)
    except Exception:
        return normalize_language(default)

    code = normalize_language(code)
    return code if code in allowed else normalize_language(default)
