"""Tests for the CLI ``export`` command.

Format validation is fast (runs before any file processing); the end-to-end
export tests need pandoc and are marked ``slow`` (no embedding model is loaded).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sdd_pipeline.cli import app

runner = CliRunner()


def _pandoc_ok() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


class TestExportValidation:
    def test_rejects_unknown_format(self, tmp_path: Path):
        # Validation precedes processing → no pandoc needed.
        result = runner.invoke(
            app, ["export", str(tmp_path), "-o", str(tmp_path / "out"), "--format", "yaml"]
        )
        assert result.exit_code == 2
        assert "Invalid --format" in result.output

    def test_merge_definitions_flag_accepted(self, tmp_path: Path):
        # Empty input dir → clean Exit(0); proves the flag parses (no pandoc).
        result = runner.invoke(
            app, ["export", str(tmp_path), "-o", str(tmp_path / "out"), "--merge-definitions"]
        )
        assert result.exit_code == 0


class TestScanValidation:
    def test_requires_a_vocab_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Neither --vocab nor PIPELINE_ENTITY_VOCAB_PATH → error before any parsing.
        monkeypatch.delenv("PIPELINE_ENTITY_VOCAB_PATH", raising=False)
        result = runner.invoke(app, ["scan", str(tmp_path)])
        assert result.exit_code == 2
        assert "vocabulary path" in result.output.lower()


class TestConvertFrontmatter:
    """Provenance frontmatter emission is pure string work — no pandoc needed."""

    def test_postprocess_emits_provenance_keys(self):
        from sdd_pipeline.html_to_gitlab_md import postprocess

        md = postprocess(
            md="# Head\n\nbody\n",
            title="AIP-107",
            author="",
            source_path=Path("aip-107.html"),
            add_frontmatter=True,
            add_toc=False,
            space="DEMO",
            source_url="https://example/aip-107",
            labels=["airflow", "aip"],
        )
        # Keys must match what structural._extract_metadata reads back.
        assert 'space: "DEMO"' in md
        assert 'url: "https://example/aip-107"' in md
        assert "labels:" in md
        assert '  - "airflow"' in md
        assert '  - "aip"' in md

    def test_postprocess_omits_absent_provenance(self):
        from sdd_pipeline.html_to_gitlab_md import postprocess

        md = postprocess(
            md="# Head\n\nbody\n",
            title="T",
            author="",
            source_path=Path("p.html"),
            add_frontmatter=True,
            add_toc=False,
        )
        assert "space:" not in md
        assert "\nurl:" not in md
        assert "labels:" not in md


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
class TestExportEndToEnd:
    def test_export_json(self, tmp_path: Path, sample_md_file: Path):
        out = tmp_path / "artifacts"
        result = runner.invoke(
            app, ["export", str(sample_md_file.parent), "-o", str(out), "--format", "json"]
        )
        assert result.exit_code == 0, result.output

        chunk_file = out / "auth-service.chunks.json"
        assert chunk_file.exists()
        chunks = json.loads(chunk_file.read_text(encoding="utf-8"))
        assert isinstance(chunks, list) and len(chunks) > 0
        for c in chunks:
            assert "embed_text" in c and "chunk_id" in c

        # Provenance from the sample markdown's frontmatter flows onto chunks.
        first = chunks[0]
        assert first["title"] == "Auth Service Design"
        assert first["space"] == "PLATFORM"
        assert first["source_url"].startswith("https://confluence.example.com")

        report = json.loads((out / "export-report.json").read_text(encoding="utf-8"))
        assert report["total_files"] == 1
        assert report["succeeded"] == 1
        assert report["format"] == "json"

    def test_export_merge_definitions_colocates_prose_and_code(
        self, tmp_path: Path, sample_md_file: Path
    ):
        out = tmp_path / "artifacts"
        result = runner.invoke(
            app,
            [
                "export",
                str(sample_md_file.parent),
                "-o",
                str(out),
                "--merge-definitions",
            ],
        )
        assert result.exit_code == 0, result.output
        chunks = json.loads((out / "auth-service.chunks.json").read_text(encoding="utf-8"))
        # The API section's prose and its fenced JSON should land in one chunk.
        assert any("```json" in c["content"] and len(c["content"]) > 40 for c in chunks)

    def test_export_jsonl(self, tmp_path: Path, sample_md_file: Path):
        out = tmp_path / "artifacts"
        result = runner.invoke(
            app, ["export", str(sample_md_file.parent), "-o", str(out), "--format", "jsonl"]
        )
        assert result.exit_code == 0, result.output

        lines = (out / "auth-service.chunks.jsonl").read_text(encoding="utf-8").splitlines()
        assert lines
        for line in lines:
            assert isinstance(json.loads(line), dict)


@pytest.mark.slow
@pytest.mark.skipif(not _pandoc_ok(), reason="pandoc not found")
class TestScanAndExportScanEndToEnd:
    def test_scan_writes_vocabulary(self, tmp_path: Path, sample_md_file: Path):
        vocab = tmp_path / "vocab.json"
        result = runner.invoke(
            app, ["scan", str(sample_md_file.parent), "--vocab", str(vocab), "-v"]
        )
        assert result.exit_code == 0, result.output
        assert vocab.exists()
        terms = json.loads(vocab.read_text(encoding="utf-8"))
        assert isinstance(terms, list) and len(terms) > 0

    def test_export_honors_vocab_path(
        self, tmp_path: Path, sample_md_file: Path, monkeypatch: pytest.MonkeyPatch
    ):
        vocab = tmp_path / "vocab.json"
        monkeypatch.setenv("PIPELINE_ENTITY_VOCAB_PATH", str(vocab))
        out = tmp_path / "artifacts"
        result = runner.invoke(app, ["export", str(sample_md_file.parent), "-o", str(out)])
        assert result.exit_code == 0, result.output
        # The scan ran model-free and persisted the vocabulary.
        assert vocab.exists()
        report = json.loads((out / "export-report.json").read_text(encoding="utf-8"))
        assert report["entity_vocab_path"] == str(vocab)
        assert report["vocab_terms"] >= 1
