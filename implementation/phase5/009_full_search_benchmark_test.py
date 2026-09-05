from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

PHASE5_DIR = Path(__file__).resolve().parent


def _load():
    path = PHASE5_DIR / "008_full_search_benchmark.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_full_search_benchmark", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BENCH = _load()


class FullSearchBenchmarkTest(unittest.TestCase):
    def test_latency_stats(self):
        stats = BENCH._latency_stats([10.0, 20.0, 30.0, 40.0, 50.0])
        self.assertEqual(stats["min_ms"], 10.0)
        self.assertEqual(stats["median_ms"], 30.0)
        self.assertEqual(stats["p95_ms"], 50.0)
        self.assertEqual(stats["max_ms"], 50.0)
        self.assertEqual(stats["mean_ms"], 30.0)

    def test_latency_stats_rejects_empty_samples(self):
        with self.assertRaises(ValueError):
            BENCH._latency_stats([])

    def test_run_rejects_zero_repeats_before_connect(self):
        original = BENCH._connect
        BENCH._connect = lambda _: self.fail("database connection must not be attempted")
        try:
            with self.assertRaisesRegex(ValueError, "repeats"):
                BENCH.run("postgresql://unused", ("法律",), 0)
        finally:
            BENCH._connect = original

    def test_run_rejects_empty_queries_before_connect(self):
        original = BENCH._connect
        BENCH._connect = lambda _: self.fail("database connection must not be attempted")
        try:
            with self.assertRaisesRegex(ValueError, "query"):
                BENCH.run("postgresql://unused", (), 1)
        finally:
            BENCH._connect = original

    def test_default_queries_are_nonempty_unique_strings(self):
        self.assertTrue(BENCH.DEFAULT_QUERIES)
        self.assertEqual(len(BENCH.DEFAULT_QUERIES), len(set(BENCH.DEFAULT_QUERIES)))
        self.assertTrue(all(isinstance(q, str) and q for q in BENCH.DEFAULT_QUERIES))


if __name__ == "__main__":
    unittest.main()
