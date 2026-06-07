"""Tests for sdd_pipeline.retrieval (BM25 + Reciprocal Rank Fusion)."""

from __future__ import annotations

from sdd_pipeline.retrieval import BM25Index, reciprocal_rank_fusion, tokenize


class TestTokenize:
    def test_lowercases_and_splits(self):
        assert tokenize("Install VSCode Now") == ["install", "vscode", "now"]

    def test_keeps_alphanumeric_identifiers(self):
        assert tokenize("port 30000 / coordinator-0") == ["port", "30000", "coordinator", "0"]

    def test_drops_punctuation(self):
        assert tokenize("a, b. c!") == ["a", "b", "c"]

    def test_empty(self):
        assert tokenize("") == []


class TestBM25Index:
    def _corpus(self) -> list[tuple[str, str]]:
        return [
            ("steps", "Install VSCode and configure the remote SSH host."),
            ("intro", "VSCode is a code editor that calls language servers."),
            ("docker", "Develop inside a Docker dev container."),
        ]

    def test_phrase_match_ranks_first(self):
        index = BM25Index(self._corpus())
        top = index.top("install vscode", n=3)
        assert top[0] == "steps"

    def test_zero_score_docs_excluded(self):
        index = BM25Index(self._corpus())
        # No corpus token matches → no results.
        assert index.top("kubernetes helm", n=3) == []

    def test_scores_cover_all_docs(self):
        index = BM25Index(self._corpus())
        scores = index.scores("vscode")
        assert set(scores) == {"steps", "intro", "docker"}
        assert scores["docker"] == 0.0  # 'vscode' not in the docker doc

    def test_rarer_term_outweighs_common_term(self):
        index = BM25Index(self._corpus())
        scores = index.scores("docker vscode")
        # 'docker' appears in 1 doc (rare, high idf); 'vscode' in 2 (common).
        assert scores["docker"] > scores["intro"]

    def test_empty_corpus_is_safe(self):
        index = BM25Index([])
        assert index.top("anything", n=5) == []
        assert index.scores("anything") == {}

    def test_top_respects_n(self):
        index = BM25Index(self._corpus())
        assert len(index.top("vscode code editor remote", n=1)) == 1


class TestReciprocalRankFusion:
    def test_consensus_top_wins(self):
        dense = ["a", "b", "c"]
        lexical = ["a", "c", "b"]
        fused = reciprocal_rank_fusion([dense, lexical])
        assert fused[0][0] == "a"

    def test_lexical_can_promote_over_dense_only(self):
        # 'x' is rank 3 in dense but rank 0 in lexical; 'y' only appears in dense.
        dense = ["y", "p", "q", "x"]
        lexical = ["x"]
        fused = dict(reciprocal_rank_fusion([dense, lexical], k=10))
        assert fused["x"] > fused["y"]

    def test_scores_descending(self):
        fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a"]])
        scores = [s for _, s in fused]
        assert scores == sorted(scores, reverse=True)

    def test_k_controls_weighting(self):
        # Larger k flattens the gap between rank 0 and rank 1.
        small_k = dict(reciprocal_rank_fusion([["a", "b"]], k=1))
        large_k = dict(reciprocal_rank_fusion([["a", "b"]], k=100))
        assert (small_k["a"] - small_k["b"]) > (large_k["a"] - large_k["b"])

    def test_empty_rankings(self):
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[], []]) == []
