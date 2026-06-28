#!/usr/bin/env python
"""Copilot integration health battery — proves the GitHub Copilot assets are
*not broken* and *wired to real code*.

Sibling of ``check_docs.py``: pure-stdlib + the live CLI surface (typer, a core
dep) + a regex read of ``mcp_server.py`` for the MCP tool names. **No** embedding
model, **no** pandoc, **no** ``mcp`` SDK import. Runs every check, prints a grouped
report, and exits non-zero if **any** check fails, so a broken Copilot asset cannot
merge. Wired into CI (the GitHub ``copilot-health`` workflow + the GitLab ``verify``
stage) and the ``.github/instructions/copilot-assets.instructions.md`` guardrail.

Scope — the tracked agent-asset surface (Copilot integration + portable skills):

  .github/prompts/*.prompt.md            reusable /slash prompts (Copilot-only ports)
  .github/agents/*.agent.md              custom agents (e.g. the ADR Generator)
  .github/instructions/*.instructions.md scoped guardrails (applyTo globs)
  .github/copilot-instructions.md        repo-wide Copilot instructions
  .github/**/*.md                        any other Copilot markdown (link/shape checks)
  .vscode/mcp.json                       the sdd-semantic MCP server registration
  .claude/skills/*/SKILL.md              portable Agent Skills, read NATIVELY by both
                                         Claude Code and Copilot (the single source of
                                         truth — see CLAUDE.md "GitHub Copilot integration")

Checks:

  C1 frontmatter   prompts have a non-empty `description`; agents have `name` +
                   `description` (and any `agents:` refs resolve to real subagents);
                   instructions have a non-empty `applyTo`.
  C2 CLI refs      every `sdd-pipeline <cmd>` / `-m sdd_pipeline.cli <cmd>` used in a
                   code span resolves to a registered CLI command.
  C3 MCP wiring    .vscode/mcp.json registers the sdd-semantic stdio server whose args
                   invoke a real CLI command; every MCP tool referenced in call form
                   (`tool_name(`) is one the server actually exposes.
  C4 links         relative markdown links / source-file links in the assets resolve.
  C5 well-formed   balanced code fences + a closed YAML frontmatter block.
  C6 skills        every .claude/skills/*/SKILL.md has Agent-Skills-spec frontmatter:
                   `name` present, equal to its directory, lowercase letters/digits/
                   hyphens only (no leading/trailing/double hyphen), <=64 chars; and a
                   non-empty `description` of <=1024 chars.

The code-span/link/shape checks (C2/C4/C5) also cover the skill bodies; C3's tool-ref
scan does too, so a SKILL.md naming a non-existent MCP tool in call form is caught.

Usage:  python src/tools/scripts/check_copilot.py [--verbose]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GH = REPO / ".github"
PROMPTS = GH / "prompts"
AGENTS = GH / "agents"
INSTRUCTIONS = GH / "instructions"
COPILOT_INSTRUCTIONS = GH / "copilot-instructions.md"
MCP_JSON = REPO / ".vscode" / "mcp.json"
MCP_SERVER = REPO / "src" / "sdd_pipeline" / "mcp_server.py"
# Portable Agent Skills — the single tracked source both Claude Code and Copilot read.
SKILLS = REPO / ".claude" / "skills"

# Markdown inline link / image: [text](target). Group 1 = target.
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_FM_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
# The console-script form is always a command; the module form only when run via `-m`
# (so `from sdd_pipeline.cli import app` is not mistaken for a command invocation).
_CLI_SCRIPT_RE = re.compile(r"sdd-pipeline\s+([a-z][a-z0-9-]*)")
_CLI_MODULE_RE = re.compile(r"-m\s+sdd_pipeline\.cli\s+([a-z][a-z0-9-]*)")
# A snake_case (≥1 underscore) identifier used in call form — an MCP tool reference.
_TOOL_CALL_RE = re.compile(r"\b([a-z][a-z0-9_]*_[a-z0-9_]*)\s*\(")
# A `.tool()` / `.tool(...)` decorator (FastMCP) — the next def is the tool name.
_TOOL_DECORATOR_RE = re.compile(r"\.tool\s*\(")
_DEF_RE = re.compile(r"\s*def\s+([a-z_][a-z0-9_]*)\s*\(")
# Agent Skills `name` spec: lowercase letters/digits/hyphens, no leading/trailing hyphen
# (the `--` ban and the 64-char cap are checked separately for clearer messages).
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# Documented placeholders that appear in call form but are not real tools (mirrors
# check_docs.py's `module.py` placeholder). `tool_name(` is the convention example in
# copilot-assets.instructions.md. Add a real core helper here if a prompt example uses
# it in call form (it is a package symbol, not an MCP tool).
_KNOWN_NON_TOOL_CALLABLES = {"tool_name"}


# ── helpers ──────────────────────────────────────────────────────────────────


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO))


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _markdown_assets() -> list[Path]:
    """Every tracked agent-asset markdown file — the .github/ Copilot surface (prompts,
    agents, instructions, the repo-wide instructions, any README) plus the portable
    .claude/skills/ bodies — the scope for code-span/link/shape checks (C2/C3/C4/C5)."""
    out: list[Path] = []
    if GH.is_dir():
        out.extend(GH.rglob("*.md"))
    if SKILLS.is_dir():
        out.extend(SKILLS.rglob("*.md"))
    return sorted(out)


def _frontmatter_block(text: str) -> str | None:
    """The body of the leading ``---`` YAML block, or None if absent/unterminated."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def _fm_keys(block: str) -> dict[str, str]:
    """Minimal stdlib frontmatter parse — top-level ``key: value`` lines (enough to
    assert required keys are present and non-empty; values are quote-stripped)."""
    out: dict[str, str] = {}
    for ln in block.splitlines():
        m = _FM_KEY_RE.match(ln)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("'\"").strip()
    return out


