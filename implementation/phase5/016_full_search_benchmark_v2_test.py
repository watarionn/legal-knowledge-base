from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

PHASE5_DIR = Path(__file__).resolve().parent


def _load():
    path = PHASE5_DIR / "013_full_search_benchmark_v2.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_full_search_benchmark_v2_test_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BENCH = _load()


class FullSearchBenchmarkV2Test(unittest.TestCase):
    def test_delta(self):
        self.assertEqual(
            BENCH._delta({"a": 10, "b": 7}, {"a": 3, "b": 9}),
            {"a": 7, "b": -2},
        )

    def test_run_rejects_invalid_repeats_before_connect(self):
        original = BENCH.BASE._connect
        BENCH.BASE._connect = lambda _: self.fail("database connection must not be attempted")
        try:
            with self.assertRaisesRegex(ValueError, "repeats"):
                BENCH.run("postgresql://unused", ("法律",), 0)
        finally:
            BENCH.BASE._connect = original

    def test_run_rejects_empty_queries_before_connect(self):
        original = BENCH.BASE._connect
        BENCH.BASE._connect = lambda _: self.fail("database connection must not be attempted")
        try:
            with self.assertRaisesRegex(ValueError, "query"):
                BENCH.run("postgresql://unused", (), 1)
        finally:
            BENCH.BASE._connect = original

    def test_default_queries_match_base_runner(self):
        self.assertEqual(BENCH.DEFAULT_QUERIES, BENCH.BASE.DEFAULT_QUERIES)


if __name__ == "__main__":
    unittest.main()
