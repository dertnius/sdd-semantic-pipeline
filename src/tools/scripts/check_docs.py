#!/usr/bin/env python
"""Documentation health battery — proves the docs are *not broken* and *updated*.

Pure-stdlib (only imports the `sdd_pipeline` package to read the live CLI/config
surface — no embedding model, no pandoc, no MkDocs). Runs every check, prints a
grouped report, and exits non-zero if **any** check fails, so a stale or broken
doc cannot merge. Wired into the CI `verify` stage and the `/docs-sync` skill.

Two intents:

  Not broken (structure / links)
    B1  intra-docs links resolve (relative `[text](target)` + images)
    B2  links to repo source files (src/…, tests/…, config/…) resolve on disk
    B4  well-formedness: balanced code fences, closed YAML frontmatter
    (B3 — `mkdocs build --strict` for nav/render/orphans — is a separate CI step.)

  Updated (doc <-> code alignment)
    U1  every CLI command is documented in docs/reference/cli.md (both directions)
    U2  every CLI flag is documented in its command's section (+ no ghost flags)
    U3  every PIPELINE_* setting in configuration.md maps to a PipelineConfig field
        and every field is documented (both directions)
    U4  documented install extras match pyproject's optional-dependencies
    U5  every source file cited in the learn/ freshness table (and every
        `module.py::symbol` citation) resolves on disk

Usage:  python src/tools/scripts/check_docs.py [--verbose]
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "docs"
SRC_PKG = REPO / "src" / "sdd_pipeline"

# docs/ subtrees kept in the repo but out of the published site (mirrors mkdocs
# exclude_docs) — historical/ingest material, not held to the live-link bar.
_EXCLUDED_DOCS_DIRS = {"archive", "inbox", "notes"}

# Roots a bare `module.py` citation may resolve under (U5).
_MODULE_ROOTS = [
    SRC_PKG,
    SRC_PKG / "convert",
    REPO / "src" / "tools" / "scripts",
    REPO / "tests",
    REPO,
]

# Markdown inline link / image: [text](target) or ![alt](target). Group 1 = target.
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_PIPELINE_ENV_RE = re.compile(r"PIPELINE_[A-Z0-9_]+")
_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")
# A `module.py::symbol` citation (the `::` is a strong real-code-reference signal).
_CITATION_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*\.py)::[A-Za-z_]")


# ── helpers ──────────────────────────────────────────────────────────────────


def _iter_docs() -> list[Path]:
    """All published-tree markdown files under docs/ (excluding archived subtrees)."""
    out = []
    for p in sorted(DOCS.rglob("*.md")):
        rel = p.relative_to(DOCS)
        if rel.parts and rel.parts[0] in _EXCLUDED_DOCS_DIRS:
            continue
        out.append(p)
    return out


def _scanned_markdown() -> list[Path]:
    """Docs in scope for link/well-formedness checks + the two root anchors."""
    return _iter_docs() + [REPO / "README.md", REPO / "CLAUDE.md"]


def _cli_commands() -> dict:
    """name -> click.Command for every registered CLI command (live, from code)."""
    import typer

    from sdd_pipeline.cli import app

    group = typer.main.get_command(app)
    return dict(group.commands)


def _config_fields() -> set[str]:
    """Field names of PipelineConfig (pydantic v2 model_fields or v1 __fields__)."""
    from sdd_pipeline.config import PipelineConfig

    fields = getattr(PipelineConfig, "model_fields", None) or getattr(
        PipelineConfig, "__fields__", {}
    )
    return set(fields.keys())


def _command_sections(cli_md: str) -> dict[str, str]:
    """Map each `## <command>` heading to its section text (heading -> next `## `)."""
    sections: dict[str, str] = {}
    lines = cli_md.splitlines()
    cur: str | None = None
    buf: list[str] = []
    for ln in lines:
        m = re.match(r"^##\s+([a-z][a-z0-9-]*)\s*$", ln)
        if m:
            if cur is not None:
                sections[cur] = "\n".join(buf)
            cur = m.group(1)
            buf = []
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        sections[cur] = "\n".join(buf)
    return sections


def _strip_code(text: str) -> str:
    """Blank fenced + inline code so doc *examples* (e.g. a sample `![](x.png)`) are
    not mistaken for real links — mirrors the lint de-fencing approach."""
    out, in_fence = [], False
    for ln in text.splitlines():
        if _FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        out.append("" if in_fence else ln)
    return re.sub(r"`[^`]*`", "", "\n".join(out))


def _resolve_module(token: str) -> bool:
    """True if a cited file token resolves on disk (path-like or bare module name)."""
    if "/" in token or "\\" in token:
        return (REPO / token).exists()
    if any((root / token).exists() for root in _MODULE_ROOTS):
        return True
    # bare filename may live deeper (e.g. tests/convert/test_x.py) — search recursively.
    return any(next(iter(root.rglob(token)), None) is not None for root in (SRC_PKG, REPO / "tests"))


# ── checks ───────────────────────────────────────────────────────────────────


def check_links() -> list[str]:
    """B1 + B2 — every relative markdown link/image target resolves on disk.

    Skips: external (http/mailto), in-page anchors, links inside code *examples*
    (de-fenced first), template/ (a worked-example SAD whose links are illustrative),
    and the generated outbox/ artifact zone (regenerable, gitignored)."""
    errors: list[str] = []
    for md in _scanned_markdown():
        rel = md.relative_to(REPO)
        if rel.parts[:2] == ("docs", "template"):
            continue
        try:
            text = _strip_code(md.read_text(encoding="utf-8"))
        except OSError as exc:  # pragma: no cover - unreadable file
            errors.append(f"{rel}: cannot read ({exc})")
            continue
        for target in _LINK_RE.findall(text):
            t = target.strip()
            if not t or t.startswith(("http://", "https://", "mailto:", "#", "{", "data:")):
                continue
            t = t.split("#", 1)[0].split("?", 1)[0]
            if not t or "outbox/" in t:  # generated artifact zone — regenerable
                continue
            if not (md.parent / t).resolve().exists():
                errors.append(f"{rel}: broken link -> {target}")
    return errors


def check_wellformed() -> list[str]:
    """B4 — balanced code fences and a closed YAML frontmatter block."""
    errors: list[str] = []
    for md in _iter_docs():
        text = md.read_text(encoding="utf-8")
        fences = sum(1 for ln in text.splitlines() if _FENCE_RE.match(ln))
        if fences % 2 != 0:
            errors.append(f"{md.relative_to(REPO)}: unbalanced code fence ({fences} found)")
        if text.startswith("---\n") and "\n---" not in text[4:]:
            errors.append(f"{md.relative_to(REPO)}: unterminated YAML frontmatter")
    return errors


def check_cli_commands() -> list[str]:
    """U1 — cli.md documents exactly the registered commands (both directions)."""
    errors: list[str] = []
    cli_md_path = DOCS / "reference" / "cli.md"
    if not cli_md_path.is_file():
        return [f"missing {cli_md_path.relative_to(REPO)}"]
    documented = set(_command_sections(cli_md_path.read_text(encoding="utf-8")).keys())
    required = set(_cli_commands().keys())
    for missing in sorted(required - documented):
        errors.append(f"cli.md: command '{missing}' not documented (## {missing})")
    for ghost in sorted(documented - required):
        errors.append(f"cli.md: documents '{ghost}' which is not a real command")
    return errors


def check_cli_flags() -> list[str]:
    """U2 — each command's options appear in its section; no documented ghost flags."""
    errors: list[str] = []
    cli_md_path = DOCS / "reference" / "cli.md"
    if not cli_md_path.is_file():
        return [f"missing {cli_md_path.relative_to(REPO)}"]
    sections = _command_sections(cli_md_path.read_text(encoding="utf-8"))
    for name, cmd in _cli_commands().items():
        section = sections.get(name)
        if section is None:
            continue  # U1 already reports the missing section
        real_long: set[str] = {"--help"}
        for p in cmd.params:
            if getattr(p, "name", None) == "help":
                continue
            for o in list(getattr(p, "opts", [])) + list(getattr(p, "secondary_opts", [])):
                if o.startswith("--"):
                    real_long.add(o)
        # code -> doc: every real long option is mentioned in the section
        for p in cmd.params:
            if getattr(p, "name", None) == "help":
                continue
            longs = [
                o
                for o in list(getattr(p, "opts", [])) + list(getattr(p, "secondary_opts", []))
                if o.startswith("--")
            ]
            if longs and not any(o in section for o in longs):
                errors.append(f"cli.md [{name}]: flag {longs[0]} not documented")
        # doc -> code: every --flag in a table row of the section is a real option
        for ln in section.splitlines():
            if not ln.lstrip().startswith("|"):
                continue
            for tok in _FLAG_RE.findall(ln):
                if tok not in real_long:
                    errors.append(f"cli.md [{name}]: documents unknown flag {tok}")
    return errors


