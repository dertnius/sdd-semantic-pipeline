"""
Tests for sdd_pipeline.ast_parser.

All tests that invoke pandoc are guarded by ``requires_pandoc``; they are
skipped automatically when pandoc is not on PATH (e.g. in a bare CI image).
Run them with:
    pytest -m "not slow" -v      # skip integration
    pytest -m "slow" -v          # integration only
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sdd_pipeline.ast_parser import generate_ast, generate_ast_batch, pandoc_version

# ── Skip guard ────────────────────────────────────────────────────────────────


def _pandoc_available() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


requires_pandoc = pytest.mark.skipif(
    not _pandoc_available(),
    reason="pandoc binary not found on PATH",
)


# ── pandoc_version ────────────────────────────────────────────────────────────


class TestPandocVersion:
    @requires_pandoc
    def test_returns_non_empty_string(self):
        ver = pandoc_version()
        assert isinstance(ver, str)
        assert "pandoc" in ver.lower()

    def test_raises_when_not_found(self, monkeypatch):
        """Simulate missing pandoc by patching PATH."""

        monkeypatch.setenv("PATH", "")
        with pytest.raises((FileNotFoundError, OSError, subprocess.SubprocessError)):
            pandoc_version()


# ── generate_ast ──────────────────────────────────────────────────────────────


class TestGenerateAst:
    @requires_pandoc
    @pytest.mark.slow
    def test_returns_dict_with_required_keys(self, sample_md_file: Path):
        ast = generate_ast(sample_md_file)
        assert isinstance(ast, dict)
        assert "pandoc-api-version" in ast
        assert "meta" in ast
        assert "blocks" in ast

    @requires_pandoc
    @pytest.mark.slow
    def test_title_in_meta(self, sample_md_file: Path):
        ast = generate_ast(sample_md_file)
        assert "title" in ast["meta"]

    @requires_pandoc
    @pytest.mark.slow
    def test_blocks_non_empty(self, sample_md_file: Path):
        ast = generate_ast(sample_md_file)
        assert len(ast["blocks"]) > 0

    @requires_pandoc
    @pytest.mark.slow
    def test_header_blocks_present(self, sample_md_file: Path):
        ast = generate_ast(sample_md_file)
        types = {b["t"] for b in ast["blocks"]}
        assert "Header" in types

    @requires_pandoc
    @pytest.mark.slow
    def test_code_block_present(self, sample_md_file: Path):
        ast = generate_ast(sample_md_file)
        types = {b["t"] for b in ast["blocks"]}
        assert "CodeBlock" in types

    @requires_pandoc
    @pytest.mark.slow
    def test_pandoc_api_version_is_list(self, sample_md_file: Path):
        ast = generate_ast(sample_md_file)
        version = ast["pandoc-api-version"]
        assert isinstance(version, list)
        assert all(isinstance(v, int) for v in version)

    def test_raises_on_missing_file(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.md"
        with pytest.raises((subprocess.CalledProcessError, FileNotFoundError)):
            generate_ast(missing)

    @requires_pandoc
    @pytest.mark.slow
    def test_custom_from_format(self, tmp_path: Path):
        """Markdown (non-GFM) should also work."""
        md = tmp_path / "plain.md"
        md.write_text("# Hello\n\nWorld.\n", encoding="utf-8")
        ast = generate_ast(md, from_format="markdown")
        assert "Header" in {b["t"] for b in ast["blocks"]}


# ── generate_ast_batch ────────────────────────────────────────────────────────


class TestGenerateAstBatch:
    @requires_pandoc
    @pytest.mark.slow
    def test_processes_all_files(self, tmp_path: Path):
        files = []
        for i in range(3):
            f = tmp_path / f"doc{i}.md"
            f.write_text(f"# Doc {i}\n\nContent {i}.\n", encoding="utf-8")
            files.append(f)

        results = generate_ast_batch(files)
        assert len(results) == 3
        for path in files:
            assert path in results
            assert "blocks" in results[path]

    @requires_pandoc
    @pytest.mark.slow
    def test_writes_json_files_when_output_dir_given(self, tmp_path: Path):
        md = tmp_path / "doc.md"
        md.write_text("# Title\n\nParagraph.\n", encoding="utf-8")
        out_dir = tmp_path / "ast_out"

        generate_ast_batch([md], output_dir=out_dir)

        written = out_dir / "doc.ast.json"
        assert written.exists()
        loaded = json.loads(written.read_text(encoding="utf-8"))
        assert "blocks" in loaded

    @requires_pandoc
    @pytest.mark.slow
    def test_empty_list_returns_empty_dict(self):
        result = generate_ast_batch([])
        assert result == {}
