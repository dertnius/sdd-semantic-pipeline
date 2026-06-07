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

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase and split into alphanumeric tokens (identifiers survive)."""
    return _TOKEN_RE.findall(text.lower())


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
    ) -> None:
        self.k1 = k1
        self.b = b
        self.ids = [doc_id for doc_id, _ in documents]
        self.term_freqs = [Counter(tokenize(text)) for _, text in documents]
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
        q_terms = tokenize(query)
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
