"""
Stage 7c: Lexical (BM25) retrieval and rank fusion.

Pure-Python and deterministic — no external services, no new dependency.
Complements the dense vector search with a sparse keyword signal so that
literal-phrase queries ("install vscode") rank the passage that *contains*
the phrase, not merely the one that is topically near it.

The two ranked id-lists (dense + lexical) are combined with Reciprocal Rank
Fusion, which is robust to the two scorers living on different scales.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import cache
from typing import Any

# ``[^\W_]`` is a Unicode word char excluding underscore — i.e. a letter or digit in ANY
# script. This keeps the legacy identifier-splitting behaviour (split on ``_`` and
# punctuation, like the old ``[a-z0-9]+``) while matching accented German/French/Italian
# letters (ä ö ü ß é è à ì ò ù) so non-English lexical search is no longer silently broken.
_TOKEN_RE = re.compile(r"[^\W_]+")


@cache
def _get_stemmer(language: str) -> Any | None:
    """Return a cached snowball stemmer for *language*, or None if unavailable.

    Import-guarded: ``snowballstemmer`` is an optional extra. When it (or the language)
    is missing, returns None so ``tokenize`` falls back to unstemmed tokens — stemming is
    a recall optimisation, never a hard dependency.
    """
    from .lang_rules import get_lang_pack

    name = get_lang_pack(language).snowball_name
    if not name:
        return None
    try:
        import snowballstemmer
    except ImportError:
        return None
    try:
        return snowballstemmer.stemmer(name)
    except Exception:  # unknown language name → no stemming
        return None


def tokenize(text: str, *, language: str = "en", stem: bool = False) -> list[str]:
    """Lowercase and split into alphanumeric tokens (identifiers survive).

    Unicode-aware, so accented letters are kept. When *stem* is true, tokens are reduced
    to their snowball stem for *language* (both corpus and query must use the same
    settings — :class:`BM25Index` guarantees this). Stemming is skipped silently if
    ``snowballstemmer`` is not installed.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    if stem:
        stemmer = _get_stemmer(language)
        if stemmer is not None:
            return list(stemmer.stemWords(tokens))
    return tokens


class BM25Index:
    """
    Minimal BM25 Okapi index over an in-memory corpus.

    Built per query from the current collection; corpora are small (one to a
    few documents' worth of chunks), so rebuild cost is negligible.
    """

    def __init__(
        self,
        documents: list[tuple[str, str]],
        k1: float = 1.5,
        b: float = 0.75,
        *,
        language: str = "en",
        stem: bool = False,
    ) -> None:
        self.k1 = k1
        self.b = b
        # Corpus and query MUST tokenize identically, so the language/stem settings are
        # stored on the index and reused by ``scores``.
        self.language = language
        self.stem = stem
        self.ids = [doc_id for doc_id, _ in documents]
        self.term_freqs = [
            Counter(tokenize(text, language=language, stem=stem)) for _, text in documents
        ]
        self.doc_len = [sum(tf.values()) for tf in self.term_freqs]
        self.n = len(documents)
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0

        df: Counter[str] = Counter()
        for tf in self.term_freqs:
            df.update(tf.keys())
        # BM25+ style idf floor keeps every idf strictly positive.
        self.idf = {
            term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def scores(self, query: str) -> dict[str, float]:
        """Return {doc_id: bm25_score} for every document in the corpus."""
        q_terms = tokenize(query, language=self.language, stem=self.stem)
        avgdl = self.avgdl or 1.0
        out: dict[str, float] = {}
        for i, doc_id in enumerate(self.ids):
            tf = self.term_freqs[i]
            dl = self.doc_len[i] or 1
            score = 0.0
            for term in q_terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = freq + self.k1 * (1 - self.b + self.b * dl / avgdl)
                score += idf * (freq * (self.k1 + 1)) / denom
            out[doc_id] = score
        return out

    def top(self, query: str, n: int) -> list[str]:
        """Return up to *n* doc_ids ranked by BM25, dropping zero-score docs."""
        ranked = sorted(self.scores(query).items(), key=lambda kv: kv[1], reverse=True)
        return [doc_id for doc_id, score in ranked if score > 0.0][:n]


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """
    Fuse several ranked id-lists into one ordering.

    Each list contributes ``1 / (k + rank)`` (rank 0-based) per id; scores are
    summed across lists. Returns ``[(doc_id, fused_score), ...]`` best-first.
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
