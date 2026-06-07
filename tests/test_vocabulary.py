"""Tests for sdd_pipeline.vocabulary."""

from __future__ import annotations

from pathlib import Path

from sdd_pipeline.vocabulary import load_vocabulary, save_vocabulary


def test_round_trip_sorted_and_deduped(tmp_path: Path):
    path = tmp_path / "vocab.json"
    save_vocabulary(path, ["Kafka", "AuthService", "Kafka", "  ", "CQRS"])
    assert load_vocabulary(path) == ["AuthService", "CQRS", "Kafka"]


def test_load_missing_path_returns_empty(tmp_path: Path):
    assert load_vocabulary(tmp_path / "does_not_exist.json") == []


def test_save_creates_parent_dirs(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "vocab.json"
    save_vocabulary(path, ["Term"])
    assert path.exists()
    assert load_vocabulary(path) == ["Term"]


def test_accepts_str_path(tmp_path: Path):
    path = str(tmp_path / "vocab.json")
    save_vocabulary(path, ["A", "B"])
    assert load_vocabulary(path) == ["A", "B"]