def _parse_agents_list(raw: str) -> list[str]:
    """Parse an inline ``agents: [a, b]`` coordinator frontmatter value into names."""
    raw = raw.strip()
    if not raw:
        return []
    raw = raw.removeprefix("[").removesuffix("]")
    return [s.strip().strip("'\"") for s in raw.split(",") if s.strip()]


def _code_spans(text: str) -> str:
    """Concatenated code only — fenced-block bodies + inline `…` spans. Command/tool
    references are scanned here so prose mentions (e.g. 'the sdd-pipeline package')
    are never mistaken for invocations."""
    parts: list[str] = []
    in_fence = False
    for ln in text.splitlines():
        if _FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            parts.append(ln)
    parts.extend(re.findall(r"`([^`\n]+)`", text))
    return "\n".join(parts)


def _cli_commands() -> set[str]:
    """Names of every registered CLI command (live, from code — same source the
    doc-health gate reads)."""
    import typer

    from sdd_pipeline.cli import app

    return set(typer.main.get_command(app).commands.keys())


def _mcp_tool_names() -> set[str]:
    """Tool names the sdd-semantic server exposes, parsed from mcp_server.py source
    (regex, so the optional `mcp` SDK is never imported)."""
    if not MCP_SERVER.is_file():
        return set()
    lines = _read(MCP_SERVER).splitlines()
    names: set[str] = set()
    for i, ln in enumerate(lines):
        if _TOOL_DECORATOR_RE.search(ln):
            for j in range(i + 1, min(i + 4, len(lines))):
                m = _DEF_RE.match(lines[j])
                if m:
                    names.add(m.group(1))
                    break
    return names


def _command_from_args(args: list) -> str | None:
    """The first positional CLI command token in an mcp.json `args` list (the token
    after `sdd_pipeline.cli`, or the first non-flag after dropping `-m`/module)."""
    toks = [str(a) for a in args]
    for i, t in enumerate(toks):
        if t.endswith("sdd_pipeline.cli") or t == "sdd_pipeline.cli":
            nxt = toks[i + 1 :]
            for cand in nxt:
                if not cand.startswith("-"):
                    return cand
            return None
    return None


# ── checks ───────────────────────────────────────────────────────────────────