def check_config() -> list[str]:
    """U3 — configuration.md documents exactly the PipelineConfig fields."""
    errors: list[str] = []
    cfg_md_path = DOCS / "reference" / "configuration.md"
    if not cfg_md_path.is_file():
        return [f"missing {cfg_md_path.relative_to(REPO)}"]
    text = cfg_md_path.read_text(encoding="utf-8")
    documented = set(_PIPELINE_ENV_RE.findall(text))
    expected = {f"PIPELINE_{name.upper()}" for name in _config_fields()}
    for missing in sorted(expected - documented):
        errors.append(f"configuration.md: setting '{missing}' not documented")
    for ghost in sorted(documented - expected):
        # Ignore wildcard/family mentions like `PIPELINE_DOWNLOAD_*` (a prefix of real names).
        if any(e.startswith(ghost) for e in expected):
            continue
        errors.append(f"configuration.md: documents '{ghost}' which is not a config field")
    return errors


def check_extras() -> list[str]:
    """U4 — documented install extras match pyproject optional-dependencies."""
    errors: list[str] = []
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    real = set(data.get("project", {}).get("optional-dependencies", {}).keys())
    cfg_md = (DOCS / "reference" / "configuration.md").read_text(encoding="utf-8")
    # Documented extras: the backticked token in the first cell of the extras table
    # (lowercase-initial, so the uppercase `PIPELINE_*` setting tables are excluded).
    documented = set(re.findall(r"^\|\s*`([a-z][a-z0-9-]*)`\s*\|", cfg_md, re.MULTILINE))
    for missing in sorted(real - documented):
        errors.append(f"configuration.md: extra '[{missing}]' not documented")
    for ghost in sorted(documented - real):
        errors.append(f"configuration.md: documents extra '[{ghost}]' which does not exist")
    return errors


