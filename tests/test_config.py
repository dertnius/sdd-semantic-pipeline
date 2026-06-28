"""Tests for sdd_pipeline.config.PipelineConfig.

Only one ``PipelineConfig`` branch (pydantic-settings v2 or the v1 fallback) is
importable at runtime, so these exercise whichever is active.
"""

from __future__ import annotations

import pytest

from sdd_pipeline.config import PipelineConfig


class TestWorkspaceConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch):
        # conftest's autouse fixture sets these env vars; clear them to see the
        # shipped defaults.
        for var in ("PIPELINE_INBOX_DIR", "PIPELINE_OUTBOX_DIR", "PIPELINE_ENFORCE_WORKSPACE"):
            monkeypatch.delenv(var, raising=False)
        cfg = PipelineConfig()
        assert cfg.inbox_dir == "./inbox"
        assert cfg.outbox_dir == "./outbox"
        assert cfg.enforce_workspace is True
        # The vector index default now lives under the outbox.
        assert cfg.chroma_persist_dir == "./outbox/index"

    def test_enforce_workspace_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PIPELINE_ENFORCE_WORKSPACE", "false")
        assert PipelineConfig().enforce_workspace is False

    def test_roots_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PIPELINE_INBOX_DIR", "/data/inbox")
        monkeypatch.setenv("PIPELINE_OUTBOX_DIR", "/data/outbox")
        cfg = PipelineConfig()
        assert cfg.inbox_dir == "/data/inbox"
        assert cfg.outbox_dir == "/data/outbox"


class TestEntityTerms:
    def test_defaults_empty(self):
        assert PipelineConfig().entity_terms == []

    def test_accepts_explicit_list(self):
        cfg = PipelineConfig(entity_terms=["KPO", "triggerer", "XCom"])
        assert cfg.entity_terms == ["KPO", "triggerer", "XCom"]

    def test_env_json_array_parsed(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_ENTITY_TERMS", '["KPO", "XCom"]')
        assert PipelineConfig().entity_terms == ["KPO", "XCom"]


class TestEmbedAndMergeConfig:
    def test_embed_char_budget_default(self):
        assert PipelineConfig().embed_char_budget == 1800

    def test_embed_char_budget_override(self):
        assert PipelineConfig(embed_char_budget=900).embed_char_budget == 900

    def test_merge_definitions_default_false(self):
        assert PipelineConfig().chunk_merge_definitions is False

    def test_merge_definitions_override(self):
        assert PipelineConfig(chunk_merge_definitions=True).chunk_merge_definitions is True


class TestVectorStoreConfig:
    def test_backend_default_is_memory(self):
        assert PipelineConfig().vector_store_backend == "memory"

    def test_backend_override(self):
        assert PipelineConfig(vector_store_backend="chroma").vector_store_backend == "chroma"


class TestPwshPathConfig:
    def test_default_empty(self):
        assert PipelineConfig().pwsh_path == ""

    def test_kwarg_override(self):
        assert PipelineConfig(pwsh_path="/opt/pwsh/pwsh").pwsh_path == "/opt/pwsh/pwsh"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PIPELINE_PWSH_PATH", "/usr/local/bin/pwsh")
        assert PipelineConfig().pwsh_path == "/usr/local/bin/pwsh"
