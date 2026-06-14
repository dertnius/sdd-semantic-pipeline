"""CLI-level tests for the inbox/outbox workspace guard.

These opt back IN to enforcement (the conftest autouse fixture turns it off for
the rest of the suite) by setting PIPELINE_ENFORCE_WORKSPACE=true plus per-test
inbox/outbox roots under tmp_path. They stay fast by exercising commands whose
guard fires before any pandoc/model work: ``index --dry-run`` (rejected before
processing) and ``lint`` (pure text, no pandoc).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sdd_pipeline.cli import app

runner = CliRunner()

_PROSE = (
    "The authentication service validates incoming requests against the policy "
    "engine and issues short-lived tokens. It records every decision for audit "
    "and exposes health metrics to the platform monitoring stack continuously.\n"
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Enforced inbox/outbox roots under tmp_path. Returns (inbox, outbox)."""
    inbox = tmp_path / "inbox"
    outbox = tmp_path / "outbox"
    inbox.mkdir()
    monkeypatch.setenv("PIPELINE_ENFORCE_WORKSPACE", "true")
    monkeypatch.setenv("PIPELINE_INBOX_DIR", str(inbox))
    monkeypatch.setenv("PIPELINE_OUTBOX_DIR", str(outbox))
    return inbox, outbox


class TestInputGuard:
    def test_index_rejects_out_of_zone_input(self, workspace: tuple[Path, Path], tmp_path: Path):
        outside = tmp_path / "outside"
        outside.mkdir()
        # --dry-run loads no model; the guard fires before any processing.
        result = runner.invoke(app, ["index", str(outside), "--dry-run"])
        assert result.exit_code == 2, result.output
        assert "inbox" in result.output.lower()

    def test_lint_rejects_out_of_zone_input(self, workspace: tuple[Path, Path], tmp_path: Path):
        outside = tmp_path / "outside"
        outside.mkdir()
        result = runner.invoke(app, ["lint", str(outside)])
        assert result.exit_code == 2, result.output
        assert "inbox" in result.output.lower()

    def test_missing_inbox_is_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PIPELINE_ENFORCE_WORKSPACE", "true")
        monkeypatch.setenv("PIPELINE_INBOX_DIR", str(tmp_path / "nope"))
        monkeypatch.setenv("PIPELINE_OUTBOX_DIR", str(tmp_path / "outbox"))
        result = runner.invoke(app, ["lint"])
        assert result.exit_code == 2, result.output
        assert "does not exist" in result.output.lower()


class TestOutputGuard:
    def test_lint_rejects_out_of_zone_report(self, workspace: tuple[Path, Path], tmp_path: Path):
        inbox, _ = workspace
        (inbox / "ok.md").write_text("# Ok\n\n" + _PROSE, encoding="utf-8")
        result = runner.invoke(app, ["lint", "-r", str(tmp_path / "outside.json")])
        assert result.exit_code == 2, result.output
        assert "outbox" in result.output.lower()


class TestDefaultsLandInZones:
    def test_lint_default_report_under_outbox(self, workspace: tuple[Path, Path]):
        inbox, outbox = workspace
        (inbox / "ok.md").write_text("# Ok\n\n" + _PROSE, encoding="utf-8")
        # No --report and no input arg: input defaults to the inbox, report to
        # outbox/reports/quality-report.json.
        result = runner.invoke(app, ["lint"])
        assert result.exit_code == 0, result.output
        assert (outbox / "reports" / "quality-report.json").exists()


class TestBypass:
    def test_enforce_false_allows_out_of_zone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PIPELINE_ENFORCE_WORKSPACE", "false")
        monkeypatch.setenv("PIPELINE_INBOX_DIR", str(tmp_path / "inbox"))
        monkeypatch.setenv("PIPELINE_OUTBOX_DIR", str(tmp_path / "outbox"))
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "ok.md").write_text("# Ok\n\n" + _PROSE, encoding="utf-8")
        result = runner.invoke(app, ["lint", str(outside), "-r", str(outside / "report.json")])
        assert result.exit_code == 0, result.output
        assert (outside / "report.json").exists()
