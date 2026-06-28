"""Tests for the documentation health battery (src/tools/scripts/check_docs.py).

Two jobs:
1. **Green guard** — every check passes against the real repo, so `pytest` fails the
   moment a doc drifts from the code (the same guarantee the CI `verify` stage gives).
2. **Trustworthy checker** — each failure class (broken link, missing/ghost command,
   undocumented/ghost flag, missing/ghost setting, extra drift, dead citation) is
   injected into a temp tree and asserted to be caught, so the gate can't pass blind.

Fast + model-free (no pandoc, no embedding model). The script is loaded by path
because src/tools/ is dev tooling, not an installed package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "src" / "tools" / "scripts" / "check_docs.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_docs", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


check_docs = _load()


# ── 1. green guard: the real repo's docs are not broken AND up to date ──────────


@pytest.mark.parametrize("label,fn", check_docs._CHECKS, ids=[c[0] for c in check_docs._CHECKS])
def test_real_repo_passes(label, fn):
    errors = fn()
    assert errors == [], f"{label} found drift:\n" + "\n".join(errors)


# ── 2. trustworthy checker: every failure class is detected ─────────────────────


def _tmp_docs(monkeypatch, tmp_path: Path) -> Path:
    """Point the battery at an empty temp repo tree; return its docs/ dir."""
    (tmp_path / "docs" / "reference").mkdir(parents=True)
    (tmp_path / "README.md").write_text("# r\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# c\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "REPO", tmp_path)
    monkeypatch.setattr(check_docs, "DOCS", tmp_path / "docs")
    return tmp_path / "docs"


def test_detects_broken_link(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    (docs / "page.md").write_text("See [the missing one](nope.md).\n", encoding="utf-8")
    errors = check_docs.check_links()
    assert any("broken link" in e and "nope.md" in e for e in errors), errors


def test_link_in_code_block_is_ignored(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    (docs / "page.md").write_text("```\n![ex](attachments/x.png)\n```\n", encoding="utf-8")
    assert check_docs.check_links() == []


def test_detects_missing_command(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    (docs / "reference" / "cli.md").write_text("## index\n\nonly this one.\n", encoding="utf-8")
    errors = check_docs.check_cli_commands()
    assert any("search" in e and "not documented" in e for e in errors), errors


def test_detects_ghost_command(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    (docs / "reference" / "cli.md").write_text("## index\n\n## bogus-cmd\n", encoding="utf-8")
    errors = check_docs.check_cli_commands()
    assert any("bogus-cmd" in e and "not a real command" in e for e in errors), errors


def test_detects_undocumented_flag(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    # A search section that omits the real --hybrid flag.
    (docs / "reference" / "cli.md").write_text(
        "## search\n\n| Flag | Default | Description |\n|---|---|---|\n"
        "| `query` (arg) | - | the query |\n",
        encoding="utf-8",
    )
    errors = check_docs.check_cli_flags()
    assert any("search" in e and "not documented" in e for e in errors), errors


def test_detects_ghost_flag(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    (docs / "reference" / "cli.md").write_text(
        "## search\n\n| Flag | Default | Description |\n|---|---|---|\n"
        "| `--bogus-flag` | off | not real |\n",
        encoding="utf-8",
    )
    errors = check_docs.check_cli_flags()
    assert any("--bogus-flag" in e and "unknown flag" in e for e in errors), errors


def test_detects_missing_setting(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    (docs / "reference" / "configuration.md").write_text(
        "Only `PIPELINE_EMBEDDING_MODEL` here.\n", encoding="utf-8"
    )
    errors = check_docs.check_config()
    assert any("PIPELINE_RRF_K" in e and "not documented" in e for e in errors), errors


def test_detects_ghost_setting(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    (docs / "reference" / "configuration.md").write_text(
        "Mystery `PIPELINE_NOT_A_REAL_FIELD` here.\n", encoding="utf-8"
    )
    errors = check_docs.check_config()
    assert any("PIPELINE_NOT_A_REAL_FIELD" in e and "not a config field" in e for e in errors)


def test_detects_extra_drift(monkeypatch, tmp_path):
    # REPO stays the real repo so pyproject's real extras are read; only DOCS is faked.
    monkeypatch.setattr(check_docs, "DOCS", tmp_path / "docs")
    (tmp_path / "docs" / "reference").mkdir(parents=True)
    (tmp_path / "docs" / "reference" / "configuration.md").write_text(
        "## Install extras\n\n| Extra | Pulls in | Enables |\n|---|---|---|\n"
        "| `dev` | x | y |\n| `bogus-extra` | x | y |\n",
        encoding="utf-8",
    )
    errors = check_docs.check_extras()
    assert any("docs" in e and "not documented" in e for e in errors), errors
    assert any("bogus-extra" in e and "does not exist" in e for e in errors), errors


def test_detects_dead_citation(monkeypatch, tmp_path):
    docs = _tmp_docs(monkeypatch, tmp_path)
    (docs / "learn").mkdir()
    (docs / "learn" / "README.md").write_text(
        "Freshness — Source files cited\n\n| Page | Source files cited |\n|---|---|\n"
        "| x | `nope_module.py` |\n",
        encoding="utf-8",
    )
    errors = check_docs.check_citations()
    assert any("nope_module.py" in e and "not found" in e for e in errors), errors