def check_frontmatter() -> list[str]:
    """C1 — required frontmatter keys are present and non-empty per asset type."""
    errors: list[str] = []
    for p in sorted(PROMPTS.glob("*.prompt.md")) if PROMPTS.is_dir() else []:
        block = _frontmatter_block(_read(p))
        if block is None:
            errors.append(f"{_rel(p)}: missing/unterminated YAML frontmatter")
            continue
        if not _fm_keys(block).get("description"):
            errors.append(f"{_rel(p)}: prompt frontmatter needs a non-empty 'description'")
    for p in sorted(AGENTS.glob("*.agent.md")) if AGENTS.is_dir() else []:
        block = _frontmatter_block(_read(p))
        if block is None:
            errors.append(f"{_rel(p)}: missing/unterminated YAML frontmatter")
            continue
        keys = _fm_keys(block)
        for key in ("name", "description"):
            if not keys.get(key):
                errors.append(f"{_rel(p)}: agent frontmatter needs a non-empty '{key}'")
        # A coordinator's `agents:` allowlist must point at real subagent files — the
        # orchestration analogue of C2 (CLI refs) and C3 (MCP tools) resolving.
        for ref in _parse_agents_list(keys.get("agents", "")):
            if not (AGENTS / f"{ref}.agent.md").is_file():
                errors.append(
                    f"{_rel(p)}: 'agents' references unknown subagent {ref!r} (no {ref}.agent.md)"
                )
    for p in sorted(INSTRUCTIONS.glob("*.instructions.md")) if INSTRUCTIONS.is_dir() else []:
        block = _frontmatter_block(_read(p))
        if block is None:
            errors.append(f"{_rel(p)}: missing/unterminated YAML frontmatter")
            continue
        if not _fm_keys(block).get("applyTo"):
            errors.append(f"{_rel(p)}: instructions frontmatter needs a non-empty 'applyTo'")
    return errors


def check_cli_refs() -> list[str]:
    """C2 — every CLI command referenced in a code span is a real command."""
    errors: list[str] = []
    real = _cli_commands()
    for p in _markdown_assets():
        code = _code_spans(_read(p))
        cmds = set(_CLI_SCRIPT_RE.findall(code)) | set(_CLI_MODULE_RE.findall(code))
        for c in sorted(cmds):
            if c not in real:
                errors.append(f"{_rel(p)}: references unknown CLI command 'sdd-pipeline {c}'")
    return errors


def check_mcp() -> list[str]:
    """C3 — mcp.json wiring is valid and every referenced MCP tool exists."""
    errors: list[str] = []
    real_tools = _mcp_tool_names()
    if not real_tools:
        errors.append(
            f"{_rel(MCP_SERVER)}: no @tool functions found (parser stale or server moved)"
        )

    # mcp.json wiring: the sdd-semantic stdio server invokes a real CLI command.
    if not MCP_JSON.is_file():
        errors.append(f"{_rel(MCP_JSON)}: missing (the sdd-semantic MCP registration)")
    else:
        try:
            data = json.loads(_read(MCP_JSON))
        except (OSError, json.JSONDecodeError) as exc:
            return [*errors, f"{_rel(MCP_JSON)}: cannot parse ({exc})"]
        servers = data.get("servers") or data.get("mcpServers") or {}
        if "sdd-semantic" not in servers:
            errors.append(f"{_rel(MCP_JSON)}: missing 'sdd-semantic' server registration")
        else:
            cmd = _command_from_args(servers["sdd-semantic"].get("args", []))
            if cmd is None:
                errors.append(f"{_rel(MCP_JSON)}: sdd-semantic args do not invoke a CLI command")
            elif cmd not in _cli_commands():
                errors.append(f"{_rel(MCP_JSON)}: sdd-semantic invokes unknown command '{cmd}'")

    # Referenced tools (call form, in code spans) must be ones the server exposes.
    if real_tools:
        for p in _markdown_assets():
            code = _code_spans(_read(p))
            for name in sorted(set(_TOOL_CALL_RE.findall(code))):
                if name in real_tools or name in _KNOWN_NON_TOOL_CALLABLES:
                    continue
                errors.append(
                    f"{_rel(p)}: references unknown MCP tool '{name}(...)' "
                    f"(known: {', '.join(sorted(real_tools))})"
                )
    return errors


