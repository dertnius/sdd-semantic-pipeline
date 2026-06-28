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
    def test_runs_without_explicit_vocab_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # scan now defaults its vocab output to outbox/vocab/, so a missing
        # --vocab is no longer an error (an empty input dir exits cleanly).
        monkeypatch.delenv("PIPELINE_ENTITY_VOCAB_PATH", raising=False)
        result = runner.invoke(app, ["scan", str(tmp_path)])
        assert result.exit_code == 0
        assert "No markdown files" in result.output


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


# A body with > 200 substantive chars so the content_density stub check stays quiet.
_PROSE = (
    "The authentication service validates incoming requests against the policy "
    "engine and issues short-lived tokens. It records every decision for audit "
    "and exposes health metrics to the platform monitoring stack continuously.\n"
)


class TestLint:
    """The lint command is pure text analysis — no pandoc or model needed."""

    def test_reports_issues_and_handles_unreadable(self, tmp_path: Path):
        (tmp_path / "dirty.md").write_text(
            "# Doc\n\n" + _PROSE + "\nThis {panel} leaked.\n", encoding="utf-8"
        )
        (tmp_path / "clean.md").write_text("# Clean\n\n" + _PROSE, encoding="utf-8")
        (tmp_path / "bad.md").write_bytes(b"\xff\xfe# undecodable\n")

        # The report now defaults under the outbox; pass an explicit path so the
        # assertion finds it (enforcement is off for the suite, see conftest).
        report_path = tmp_path / "quality-report.json"
        result = runner.invoke(app, ["lint", str(tmp_path), "-r", str(report_path)])
        # One unreadable file → non-zero exit even without --strict.
        assert result.exit_code == 1, result.output

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["total_files"] == 3
        assert report["clean_files"] == 1
        assert report["files_with_issues"] == 1
        assert report["failed"] == 1
        assert report["block_issues"] >= 1

        sources = [f["source"] for f in report["files"]]
        # files[] is issues-only: the clean file is counted, not listed.
        assert not any(s.endswith("clean.md") for s in sources)
        dirty = next(f for f in report["files"] if f["source"].endswith("dirty.md"))
        assert dirty["is_embeddable"] is False
        assert dirty["issues"]

    def test_clean_corpus_exits_zero(self, tmp_path: Path):
        (tmp_path / "ok.md").write_text("# Ok\n\n" + _PROSE, encoding="utf-8")
        report_path = tmp_path / "quality-report.json"
        result = runner.invoke(app, ["lint", str(tmp_path), "-r", str(report_path)])
        assert result.exit_code == 0, result.output
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["files_with_issues"] == 0
        assert report["files"] == []

    def test_strict_exits_nonzero_only_on_block(self, tmp_path: Path):
        # A near-empty stub is a block-severity finding, but not a read failure.
        (tmp_path / "stub.md").write_text("# Stub\n\nTODO\n", encoding="utf-8")
        assert runner.invoke(app, ["lint", str(tmp_path)]).exit_code == 0
        assert runner.invoke(app, ["lint", str(tmp_path), "--strict"]).exit_code == 1

    def test_empty_dir_exits_zero(self, tmp_path: Path):
        result = runner.invoke(app, ["lint", str(tmp_path)])
        assert result.exit_code == 0
        assert "No markdown files" in result.output


class TestCheckPwshRow:
    """The `check` command reports pwsh but never lets it change the exit code."""

    def test_reports_pwsh_row(self, monkeypatch: pytest.MonkeyPatch):
        from sdd_pipeline import cli
        from sdd_pipeline.shell import PwshInfo

        monkeypatch.setattr(
            cli,
            "resolve_pwsh",
            lambda config=None, **kw: PwshInfo("/usr/bin/pwsh", "7.4.1", 7, "which"),
        )
        result = runner.invoke(app, ["check"])
        assert "pwsh" in result.output
        assert "7.4.1" in result.output

    def test_missing_pwsh_does_not_gate(self, monkeypatch: pytest.MonkeyPatch):
        from sdd_pipeline import cli
        from sdd_pipeline.shell import PwshInfo

        # The exit code must be identical whether pwsh is present or absent — the
        # pwsh row is informational. (Equal regardless of whether pandoc is on PATH.)
        monkeypatch.setattr(
            cli,
            "resolve_pwsh",
            lambda config=None, **kw: PwshInfo("/usr/bin/pwsh", "7.4.1", 7, "which"),
        )
        rc_present = runner.invoke(app, ["check"]).exit_code
        monkeypatch.setattr(cli, "resolve_pwsh", lambda config=None, **kw: None)
        rc_absent = runner.invoke(app, ["check"]).exit_code
        assert rc_present == rc_absent


class TestPwshPathCommand:
    def test_prints_path_for_usable_v7(self, monkeypatch: pytest.MonkeyPatch):
        from sdd_pipeline import cli
        from sdd_pipeline.shell import PwshInfo

        monkeypatch.setattr(
            cli,
            "resolve_pwsh",
            lambda config=None, **kw: PwshInfo("/usr/bin/pwsh", "7.4.1", 7, "which"),
        )
        result = runner.invoke(app, ["pwsh-path"])
        assert result.exit_code == 0
        assert "/usr/bin/pwsh" in result.output

    def test_exit_one_when_none(self, monkeypatch: pytest.MonkeyPatch):
        from sdd_pipeline import cli

        monkeypatch.setattr(cli, "resolve_pwsh", lambda config=None, **kw: None)
        result = runner.invoke(app, ["pwsh-path"])
        assert result.exit_code == 1

    def test_default_floor_is_seven_allow_any_is_one(self, monkeypatch: pytest.MonkeyPatch):
        from sdd_pipeline import cli
        from sdd_pipeline.shell import PwshInfo

        calls: list[int] = []

        def fake(config=None, *, min_major=0, **kw):
            calls.append(min_major)
            info = PwshInfo("/usr/bin/powershell", "5.1.0", 5, "windows-powershell")
            return info if info.major >= min_major else None

        monkeypatch.setattr(cli, "resolve_pwsh", fake)
        # Default demands v7 → a 5.1-only box fails.
        assert runner.invoke(app, ["pwsh-path"]).exit_code == 1
        # --allow-any drops the floor to 1 → the 5.1 path is printed.
        any_result = runner.invoke(app, ["pwsh-path", "--allow-any"])
        assert any_result.exit_code == 0
        assert "/usr/bin/powershell" in any_result.output
        assert calls == [7, 1]