def check_citations() -> list[str]:
    """U5 — learn/ freshness-table sources and `module.py::symbol` citations resolve."""
    errors: list[str] = []
    learn = DOCS / "learn"
    if not learn.is_dir():
        return errors
    seen: set[str] = set()

    # Freshness table in learn/README.md: pull file-looking tokens from its rows.
    readme = learn / "README.md"
    if readme.is_file():
        in_table = False
        for ln in readme.read_text(encoding="utf-8").splitlines():
            if "Source files cited" in ln or "source files" in ln.lower():
                in_table = True
                continue
            if in_table and ln.lstrip().startswith("|"):
                for tok in re.findall(r"`([^`]+)`", ln):
                    for f in re.split(r"[,\s]+", tok):
                        f = f.strip(" .")
                        if f.endswith((".py", ".toml")) and f not in seen:
                            seen.add(f)
                            if not _resolve_module(f):
                                errors.append(f"learn/README.md freshness table: {f} not found")

    # `module.py::symbol` citations anywhere under learn/.
    # `module.py` is the documented placeholder for the citation convention itself.
    placeholders = {"module.py"}
    for md in sorted(learn.rglob("*.md")):
        for mod in _CITATION_RE.findall(md.read_text(encoding="utf-8")):
            if mod in seen or mod in placeholders:
                continue
            seen.add(mod)
            if not _resolve_module(mod):
                errors.append(f"{md.relative_to(REPO)}: citation {mod} not found")
    return errors


_CHECKS = [
    ("B1+B2 links", check_links),
    ("B4 well-formed", check_wellformed),
    ("U1 CLI commands", check_cli_commands),
    ("U2 CLI flags", check_cli_flags),
    ("U3 config", check_config),
    ("U4 extras", check_extras),
    ("U5 learn citations", check_citations),
]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    verbose = "--verbose" in argv or "-v" in argv
    sys.path.insert(0, str(REPO / "src"))  # make `import sdd_pipeline` work standalone

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
        print(f"check-docs: {total} issue(s) - docs are out of sync with the code.")
        return 1
    print("check-docs: all checks passed — docs are not broken and up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
