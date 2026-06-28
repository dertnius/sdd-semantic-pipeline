"""Contract test for the docs-sync skill ↔ doc-health battery wiring.

The skill (``.claude/skills/docs-sync/SKILL.md``) is a thin helper that drives
``src/tools/scripts/check_docs.py`` and the CLI ``help``. It is a **tracked** portable
Agent Skill (``.claude/skills/`` is the one carved-out exception to the gitignored
``.claude/`` — read by both Claude Code and Copilot), so this contract now runs in CI
too. The ``skipif`` below stays only as a guard for a checkout that lacks the subtree;
normally the checks guard the contract: valid frontmatter, and the tools the skill
points at still exist. The broader enforced guarantee remains ``check_docs.py`` + the
CI verify stage (covered by ``tests/test_check_docs.py``). Fast + model-free.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SKILL = _ROOT / ".claude" / "skills" / "docs-sync" / "SKILL.md"

pytestmark = pytest.mark.skipif(
    not _SKILL.is_file(), reason="docs-sync skill is a local helper (.claude/ is gitignored)"
)


def _frontmatter(text: str) -> dict:
    return yaml.safe_load(text.split("---")[1])


def test_skill_frontmatter_is_valid():
    fm = _frontmatter(_SKILL.read_text(encoding="utf-8"))
    assert fm.get("name") == "docs-sync"
    assert (fm.get("description") or "").strip()


def test_skill_points_at_the_real_battery():
    body = _SKILL.read_text(encoding="utf-8")
    assert "src/tools/scripts/check_docs.py" in body, "skill must drive the doc-health battery"
    # The battery the skill drives must actually exist and be importable-by-path.
    assert (_ROOT / "src" / "tools" / "scripts" / "check_docs.py").is_file()


def test_skill_references_the_reference_pages():
    body = _SKILL.read_text(encoding="utf-8")
    assert "docs/reference/cli.md" in body
    assert "docs/reference/configuration.md" in body
    assert (_ROOT / "docs" / "reference" / "cli.md").is_file()
    assert (_ROOT / "docs" / "reference" / "configuration.md").is_file()
