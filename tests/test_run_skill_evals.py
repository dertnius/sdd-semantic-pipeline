"""Tests for the deterministic skill-eval harness (src/tools/scripts/run_skill_evals.py).

Two jobs (same shape as tests/test_check_copilot.py):
1. **Green guard** — the real seeded eval suites pass end-to-end (the runner drives
   each skill's vendored scripts and code-grades the assertions), so `pytest` fails the
   moment a skill's engine regresses against a committed eval — the same guarantee the
   CI skill-eval gate gives. Also asserts every committed evals.json is well-formed.
2. **Trustworthy checker** — every grader is shown to FAIL on a wrong output (not just
   pass on a right one), so the gate can't pass blind, and an unknown assertion type
   raises rather than silently passing.

Fast + model-free (no pandoc, no embedding model). The seeded gliffy-to-drawio suite is
pure stdlib, so the green guard runs in the fast lane. The script is loaded by path
because src/tools/ is dev tooling, not an installed package.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "src" / "tools" / "scripts" / "run_skill_evals.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_skill_evals", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rse = _load()


def _ctx(*, returncode=0, stdout="", stderr="", facts=None) -> dict:
    """A grader context with a real CompletedProcess and an identity expander."""
    proc = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)
    return {"proc": proc, "facts": facts, "exp": lambda s: s}


# ── 1. green guard: the real seeded eval suites pass, manifests are well-formed ──


def test_seeded_gliffy_drawio_eval_passes(tmp_path):
    """End-to-end: run the committed gliffy-to-drawio suite, expect all cases green."""
    rc = rse.main(["--skill", "gliffy-to-drawio", "--out", str(tmp_path)])
    assert rc == 0
    bench = json.loads((tmp_path / "iteration-1" / "benchmark.json").read_text(encoding="utf-8"))
    assert bench["total_cases"] > 0
    assert bench["failed"] == 0 and bench["passed"] == bench["total_cases"]


def test_all_eval_manifests_are_wellformed():
    """Every committed evals.json: unique ids, fixtures exist, known assertion types,
    and each case's command names a real script under the skill dir."""
    manifests = sorted(rse.SKILLS_DIR.glob("*/evals/evals.json"))
    assert manifests, "expected at least one seeded evals.json"
    for manifest in manifests:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        evals_dir, skill_dir = manifest.parent, manifest.parent.parent
        ids = [c["id"] for c in data["cases"]]
        assert len(ids) == len(set(ids)), f"duplicate case ids in {manifest}"
        for case in data["cases"]:
            for rel in case["files"]:
                assert (evals_dir / rel).exists(), f"missing fixture {rel} in {manifest}"
            for a in case["assertions"]:
                assert a["type"] in rse.GRADERS, f"unknown assertion type {a['type']!r} in {manifest}"
            scripts = [t for t in case["command"] if t.endswith(".py") and "{" not in t]
            for ref in scripts:
                assert (skill_dir / ref).exists(), f"command names missing script {ref} in {manifest}"


# ── 2. trustworthy checker: every grader detects a wrong output ──────────────────


def test_exit_code_grader():
    assert rse.GRADERS["exit_code"]({"op": "==", "value": 0}, _ctx(returncode=0))[0]
    assert not rse.GRADERS["exit_code"]({"op": "==", "value": 0}, _ctx(returncode=2))[0]
    assert rse.GRADERS["exit_code"]({"op": "!=", "value": 0}, _ctx(returncode=1))[0]


def test_stream_contains_graders():
    assert rse.GRADERS["stdout_contains"]({"needle": "[check: OK]"}, _ctx(stdout="x [check: OK]"))[0]
    assert not rse.GRADERS["stdout_contains"]({"needle": "[check: OK]"}, _ctx(stdout="nope"))[0]
    assert rse.GRADERS["stdout_not_contains"]({"needle": "DIFFS"}, _ctx(stdout="clean"))[0]
    assert not rse.GRADERS["stdout_not_contains"]({"needle": "DIFFS"}, _ctx(stdout="2 DIFFS"))[0]
    assert rse.GRADERS["stderr_contains"]({"needle": "FAIL"}, _ctx(stderr="FAIL boom"))[0]
    assert not rse.GRADERS["stderr_contains"]({"needle": "FAIL"}, _ctx(stderr=""))[0]


