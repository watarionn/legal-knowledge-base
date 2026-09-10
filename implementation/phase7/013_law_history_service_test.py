from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent


def _load():
    path = HERE / "012_law_history_service.py"
    spec = importlib.util.spec_from_file_location("phase7_history_test_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SERVICE = _load()


class ParseDateTest(unittest.TestCase):
    def test_explicit_iso_date(self):
        self.assertEqual(
            SERVICE.parse_as_of_date("2024-04-01"), date(2024, 4, 1)
        )

    def test_default_date(self):
        value = date(2026, 9, 10)
        self.assertEqual(SERVICE.parse_as_of_date(None, default_date=value), value)

    def test_invalid_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "valid calendar date"):
            SERVICE.parse_as_of_date("2026-02-30")

class HistoryProjectionTest(unittest.TestCase):
    def test_selected_and_candidate_flags_are_preserved(self):
        candidate = SimpleNamespace(law_revision_id="r1")
        temporal = SimpleNamespace(
            candidates=(candidate,),
            selected_revision_id="r1",
            as_of_date=date(2026, 9, 10),
            to_dict=lambda: {"status": "resolved", "selected_revision_id": "r1"},
        )
        rows = [
            {
                "law_revision_id": "r1",
                "revision_sequence": 2,
                "valid_from": date(2026, 1, 1),
                "valid_to_exclusive": None,
                "succeeded_document_count": 1,
                "document_pk": 10,
                "source_xml_sha256": "a" * 64,
            },
            {
                "law_revision_id": "r0",
                "revision_sequence": 1,
                "valid_from": date(2025, 1, 1),
                "valid_to_exclusive": date(2026, 1, 1),
                "succeeded_document_count": 0,
                "document_pk": None,
                "source_xml_sha256": None,
            },
        ]
        value = SERVICE.build_history_response(
            {"law_id": "129AC0000000089", "law_title": "民法"}, rows, temporal
        )
        self.assertEqual(value["revision_count"], 2)
        self.assertTrue(value["revisions"][0]["selected_for_as_of"])
        self.assertTrue(value["revisions"][0]["candidate_for_as_of"])
        self.assertEqual(value["revisions"][0]["content_status"], "available")
        self.assertEqual(value["revisions"][1]["content_status"], "missing")
        self.assertEqual(value["source_truth"], "phase3-phase4")

    def test_multiple_documents_are_not_presented_as_available(self):
        self.assertEqual(SERVICE._content_status(2), "multiple")


if __name__ == "__main__":
    unittest.main()
