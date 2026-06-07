"""Tests for sdd_pipeline.embeddings (Azure provider, factory, identity).

The Azure ``openai`` SDK is never imported: a fake client is injected directly,
and the ImportError path is forced via sys.modules.
"""

from __future__ import annotations

import sys

import pytest

from sdd_pipeline.config import PipelineConfig
from sdd_pipeline.embeddings import (
    AzureOpenAIEmbedder,
    EmbeddingModel,
    embedder_identity,
    make_embedder,
)

# ── Fake Azure client ─────────────────────────────────────────────────────────


class _Row:
    def __init__(self, index: int, embedding: list[float]):
        self.index = index
        self.embedding = embedding


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddings:
    def __init__(self, recorder: list[dict], dim: int = 4, shuffle: bool = False):
        self.recorder = recorder
        self.dim = dim
        self.shuffle = shuffle

    def create(self, model: str, input: list[str]):
        self.recorder.append({"model": model, "input": list(input)})
        # Deterministic embedding keyed on the text length so order is checkable.
        rows = [_Row(i, [float(len(t))] * self.dim) for i, t in enumerate(input)]
        if self.shuffle:
            rows = list(reversed(rows))
        return _Resp(rows)


class _FakeClient:
    def __init__(self, recorder: list[dict], dim: int = 4, shuffle: bool = False):
        self.embeddings = _FakeEmbeddings(recorder, dim, shuffle)


def _embedder(recorder: list[dict], batch_size: int = 32, dim: int = 4, shuffle: bool = False):
    emb = AzureOpenAIEmbedder(
        endpoint="https://x.openai.azure.com/",
        api_key="secret",
        deployment="dep",
        batch_size=batch_size,
    )
    emb._client = _FakeClient(recorder, dim, shuffle)
    return emb


# ── AzureOpenAIEmbedder ───────────────────────────────────────────────────────


class TestAzureOpenAIEmbedder:
    def test_batches_by_batch_size(self):
        rec: list[dict] = []
        emb = _embedder(rec, batch_size=2)
        emb.embed(["a", "b", "c", "d", "e"])
        assert [len(call["input"]) for call in rec] == [2, 2, 1]

    def test_preserves_input_order_despite_shuffled_response(self):
        rec: list[dict] = []
        emb = _embedder(rec, batch_size=10, shuffle=True)
        out = emb.embed(["a", "bb", "ccc"])  # lengths 1, 2, 3
        assert out == [[1.0] * 4, [2.0] * 4, [3.0] * 4]

    def test_empty_input_skips_client(self):
        rec: list[dict] = []
        emb = _embedder(rec)
        assert emb.embed([]) == []
        assert rec == []

    def test_missing_config_raises(self):
        with pytest.raises(ValueError):
            AzureOpenAIEmbedder(endpoint="", api_key="k", deployment="d")
        with pytest.raises(ValueError):
            AzureOpenAIEmbedder(endpoint="e", api_key="", deployment="d")
        with pytest.raises(ValueError):
            AzureOpenAIEmbedder(endpoint="e", api_key="k", deployment="")

    def test_import_error_gives_install_hint(self, monkeypatch):
        # Force `from openai import AzureOpenAI` to fail regardless of install state.
        monkeypatch.setitem(sys.modules, "openai", None)
        emb = AzureOpenAIEmbedder(endpoint="e", api_key="k", deployment="d")
        with pytest.raises(ImportError, match=r"sdd-pipeline\[azure\]"):
            emb.embed(["x"])

    def test_embed_chunks_uses_embed_text(self, sample_chunks):
        rec: list[dict] = []
        emb = _embedder(rec)
        emb.embed_chunks(sample_chunks)
        assert rec[0]["input"] == [c.to_embed_text() for c in sample_chunks]

    def test_embed_query_returns_single_vector(self):
        rec: list[dict] = []
        emb = _embedder(rec, dim=3)
        vec = emb.embed_query("hello")
        assert vec == [5.0, 5.0, 5.0]  # len("hello") == 5

    def test_dimension_cached_after_embed(self):
        rec: list[dict] = []
        emb = _embedder(rec, dim=7)
        emb.embed(["abc"])
        assert emb.dimension == 7
        assert len(rec) == 1  # no extra probe call

    def test_dimension_probes_when_unknown(self):
        rec: list[dict] = []
        emb = _embedder(rec, dim=5)
        assert emb.dimension == 5
        assert len(rec) == 1  # one probe embed


# ── Factory & identity ────────────────────────────────────────────────────────


class TestMakeEmbedder:
    def test_local_returns_embedding_model(self):
        cfg = PipelineConfig(embedding_provider="local", embedding_model="all-MiniLM-L6-v2")
        assert isinstance(make_embedder(cfg), EmbeddingModel)

    def test_azure_returns_azure_embedder(self):
        cfg = PipelineConfig(
            embedding_provider="azure",
            azure_openai_endpoint="https://x.openai.azure.com/",
            azure_openai_api_key="k",
            azure_openai_deployment="dep",
        )
        assert isinstance(make_embedder(cfg), AzureOpenAIEmbedder)

    def test_unknown_provider_raises(self):
        cfg = PipelineConfig(embedding_provider="banana")
        with pytest.raises(ValueError, match="Unknown embedding_provider"):
            make_embedder(cfg)


class TestEmbedderIdentity:
    def test_local_identity(self):
        cfg = PipelineConfig(embedding_provider="local", embedding_model="m1")
        assert embedder_identity(cfg) == ("local", "m1")

    def test_azure_identity_uses_deployment(self):
        cfg = PipelineConfig(embedding_provider="azure", azure_openai_deployment="dep-x")
        assert embedder_identity(cfg) == ("azure", "dep-x")
