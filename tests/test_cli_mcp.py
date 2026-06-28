"""
CLI-level tests for the `sdd-pipeline mcp` command.

These never start the real stdio loop (it blocks): `--help` is handled by Click,
the workspace test exits before `run_server`, and the run-path test monkeypatches
`run_server` to a no-op so we can assert the resolved config without serving.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytest.importorskip("mcp")

from sdd_pipeline.cli import app

runner = CliRunner()

# Typer/Rich styles help with ANSI; bold (`\x1b[1m`) splits a flag into `-`+`-name`,
# which NO_COLOR does not strip. Remove escape codes so flag-name substring checks are
# rendering-independent across platforms.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def test_mcp_help_lists_options():
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    plain = _ANSI_RE.sub("", result.output)
    for opt in ("--index", "--model", "--provider", "--backend", "--hybrid"):
        assert opt in plain


def test_mcp_out_of_zone_index_exits_2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Re-enable the workspace guard (the autouse conftest fixture turns it off).
    monkeypatch.setenv("PIPELINE_ENFORCE_WORKSPACE", "true")
    # Safety net: if the guard unexpectedly passes, run_server must not block the test.
    import sdd_pipeline.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "run_server", lambda config: None)

    outside = tmp_path / "outside" / "index"  # not under the temp outbox
    result = runner.invoke(app, ["mcp", "--index", str(outside)])
    assert result.exit_code == 2


def test_mcp_invokes_run_server_with_resolved_index(monkeypatch: pytest.MonkeyPatch):
    import sdd_pipeline.mcp_server as mcp_server

    captured: dict = {}
    monkeypatch.setattr(mcp_server, "run_server", lambda config: captured.update(config=config))

    result = runner.invoke(app, ["mcp"])
    assert result.exit_code == 0, result.output
    assert "config" in captured
    assert captured["config"].chroma_persist_dir  # the index path was resolved