def check_links() -> list[str]:
    """C4 — relative markdown links / source-file links in the assets resolve."""
    errors: list[str] = []
    for p in _markdown_assets():
        for target in _LINK_RE.findall(_code_spans_stripped(_read(p))):
            t = target.strip()
            if not t or t.startswith(("http://", "https://", "mailto:", "#", "{", "data:")):
                continue
            t = t.split("#", 1)[0].split("?", 1)[0]
            if not t:
                continue
            base = REPO if t.startswith("/") else p.parent
            rel_t = t.lstrip("/")
            if not (base / rel_t).resolve().exists():
                errors.append(f"{_rel(p)}: broken link -> {target}")
    return errors


def check_wellformed() -> list[str]:
    """C5 — balanced code fences and a closed YAML frontmatter block."""
    errors: list[str] = []
    for p in _markdown_assets():
        text = _read(p)
        fences = sum(1 for ln in text.splitlines() if _FENCE_RE.match(ln))
        if fences % 2 != 0:
            errors.append(f"{_rel(p)}: unbalanced code fence ({fences} found)")
        if text.startswith("---\n") and _frontmatter_block(text) is None:
            errors.append(f"{_rel(p)}: unterminated YAML frontmatter")
    return errors


def _code_spans_stripped(text: str) -> str:
    """Text with fenced + inline code blanked — so a link inside a code *example* is
    not treated as a real link (mirrors check_docs._strip_code)."""
    out, in_fence = [], False
    for ln in text.splitlines():
        if _FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        out.append("" if in_fence else ln)
    return re.sub(r"`[^`]*`", "", "\n".join(out))


def check_skills() -> list[str]:
    """C6 — every .claude/skills/<dir>/SKILL.md carries Agent-Skills-spec frontmatter.

    Validates the two required fields against the open standard (agentskills.io
    /specification): `name` is present, equals its directory, matches the lowercase
    letters/digits/hyphens grammar (no leading/trailing/double hyphen) and is <=64
    chars; `description` is present and <=1024 chars. Skips silently when the skills
    dir is absent (e.g. a checkout without the tracked subtree)."""
    errors: list[str] = []
    if not SKILLS.is_dir():
        return errors
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        skill_dir = skill_md.parent.name
        block = _frontmatter_block(_read(skill_md))
        if block is None:
            errors.append(f"{_rel(skill_md)}: missing/unterminated YAML frontmatter")
            continue
        keys = _fm_keys(block)
        name = keys.get("name", "")
        if not name:
            errors.append(f"{_rel(skill_md)}: skill frontmatter needs a non-empty 'name'")
        else:
            if name != skill_dir:
                errors.append(
                    f"{_rel(skill_md)}: 'name: {name}' must equal the skill directory '{skill_dir}'"
                )
            if len(name) > 64 or not _SKILL_NAME_RE.match(name) or "--" in name:
                errors.append(
                    f"{_rel(skill_md)}: invalid skill 'name: {name}' "
                    "(lowercase letters/digits/hyphens, no leading/trailing/double hyphen, <=64 chars)"
                )
        desc = keys.get("description", "")
        if not desc:
            errors.append(f"{_rel(skill_md)}: skill frontmatter needs a non-empty 'description'")
        elif len(desc) > 1024:
            errors.append(
                f"{_rel(skill_md)}: 'description' exceeds 1024 chars ({len(desc)}) — trim it"
            )
    return errors


_CHECKS = [
    ("C1 frontmatter", check_frontmatter),
    ("C2 CLI refs", check_cli_refs),
    ("C3 MCP wiring", check_mcp),
    ("C4 links", check_links),
    ("C5 well-formed", check_wellformed),
    ("C6 skills", check_skills),
]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    verbose = "--verbose" in argv or "-v" in argv
    sys.path.insert(0, str(REPO / "src"))  # make `import sdd_pipeline` work standalone

    if not GH.is_dir() and not SKILLS.is_dir():
        print("check-copilot: no .github/ or .claude/skills/ — nothing to check.")
        return 0

    total = 0
    for label, fn in _CHECKS:
        errors = fn()
        total += len(errors)
        mark = "FAIL" if errors else "ok"
        print(f"[{mark}] {label}: {len(errors)} issue(s)")
        if errors and (verbose or True):
            for e in errors:
                print(f"    - {e}")
    print()
    if total:
        print(f"check-copilot: {total} issue(s) - agent assets are broken or stale.")
        return 1
    print("check-copilot: all checks passed — agent assets are valid and wired to real code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