def test_file_exists_and_absent_graders(tmp_path):
    present = tmp_path / "a.drawio"
    present.write_text("x", encoding="utf-8")
    missing = tmp_path / "missing.drawio"
    ctx = _ctx()
    assert rse.GRADERS["file_exists"]({"path": str(present)}, ctx)[0]
    assert not rse.GRADERS["file_exists"]({"path": str(missing)}, ctx)[0]
    assert rse.GRADERS["file_absent"]({"path": str(missing)}, ctx)[0]
    assert not rse.GRADERS["file_absent"]({"path": str(present)}, ctx)[0]


def test_valid_xml_and_is_mxgraph_graders(tmp_path):
    good = tmp_path / "g.drawio"
    good.write_text(
        "<mxfile><diagram><mxGraphModel><root/></mxGraphModel></diagram></mxfile>", encoding="utf-8"
    )
    broken = tmp_path / "b.drawio"
    broken.write_text("<mxfile><diagram>", encoding="utf-8")  # unclosed
    not_mx = tmp_path / "n.xml"
    not_mx.write_text("<foo><bar/></foo>", encoding="utf-8")
    ctx = _ctx()
    assert rse.GRADERS["valid_xml"]({"path": str(good)}, ctx)[0]
    assert not rse.GRADERS["valid_xml"]({"path": str(broken)}, ctx)[0]
    assert rse.GRADERS["is_mxgraph"]({"path": str(good)}, ctx)[0]
    assert not rse.GRADERS["is_mxgraph"]({"path": str(not_mx)}, ctx)[0]


def test_xml_contains_grader(tmp_path):
    f = tmp_path / "g.drawio"
    f.write_text('<mxCell edge="1" style="dashed=1"/>', encoding="utf-8")
    ctx = _ctx()
    assert rse.GRADERS["xml_contains"]({"path": str(f), "needle": 'edge="1"'}, ctx)[0]
    assert not rse.GRADERS["xml_contains"]({"path": str(f), "needle": "rounded=1"}, ctx)[0]


def test_model_count_and_roundtrip_graders():
    facts = {"parse_ok": True, "nodes": 3, "edges": 1, "placeholders": 0, "roundtrip_equal": True}
    ctx = _ctx(facts=facts)
    assert rse.GRADERS["node_count"]({"op": "==", "value": 3}, ctx)[0]
    assert not rse.GRADERS["node_count"]({"op": "==", "value": 2}, ctx)[0]
    assert rse.GRADERS["edge_count"]({"op": ">=", "value": 1}, ctx)[0]
    assert rse.GRADERS["placeholder_count"]({"op": "==", "value": 0}, ctx)[0]
    assert rse.GRADERS["roundtrip_ok"]({}, ctx)[0]
    # round-trip mismatch must fail, not crash
    bad_rt = _ctx(facts={**facts, "roundtrip_equal": False})
    assert not rse.GRADERS["roundtrip_ok"]({}, bad_rt)[0]
    # a parse failure makes every model grader FAIL (with evidence), never raise
    no_parse = _ctx(facts={"parse_ok": False, "error": "boom"})
    assert not rse.GRADERS["node_count"]({"op": "==", "value": 0}, no_parse)[0]
    assert not rse.GRADERS["roundtrip_ok"]({}, no_parse)[0]


def test_unknown_assertion_type_raises():
    with pytest.raises(SystemExit):
        rse.grade_assertions([{"type": "frobnicate"}], _ctx(), case_id="x")
