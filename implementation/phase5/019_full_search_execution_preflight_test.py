from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

PHASE5_DIR = Path(__file__).resolve().parent


def _load():
    path = PHASE5_DIR / "017_full_search_execution_preflight.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_execution_preflight", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PREFLIGHT = _load()


class FullSearchExecutionPreflightTest(unittest.TestCase):
    def _run_case(self, *, documents: int, nodes: int, free_bytes: int):
        original_validate = PREFLIGHT.validate_archives
        original_inspect = PREFLIGHT.inspect_database
        original_disk_usage = PREFLIGHT.shutil.disk_usage
        PREFLIGHT.validate_archives = lambda _: (4, 330651407)
        PREFLIGHT.inspect_database = lambda _: {
            "postgres_version": "PostgreSQL 16.15",
            "postgres_version_num": 160015,
            "law_revision_count": 53711,
            "law_document_count": documents,
            "provision_node_count": nodes,
        }
        PREFLIGHT.shutil.disk_usage = lambda _: SimpleNamespace(free=free_bytes)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                return PREFLIGHT.evaluate(Path(tmp), Path(tmp), "postgresql://unused")
        finally:
            PREFLIGHT.validate_archives = original_validate
            PREFLIGHT.inspect_database = original_inspect
            PREFLIGHT.shutil.disk_usage = original_disk_usage

    def test_full_phase4_dataset_selects_benchmark_only(self):
        result = self._run_case(
            documents=PREFLIGHT.EXPECTED_PHASE4_DOCUMENTS,
            nodes=PREFLIGHT.EXPECTED_PHASE4_NODES,
            free_bytes=PREFLIGHT.MIN_FREE_BYTES_BENCHMARK_ONLY,
        )
        self.assertTrue(result.phase4_full_dataset_present)
        self.assertEqual(result.recommended_mode, "benchmark-only")
        self.assertTrue(result.ready)

    def test_missing_phase4_dataset_selects_full_rebuild(self):
        result = self._run_case(
            documents=0,
            nodes=0,
            free_bytes=PREFLIGHT.MIN_FREE_BYTES_FULL_REBUILD,
        )
        self.assertFalse(result.phase4_full_dataset_present)
        self.assertEqual(result.recommended_mode, "full-rebuild")
        self.assertTrue(result.ready)

    def test_insufficient_disk_blocks_execution(self):
        result = self._run_case(
            documents=0,
            nodes=0,
            free_bytes=PREFLIGHT.MIN_FREE_BYTES_FULL_REBUILD - 1,
        )
        self.assertFalse(result.disk_ready)
        self.assertFalse(result.ready)


if __name__ == "__main__":
    unittest.main()
