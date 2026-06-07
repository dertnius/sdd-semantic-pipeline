"""Tests for sdd_pipeline.config.PipelineConfig.

Only one ``PipelineConfig`` branch (pydantic-settings v2 or the v1 fallback) is
importable at runtime, so these exercise whichever is active.
"""

from __future__ import annotations

from sdd_pipeline.config import PipelineConfig


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
