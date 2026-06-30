#!/usr/bin/env python3
"""run_skill_evals.py -- deterministic, model-free evaluation of Agent Skills.

This is **Layer A** of the skill-evaluation design: it runs each skill's *vendored*
``scripts/`` on the fixtures committed under ``<skill>/evals/files/`` and then
CODE-GRADES the structural ``assertions`` declared in ``<skill>/evals/evals.json``.
No LLM, no agent runtime -- a deterministic sibling of ``check_copilot.py`` /
``check_docs.py``, suitable for the CI fast lane.

It honours the agentskills.io eval schema (``prompt`` / ``expected_output`` /
``files`` / ``assertions``) and adds two deterministic keys per case:

  * ``command`` -- argv for invoking the skill's engine (templated, see below).
  * ``assertions[].type`` -- a grader name from ``GRADERS`` (each grades one
    structured assertion to PASS/FAIL **with evidence**).

Template tokens expanded in ``command`` and in assertion ``path`` / ``needle``:
  ``{python}`` = this interpreter, ``{file}`` = abs path of ``files[0]``,
  ``{stem}`` = its stem, ``{outdir}`` = the case's output directory.

The **behavioral** with-skill/without-skill comparison from the agentskills.io guide
is a separate, non-deterministic layer (driven by an agent runtime -- the
``skill-creator`` skill or Claude Code subagents) and is intentionally NOT part of
this gate. See ``docs`` / the harness README for that loop.

Usage
-----
  python src/tools/scripts/run_skill_evals.py [--skill NAME] [--iteration N]
                                              [--include-slow] [--out DIR] [-v]

Exit status: ``0`` if every graded assertion in the selected (fast-lane) cases
passed, else ``1`` -- so CI fails the moment a skill's engine regresses against a
committed eval. ``2`` for a usage / load error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
DEFAULT_OUT = REPO_ROOT / "outbox" / "skill-evals"

# ── model probes ─────────────────────────────────────────────────────────────────
# Assertions that need the parsed semantic model (not just files / streams). For
# such a case we run ONE probe subprocess from the skill's scripts/ dir (so the
# vendored flat-imports resolve) and cache the JSON facts for all model graders.
_MODEL_ASSERTIONS = {"node_count", "edge_count", "placeholder_count", "roundtrip_ok"}

_GLIFFY_PROBE = r"""
import sys, json
path = sys.argv[1]
from gliffy_to_svg import parse_gliffy
from fidelity import roundtrip_check
data = open(path, encoding="utf-8-sig").read()
try:
    m = parse_gliffy(data)
    rt = roundtrip_check(data)
    print(json.dumps({
        "parse_ok": True,
        "nodes": len(m.nodes),
        "edges": len(m.edges),
        "placeholders": sum(1 for n in m.nodes if getattr(n, "kind", None) == "placeholder"),
        "roundtrip_equal": bool(rt["equal"]),
    }))
except Exception as exc:  # parse_gliffy raises ConversionError on bad input
    print(json.dumps({"parse_ok": False, "error": str(exc)}))
