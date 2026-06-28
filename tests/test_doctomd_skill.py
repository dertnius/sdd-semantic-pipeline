"""Contract test for the docToMd skill ↔ CLI wiring.

The skill (``.claude/skills/docToMd/SKILL.md``) is a thin wrapper that drives the
``sdd-pipeline convert-docx`` command. A skill can break *silently*: rename the
command, fumble the frontmatter, or document an invocation that no longer
resolves, and nothing fails until someone runs it by hand. These checks guard the
contract — the skill file stays valid and the command it points at remains a
real, resolvable CLI command. Fast + model-free (no pandoc, no embedding model);
it tests the *wiring*, not whether the model chooses to trigger the skill (that is
a description-quality eval, run via the skill-creator tooling).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from sdd_pipeline.cli import app

runner = CliRunner()

_SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "docToMd" / "SKILL.md"


def _frontmatter(text: str) -> dict:
    """Parse the leading ``---`` YAML block of a SKILL.md."""
    return yaml.safe_load(text.split("---")[1])


def test_skill_file_exists():
    assert _SKILL.is_file(), f"docToMd skill missing at {_SKILL}"


def test_skill_frontmatter_is_valid():
    fm = _frontmatter(_SKILL.read_text(encoding="utf-8"))
    # name drives `/docToMd`; description is what the model matches on to trigger.
    assert fm.get("name") == "docToMd"
    assert (fm.get("description") or "").strip()


def test_skill_documents_the_real_command():
    body = _SKILL.read_text(encoding="utf-8")
    assert "convert-docx" in body, "skill must document the command it drives"


def test_convert_docx_command_resolves_and_parses():
    # The exact command the skill documents must be a registered, parseable
    # CLI command — this is what caught the un-importable invocation.
    result = runner.invoke(app, ["convert-docx", "--help"])
    assert result.exit_code == 0, result.output
    assert "Convert all Word .docx files" in result.output
