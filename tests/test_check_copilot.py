"""Tests for the Copilot integration health battery (src/tools/scripts/check_copilot.py).

Two jobs (same shape as tests/test_check_docs.py):
1. **Green guard** — every check passes against the real repo, so `pytest` fails the
   moment a Copilot asset drifts (missing frontmatter, a dead CLI/MCP-tool reference,
   a broken link) — the same guarantee the CI copilot-health gate gives.
2. **Trustworthy checker** — each failure class is injected into a temp `.github`
   tree and asserted to be caught, so the gate can't pass blind.

Fast + model-free (no pandoc, no embedding model, no `mcp` SDK). The script is loaded
by path because src/tools/ is dev tooling, not an installed package.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "src" / "tools" / "scripts" / "check_copilot.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_copilot", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cc = _load()


# ── 1. green guard: the real repo's Copilot assets are valid and wired ──────────


@pytest.mark.parametrize("label,fn", cc._CHECKS, ids=[c[0] for c in cc._CHECKS])
def test_real_repo_passes(label, fn):
    errors = fn()
    assert errors == [], f"{label} found drift:\n" + "\n".join(errors)


# ── 2. trustworthy checker: every failure class is detected ─────────────────────


def _good_mcp_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "sdd-semantic": {
                        "type": "stdio",
                        "command": "python",
                        "args": ["-m", "sdd_pipeline.cli", "mcp", "--lexical"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _tmp_gh(monkeypatch, tmp_path: Path) -> Path:
    """Point the battery at an empty temp .github tree (+ a valid mcp.json so the
    MCP-wiring check is satisfied unless the test breaks it on purpose)."""
    gh = tmp_path / ".github"
    for sub in ("prompts", "agents", "instructions"):
        (gh / sub).mkdir(parents=True)
    monkeypatch.setattr(cc, "REPO", tmp_path)
    monkeypatch.setattr(cc, "GH", gh)
    monkeypatch.setattr(cc, "PROMPTS", gh / "prompts")
    monkeypatch.setattr(cc, "AGENTS", gh / "agents")
    monkeypatch.setattr(cc, "INSTRUCTIONS", gh / "instructions")
    monkeypatch.setattr(cc, "COPILOT_INSTRUCTIONS", gh / "copilot-instructions.md")
    monkeypatch.setattr(cc, "MCP_JSON", tmp_path / ".vscode" / "mcp.json")
    _good_mcp_json(tmp_path / ".vscode" / "mcp.json")
    return gh


def test_detects_missing_description(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "prompts" / "x.prompt.md").write_text("---\nmode: agent\n---\n# x\n", encoding="utf-8")
    errors = cc.check_frontmatter()
    assert any("description" in e and "x.prompt.md" in e for e in errors), errors


def test_detects_missing_applyto(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "instructions" / "x.instructions.md").write_text(
        "---\ndescription: no applyTo here\n---\n# x\n", encoding="utf-8"
    )
    errors = cc.check_frontmatter()
    assert any("applyTo" in e and "x.instructions.md" in e for e in errors), errors


def test_detects_unknown_cli_command(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "prompts" / "x.prompt.md").write_text(
        "---\ndescription: d\n---\nRun `sdd-pipeline frobnicate` now.\n", encoding="utf-8"
    )
    errors = cc.check_cli_refs()
    assert any("frobnicate" in e and "unknown CLI command" in e for e in errors), errors


def test_real_cli_command_passes(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "prompts" / "x.prompt.md").write_text(
        "---\ndescription: d\n---\nRun `sdd-pipeline convert-docx` then `sdd-pipeline index`.\n",
        encoding="utf-8",
    )
    assert cc.check_cli_refs() == []


def test_detects_unknown_mcp_tool(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "agents" / "x.agent.md").write_text(
        "---\nname: X\ndescription: d\n---\nCall `frobnicate_things(topic)`.\n", encoding="utf-8"
    )
    errors = cc.check_mcp()
    assert any("frobnicate_things" in e and "unknown MCP tool" in e for e in errors), errors


def test_real_mcp_tool_passes(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "agents" / "x.agent.md").write_text(
        "---\nname: X\ndescription: d\n---\nCall `find_decision_context(topic)`.\n",
        encoding="utf-8",
    )
    # Only the MCP-tool reference is exercised here; wiring is satisfied by _good_mcp_json.
    assert cc.check_mcp() == []


def test_mcp_wiring_detects_missing_server(monkeypatch, tmp_path):
    _tmp_gh(monkeypatch, tmp_path)
    (tmp_path / ".vscode" / "mcp.json").write_text(
        json.dumps({"servers": {"other": {"args": []}}}), encoding="utf-8"
    )
    errors = cc.check_mcp()
    assert any("sdd-semantic" in e and "missing" in e for e in errors), errors


def test_detects_broken_link(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "notes.md").write_text("See [the missing one](nope.md).\n", encoding="utf-8")
    errors = cc.check_links()
    assert any("broken link" in e and "nope.md" in e for e in errors), errors


def test_link_in_code_block_is_ignored(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "notes.md").write_text("```\n[ex](nope.md)\n```\n", encoding="utf-8")
    assert cc.check_links() == []


def test_detects_unbalanced_fence(monkeypatch, tmp_path):
    gh = _tmp_gh(monkeypatch, tmp_path)
    (gh / "notes.md").write_text("# x\n\n```powershell\nsome code\n", encoding="utf-8")
    errors = cc.check_wellformed()
    assert any("unbalanced code fence" in e and "notes.md" in e for e in errors), errors
