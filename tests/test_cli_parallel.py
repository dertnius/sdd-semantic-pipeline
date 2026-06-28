"""Tests for the CLI parallel-map helper (the --jobs determinism contract).

Pure and model-free: validates that parallel execution preserves input order and
captures per-item errors, so a report built from the results is identical for any
--jobs value.
"""

from __future__ import annotations

from sdd_pipeline.cli import _parallel_compute


def _double(x):
    return x * 2


class TestParallelCompute:
    def test_serial_preserves_order(self):
        items = list(range(20))
        out = _parallel_compute(items, _double, jobs=1)
        assert [it for it, _, _ in out] == items
        assert [res for _, res, _ in out] == [x * 2 for x in items]
        assert all(exc is None for _, _, exc in out)

    def test_parallel_preserves_input_order(self):
        items = list(range(50))
        out = _parallel_compute(items, _double, jobs=8)
        # Order must match the input even though work ran concurrently.
        assert [it for it, _, _ in out] == items
        assert [res for _, res, _ in out] == [x * 2 for x in items]

    def test_jobs_zero_uses_all_cpus_and_keeps_order(self):
        items = list(range(10))
        out = _parallel_compute(items, _double, jobs=0)
        assert [it for it, _, _ in out] == items

    def test_serial_and_parallel_agree(self):
        items = [f"f{i}.md" for i in range(30)]
        serial = _parallel_compute(items, len, jobs=1)
        parallel = _parallel_compute(items, len, jobs=6)
        assert serial == parallel

    def test_exception_is_captured_per_item_not_raised(self):
        def boom(x):
            if x == 3:
                raise ValueError("bad item")
            return x

        out = _parallel_compute(list(range(6)), boom, jobs=4)
        assert [it for it, _, _ in out] == list(range(6))
        # Item 3 carries the exception; all others succeed.
        errs = {it: exc for it, _, exc in out if exc is not None}
        assert set(errs) == {3}
        assert isinstance(errs[3], ValueError)

    def test_single_item_runs_inline(self):
        assert _parallel_compute([42], _double, jobs=8) == [(42, 84, None)]

    def test_empty_items(self):
        assert _parallel_compute([], _double, jobs=4) == []