"""

# skill name -> probe source. Skills that share diagram_model.py share the probe.
_MODEL_PROBES: dict[str, str] = {
    "gliffy-to-drawio": _GLIFFY_PROBE,
    "gliffy-to-svg": _GLIFFY_PROBE,
}


# ── assertion graders ────────────────────────────────────────────────────────────
# Each grader takes (assertion, ctx) and returns (passed, evidence). ctx exposes:
#   ctx["proc"]  -> CompletedProcess (returncode/stdout/stderr) of the engine run
#   ctx["facts"] -> dict of model facts (or None if no probe ran / parse failed)
#   ctx["exp"]   -> str->str template expander
Grader = Callable[[dict[str, Any], dict[str, Any]], "tuple[bool, str]"]


def _cmp(op: str, a: float, b: float) -> bool:
    return {
        "==": a == b, "!=": a != b, ">=": a >= b,
        "<=": a <= b, ">": a > b, "<": a < b,
    }[op]


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _g_exit_code(a, ctx):
    rc = ctx["proc"].returncode
    ok = _cmp(a["op"], rc, a["value"])
    return ok, f"exit code {rc} {a['op']} {a['value']}"


def _g_stream_contains(stream: str, want: bool):
    def grader(a, ctx):
        text = getattr(ctx["proc"], stream)
        needle = ctx["exp"](a["needle"])
        present = needle in text
        ok = present is want
        verb = "contains" if present else "does not contain"
        return ok, f"{stream} {verb} {needle!r}"
    return grader


def _g_file_exists(want: bool):
    def grader(a, ctx):
        p = Path(ctx["exp"](a["path"]))
        ok = p.exists() is want
        return ok, f"{p.name} {'exists' if p.exists() else 'absent'}"
    return grader


def _g_valid_xml(a, ctx):
    p = Path(ctx["exp"](a["path"]))
    if not p.exists():
        return False, f"{p.name} missing"
    try:
        ET.parse(p)
        return True, f"{p.name} is well-formed XML"
    except ET.ParseError as exc:
        return False, f"{p.name} XML parse error: {exc}"


def _g_is_mxgraph(a, ctx):
    p = Path(ctx["exp"](a["path"]))
    if not p.exists():
        return False, f"{p.name} missing"
    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as exc:
        return False, f"{p.name} XML parse error: {exc}"
    found = root.tag == "mxGraphModel" or root.find(".//mxGraphModel") is not None
    return found, f"{p.name} {'has' if found else 'has no'} <mxGraphModel>"


def _g_xml_contains(a, ctx):
    p = Path(ctx["exp"](a["path"]))
    needle = ctx["exp"](a["needle"])
    if not p.exists():
        return False, f"{p.name} missing"
    present = needle in _read(str(p))
    return present, f"{p.name} {'contains' if present else 'lacks'} {needle!r}"


def _g_model_count(field: str):
    def grader(a, ctx):
        facts = ctx["facts"]
        if not facts or not facts.get("parse_ok"):
            return False, f"no model facts ({facts.get('error') if facts else 'no probe'})"
        n = facts[field]
        ok = _cmp(a["op"], n, a["value"])
        return ok, f"{field}={n} {a['op']} {a['value']}"
    return grader


def _g_roundtrip_ok(a, ctx):
    facts = ctx["facts"]
    if not facts or not facts.get("parse_ok"):
        return False, f"no model facts ({facts.get('error') if facts else 'no probe'})"
    ok = bool(facts["roundtrip_equal"])
    return ok, f"roundtrip equal={ok}"


GRADERS: dict[str, Grader] = {
    "exit_code": _g_exit_code,
    "stdout_contains": _g_stream_contains("stdout", want=True),
    "stdout_not_contains": _g_stream_contains("stdout", want=False),
    "stderr_contains": _g_stream_contains("stderr", want=True),
    "file_exists": _g_file_exists(want=True),
    "file_absent": _g_file_exists(want=False),
    "valid_xml": _g_valid_xml,
    "is_mxgraph": _g_is_mxgraph,
    "xml_contains": _g_xml_contains,
    "node_count": _g_model_count("nodes"),
    "edge_count": _g_model_count("edges"),
    "placeholder_count": _g_model_count("placeholders"),
    "roundtrip_ok": _g_roundtrip_ok,
}


# ── runner ───────────────────────────────────────────────────────────────────────


def discover_skills(only: str | None) -> list[Path]:
    """Skill dirs that ship an evals/evals.json (optionally filtered by name)."""
    dirs = sorted(p.parent.parent for p in SKILLS_DIR.glob("*/evals/evals.json"))
    if only:
        dirs = [d for d in dirs if d.name == only]
    return dirs


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8"
    )


def _probe(skill: str, scripts: Path, input_file: Path) -> dict[str, Any] | None:
    src = _MODEL_PROBES.get(skill)
    if src is None:
        return None
    proc = subprocess.run(
        [sys.executable, "-c", src, str(input_file)],
        cwd=str(scripts), capture_output=True, text=True, encoding="utf-8",
    )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"parse_ok": False, "error": (proc.stderr or proc.stdout)[:200]}


def grade_assertions(
    assertions: list[dict[str, Any]], ctx: dict[str, Any], *, case_id: str = "?"
) -> list[dict[str, Any]]:
    """Grade each structured assertion -> ``[{type, passed, evidence}]``.

    Raises ``SystemExit`` on an unknown assertion ``type`` -- a typo must never
    silently pass (same strictness as ``check_copilot``'s unknown-ref handling).
    """
    results = []
    for a in assertions:
        grader = GRADERS.get(a["type"])
        if grader is None:
            raise SystemExit(f"unknown assertion type {a['type']!r} in case {case_id!r}")
        passed, evidence = grader(a, ctx)
        results.append({"type": a["type"], "passed": passed, "evidence": evidence})
    return results


def grade_case(skill_dir: Path, case: dict[str, Any], out_root: Path, verbose: bool) -> dict[str, Any]:
    scripts = skill_dir / "scripts"
    evals_dir = skill_dir / "evals"
    input_file = (evals_dir / case["files"][0]).resolve()
    outdir = out_root / skill_dir.name / case["id"] / "outputs"
    outdir.mkdir(parents=True, exist_ok=True)

    tokens = {
        "{python}": sys.executable,
        "{file}": str(input_file),
        "{stem}": input_file.stem,
        "{outdir}": str(outdir),
    }

    def exp(s: str) -> str:
        for k, v in tokens.items():
            s = s.replace(k, v)
        return s

    # Engine command paths (e.g. "scripts/convert_drawio.py") are relative to the
    # skill dir; run from there. Python puts the *script's* own dir (scripts/) on
    # sys.path[0], so the vendored flat sibling imports still resolve.
    argv = [exp(tok) for tok in case["command"]]
    proc = _run(argv, cwd=skill_dir)

    need_model = any(a["type"] in _MODEL_ASSERTIONS for a in case["assertions"])
    facts = _probe(skill_dir.name, scripts, input_file) if need_model else None
    ctx = {"proc": proc, "facts": facts, "exp": exp}

    results = grade_assertions(case["assertions"], ctx, case_id=case["id"])

    passed_all = all(r["passed"] for r in results)
    grading = {
        "case_id": case["id"],
        "command": argv,
        "exit_code": proc.returncode,
        "passed_all": passed_all,
        "assertions": results,
    }
    (outdir.parent / "grading.json").write_text(json.dumps(grading, indent=2), encoding="utf-8")

    mark = "PASS" if passed_all else "FAIL"
    print(f"  [{mark}] {case['id']}")
    if verbose or not passed_all:
        for r in results:
            tick = "ok " if r["passed"] else "XX "
            print(f"        {tick}{r['type']}: {r['evidence']}")
    return grading


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--skill", default=None, help="Only this skill (dir name)")
    p.add_argument("--iteration", type=int, default=1, help="Iteration number (output subdir)")
    p.add_argument("--include-slow", action="store_true", help="Also run cases marked 'slow'")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Workspace root for run artifacts")
    p.add_argument("-v", "--verbose", action="store_true", help="Show every assertion, not just failures")
    args = p.parse_args(argv)

    skills = discover_skills(args.skill)
    if not skills:
        print(f"no skills with evals/evals.json under {SKILLS_DIR}", file=sys.stderr)
        return 2

    out_root = args.out / f"iteration-{args.iteration}"
    per_skill: dict[str, dict[str, int]] = {}
    gradings: list[dict[str, Any]] = []

    for skill_dir in skills:
        manifest = json.loads((skill_dir / "evals" / "evals.json").read_text(encoding="utf-8"))
        cases = manifest.get("cases", [])
        if not args.include_slow:
            cases = [c for c in cases if "slow" not in c.get("markers", [])]
        if not cases:
            continue
        print(f"\n{skill_dir.name}  ({len(cases)} case{'s' if len(cases) != 1 else ''})")
        tally = {"passed": 0, "failed": 0}
        for case in cases:
            g = grade_case(skill_dir, case, out_root, args.verbose)
            gradings.append(g)
            tally["passed" if g["passed_all"] else "failed"] += 1
        per_skill[skill_dir.name] = tally

    total = sum(t["passed"] + t["failed"] for t in per_skill.values())
    passed = sum(t["passed"] for t in per_skill.values())
    benchmark = {
        "iteration": args.iteration,
        "skills": per_skill,
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "benchmark.json").write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    print(f"\n{'=' * 48}")
    print(f"{passed}/{total} cases passed  ->  {out_root / 'benchmark.json'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
