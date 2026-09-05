#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("007_parallel_full_bootstrap.py")
spec = importlib.util.spec_from_file_location("phase3_resumable", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class StorageNormalizationTests(unittest.TestCase):
    def test_blank_amendment_law_id_becomes_none(self):
        source = {
            "law_revision_id": "321CONSTITUTION_19470503_000000000000000",
            "amendment_law_id": "",
            "law_title": "日本国憲法",
        }
        normalized = module.normalize_revision_for_storage(source)
        self.assertIsNone(normalized["amendment_law_id"])
        self.assertEqual(source["amendment_law_id"], "")

    def test_whitespace_amendment_law_id_becomes_none(self):
        source = {"amendment_law_id": "   "}
        normalized = module.normalize_revision_for_storage(source)
        self.assertIsNone(normalized["amendment_law_id"])

    def test_nonblank_amendment_law_id_is_preserved(self):
        source = {"amendment_law_id": "506AC0000000046"}
        normalized = module.normalize_revision_for_storage(source)
        self.assertEqual(normalized["amendment_law_id"], "506AC0000000046")


class ResumePlanningTests(unittest.TestCase):
    def test_completed_laws_are_skipped(self):
        law_ids = ["A", "B", "C", "D"]
        completed = {"B", "D"}
        self.assertEqual(module.pending_law_ids(law_ids, completed), ["A", "C"])

    def test_empty_checkpoint_processes_all(self):
        law_ids = ["A", "B"]
        self.assertEqual(module.pending_law_ids(law_ids, set()), law_ids)


if __name__ == "__main__":
    unittest.main()
