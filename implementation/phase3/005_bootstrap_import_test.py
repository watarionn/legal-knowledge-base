#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
import sys
from datetime import date
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("004_bootstrap_import.py")
spec = importlib.util.spec_from_file_location("phase3_bootstrap", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class RevisionIdTests(unittest.TestCase):
    def test_parse_revision_id(self):
        parsed = module.parse_revision_id("405AC0000000088_20260401_506AC0000000046")
        self.assertEqual(parsed.law_id, "405AC0000000088")
        self.assertEqual(parsed.effective_date, date(2026, 4, 1))
        self.assertEqual(parsed.amending_law_id, "506AC0000000046")

    def test_invalid_revision_id(self):
        with self.assertRaises(ValueError):
            module.parse_revision_id("not-a-revision-id")


class TemporalDerivationTests(unittest.TestCase):
    def test_nonbaseline_matching_api_date(self):
        parsed = module.parse_revision_id("405AC0000000088_20260401_506AC0000000046")
        result = module.derive_temporal({"amendment_enforcement_date": "2026-04-01"}, parsed)
        self.assertEqual(result.revision_date_kind, "amendment-enforcement")
        self.assertEqual(result.valid_from, date(2026, 4, 1))
        self.assertEqual(result.temporal_resolution_quality, "confirmed-api")
        self.assertFalse(result.issues)

    def test_nonbaseline_missing_api_date_uses_revision_id(self):
        parsed = module.parse_revision_id("405AC0000000088_20260401_506AC0000000046")
        result = module.derive_temporal({}, parsed)
        self.assertEqual(result.valid_from, date(2026, 4, 1))
        self.assertEqual(result.temporal_resolution_quality, "confirmed-revision-id")

    def test_date_conflict_does_not_choose_winner(self):
        parsed = module.parse_revision_id("405AC0000000088_20260401_506AC0000000046")
        result = module.derive_temporal({"amendment_enforcement_date": "2026-04-02"}, parsed)
        self.assertIsNone(result.valid_from)
        self.assertEqual(result.temporal_resolution_quality, "ambiguous")
        self.assertEqual(result.issues[0]["issue_code"], "REVISION_EFFECTIVE_DATE_MISMATCH")

    def test_baseline_suffix_remains_unknown(self):
        parsed = module.parse_revision_id("405AC0000000088_19931112_000000000000000")
        result = module.derive_temporal({"amendment_enforcement_date": None}, parsed)
        self.assertEqual(result.revision_date_kind, "unknown")
        self.assertEqual(result.valid_from, date(1993, 11, 12))
        self.assertEqual(result.temporal_resolution_quality, "ambiguous")


class IntervalTests(unittest.TestCase):
    def test_same_day_revisions_share_next_strictly_greater_boundary(self):
        rows = [
            {"law_revision_id": "A", "valid_from": date(2020, 1, 1), "temporal_resolution_quality": "confirmed-api"},
            {"law_revision_id": "B", "valid_from": date(2020, 1, 1), "temporal_resolution_quality": "confirmed-api"},
            {"law_revision_id": "C", "valid_from": date(2021, 1, 1), "temporal_resolution_quality": "confirmed-api"},
        ]
        module.derive_intervals(rows)
        by_id = {row["law_revision_id"]: row for row in rows}
        self.assertEqual(by_id["A"]["valid_to_exclusive"], date(2021, 1, 1))
        self.assertEqual(by_id["B"]["valid_to_exclusive"], date(2021, 1, 1))
        self.assertEqual(by_id["A"]["temporal_resolution_quality"], "ambiguous")
        self.assertEqual(by_id["B"]["temporal_resolution_quality"], "ambiguous")
        self.assertEqual(by_id["C"]["valid_to_exclusive"], None)
        self.assertEqual(
            [row["law_revision_id"] for row in sorted(rows, key=lambda row: row["revision_sequence"])],
            ["A", "B", "C"],
        )

    def test_null_valid_from_sorts_last(self):
        rows = [
            {"law_revision_id": "B", "valid_from": None, "temporal_resolution_quality": "ambiguous"},
            {"law_revision_id": "A", "valid_from": date(2020, 1, 1), "temporal_resolution_quality": "confirmed-api"},
        ]
        module.derive_intervals(rows)
        by_id = {row["law_revision_id"]: row for row in rows}
        self.assertEqual(by_id["A"]["revision_sequence"], 1)
        self.assertEqual(by_id["B"]["revision_sequence"], 2)


if __name__ == "__main__":
    unittest.main()
