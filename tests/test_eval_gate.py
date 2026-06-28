"""Tests for the retrieval-quality gate decision (src/tools/scripts/eval_gate.py).

Pure + model-free: ``evaluate_gate`` decides pass/fail from plain dicts, so the gating
rule (absolute floor, baseline regression band, lexical-control no-regression) is tested
without pandoc, a model, or a built index. The script is loaded by path because
src/tools/ is dev tooling, not an installed package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "src" / "tools" / "scripts" / "eval_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("eval_gate", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eg = _load()


def _results(recall10: float, control10: float | None = None) -> dict:
    by_cat = {}
    if control10 is not None:
        by_cat["lexical-control"] = {
            "recall@10": control10,
            "recall@5": control10,
            "MRR": control10,
        }
    return {
        "embedder": {"provider": "azure", "model": "text-embedding-3-large"},
        "aggregate": {"recall@10": recall10, "recall@5": recall10, "MRR": recall10},
        "by_category": by_cat,
    }


def test_pass_above_floor_with_baseline():
    base = _results(0.60, 0.90)
    passed, reasons = eg.evaluate_gate(_results(0.62, 0.90), base)
    assert passed is True
    assert reasons == []


def test_fail_below_absolute_floor():
    passed, reasons = eg.evaluate_gate(_results(0.40), None, floor=0.5)
    assert passed is False
    assert any("below floor" in r for r in reasons)


def test_fail_aggregate_regression_vs_baseline():
    base = _results(0.70)
    passed, reasons = eg.evaluate_gate(_results(0.60), base, floor=0.5, noise=0.02)
    assert passed is False
    assert any("regressed vs baseline" in r for r in reasons)


def test_fail_lexical_control_regression():
    base = _results(0.70, 0.95)
    # Aggregate holds, but the lexical-control regression alone must fail the gate.
    passed, reasons = eg.evaluate_gate(_results(0.71, 0.80), base, floor=0.5, noise=0.02)
    assert passed is False
    assert any("lexical-control" in r and "regressed" in r for r in reasons)


def test_missing_baseline_is_informational_not_failure():
    passed, reasons = eg.evaluate_gate(_results(0.55), None, floor=0.5)
    assert passed is True  # floor met; absent baseline is only a note
    assert any("no baseline.json" in r for r in reasons)


def test_missing_metric_fails():
    passed, reasons = eg.evaluate_gate({"aggregate": {}}, None)
    assert passed is False
    assert any("no aggregate recall@10" in r for r in reasons)


def test_within_noise_band_is_not_a_regression():
    base = _results(0.62)
    passed, _ = eg.evaluate_gate(_results(0.61), base, floor=0.5, noise=0.02)
    assert passed is True  # 0.01 drop is within the 0.02 noise band
