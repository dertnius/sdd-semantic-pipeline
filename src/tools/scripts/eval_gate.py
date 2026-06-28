#!/usr/bin/env python
"""
Retrieval-quality GATE — the CI pass/fail wrapper over ``eval_retrieval.py``.

``eval_retrieval.py`` *measures* recall@k / MRR on the frozen golden set; this turns
those numbers into a **binding gate** (a sibling of ``check_docs.py`` /
``check_copilot.py``). It exits non-zero unless retrieval quality clears an absolute
floor **and** does not regress against the recorded baseline
(``src/tools/eval/baseline.json``), with the ``lexical-control`` category held as a hard
no-regression floor — encoding the rule the RETRIEVAL_LOG states in prose
("must beat baseline and not regress lexical-control"). Wire it into CI so an
index/enrichment change that degrades retrieval cannot merge.

This is the *global* gate (run in CI / before a batch). It is distinct from the
authoring-time *precheck* (index non-empty + provenance OK), which the MCP tools enforce
directly by raising an actionable error.

Usage:
    python src/tools/scripts/eval_gate.py                  # full run (needs a model + pandoc)
    python src/tools/scripts/eval_gate.py --mock           # wiring only (no model); informational
    python src/tools/scripts/eval_gate.py --results r.json # gate a precomputed results file
    python src/tools/scripts/eval_gate.py --update-baseline  # record the current run as baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent  # .../src/tools/scripts
TOOLS = SCRIPTS.parent  # .../src/tools
ROOT = SCRIPTS.parents[2]  # repo root

DEFAULT_FLOOR = 0.5  # absolute aggregate recall@10 floor
DEFAULT_NOISE = 0.02  # run-to-run noise band; a drop within it is not a regression
GATE_METRIC = "recall@10"
CONTROL_CATEGORY = "lexical-control"
_NO_BASELINE = "no baseline.json recorded - gating on the absolute floor only"


def evaluate_gate(
    results: dict,
    baseline: dict | None,
    *,
    floor: float = DEFAULT_FLOOR,
    noise: float = DEFAULT_NOISE,
    metric: str = GATE_METRIC,
    control: str = CONTROL_CATEGORY,
) -> tuple[bool, list[str]]:
    """Decide pass/fail purely from dicts (+ optional baseline). Returns (passed, reasons).

    Fails on: missing metric, below the absolute *floor*, an aggregate regression beyond
    the *noise* band vs baseline, or a ``lexical-control`` regression beyond *noise*. A
    missing baseline is an informational note, not a failure (the floor still applies).
    """
    reasons: list[str] = []
    agg = results.get("aggregate", {})
    score = agg.get(metric)
    if score is None:
        return False, [f"results have no aggregate {metric}"]

    if score < floor:
        reasons.append(f"aggregate {metric}={score:.3f} below floor {floor:.3f}")

    if baseline:
        base_score = baseline.get("aggregate", {}).get(metric)
        if base_score is not None and score < base_score - noise:
            reasons.append(
                f"aggregate {metric}={score:.3f} regressed vs baseline "
                f"{base_score:.3f} (noise band {noise:.3f})"
            )
        base_ctrl = baseline.get("by_category", {}).get(control, {}).get(metric)
        cur_ctrl = results.get("by_category", {}).get(control, {}).get(metric)
        if base_ctrl is not None and cur_ctrl is not None and cur_ctrl < base_ctrl - noise:
            reasons.append(
                f"{control} {metric}={cur_ctrl:.3f} regressed vs baseline "
                f"{base_ctrl:.3f} (noise band {noise:.3f})"
            )
    else:
        reasons.append(_NO_BASELINE)

    hard = [r for r in reasons if r != _NO_BASELINE]
    return (not hard), reasons


def _baseline_view(results: dict) -> dict:
    """The minimal, machine-readable slice of a results dict kept as the baseline."""
    return {
        "embedder": results.get("embedder", {}),
        "aggregate": results.get("aggregate", {}),
        "by_category": results.get("by_category", {}),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Retrieval-quality gate")
    ap.add_argument("--corpus", type=Path, default=TOOLS / "eval" / "corpus")
    ap.add_argument("--queries", type=Path, default=TOOLS / "eval" / "queries.yaml")
    ap.add_argument("--baseline", type=Path, default=TOOLS / "eval" / "baseline.json")
    ap.add_argument(
        "--results", type=Path, default=None, help="Gate a precomputed results JSON instead."
    )
    ap.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    ap.add_argument("--noise", type=float, default=DEFAULT_NOISE)
    ap.add_argument("--hybrid", action="store_true")
    ap.add_argument(
        "--mock", action="store_true", help="Wiring only (hashing embedder); never fails CI."
    )
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help="Record the current run as the new baseline.json and exit 0.",
    )
    args = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT / "src"))  # make `import sdd_pipeline` work standalone
    sys.path.insert(0, str(SCRIPTS))  # make `import eval_retrieval` (sibling) work

    if args.results is not None:
        results = json.loads(args.results.read_text(encoding="utf-8"))
    else:
        import eval_retrieval

        queries = eval_retrieval.load_queries(args.queries)
        results = eval_retrieval.run_eval(
            args.corpus, queries, use_mock=args.mock, top_k=10, hybrid=args.hybrid, ks=(5, 10)
        )

    if args.update_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(_baseline_view(results), indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"eval-gate: baseline written to {args.baseline}")
        return 0

    baseline = (
        json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.is_file() else None
    )
    passed, reasons = evaluate_gate(results, baseline, floor=args.floor, noise=args.noise)

    agg = results.get("aggregate", {})
    print(
        f"eval-gate: aggregate recall@10={agg.get('recall@10', float('nan')):.3f} "
        f"MRR={agg.get('MRR', float('nan')):.3f}"
    )
    for r in reasons:
        print(f"  - {r}")

    # A mock/wiring run's numbers are not a quality baseline — informational, never gating.
    if results.get("embedder", {}).get("provider") == "mock":
        print("eval-gate: mock run - informational only, not gating.")
        return 0
    if passed:
        print("eval-gate: PASS")
        return 0
    print("eval-gate: FAIL - retrieval quality gate not met.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
