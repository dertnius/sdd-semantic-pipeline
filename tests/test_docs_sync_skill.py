"""Contract test for the docs-sync skill ↔ doc-health battery wiring.

The skill (``.claude/skills/docs-sync/SKILL.md``) is a thin local helper that drives
``src/tools/scripts/check_docs.py`` and the CLI ``help``. ``.claude/`` is gitignored,
so the skill is absent on a fresh clone / in CI — these checks **skip** when it is
missing (the tracked, enforced guarantee is ``check_docs.py`` + the CI verify stage,
covered by ``tests/test_check_docs.py``). When the skill is present (local dev), the
checks guard the contract: valid frontmatter, and the tools it points at still exist.
Fast + model-free.
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
