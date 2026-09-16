from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase76b_watch", HERE / "038_law_watch_service.py"
)
assert SPEC and SPEC.loader
WATCH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = WATCH
SPEC.loader.exec_module(WATCH)


class Temporal:
    def __init__(self, status: str, selected_revision_id: str | None = None):
        self.status = status
        self.selected_revision_id = selected_revision_id

    def to_dict(self):
        return {"status": self.status, "selected_revision_id": self.selected_revision_id}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.conn.calls.append((sql, params))


class FakeConnection:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return FakeCursor(self)


def watch_row(revision: str = "rev-1", run_id: str = "run-base") -> dict:
    return {
        "watch_id": "a" * 32,
        "theme_id": None,
        "law_id": "129AC0000000089",
        "baseline_revision_id": revision,
        "baseline_ingestion_run_id": run_id,
        "enabled": True,
    }


def latest_run(run_id: str = "run-new") -> dict:
    return {
        "ingestion_run_id": run_id,
        "started_at": "2026-09-16T00:00:00+00:00",
        "completed_at": "2026-09-16T00:01:00+00:00",
        "result_status": "succeeded",
        "input_manifest_sha256": "b" * 64,
    }


class ChangeEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()
        self.today = date(2026, 9, 16)
        self.scheduled = [{
            "event_type": "scheduled-change",
            "law_revision_id": "rev-future",
            "scheduled_enforcement_date": "2027-04-01",
            "legal_deadline": False,
        }]

    def test_scheduled_change_is_not_a_legal_deadline(self):
        row = {
            "law_revision_id": "rev-future",
            "revision_sequence": 2,
            "law_title": "Test Law",
            "revision_id_effective_date": self.today,
            "revision_date_kind": "amendment-enforcement",
            "amendment_promulgate_date": self.today,
            "amendment_enforcement_date": None,
            "amendment_scheduled_enforcement_date": date(2027, 4, 1),
            "amendment_law_id": None,
            "amendment_law_num": None,
            "amendment_law_title": None,
            "first_seen_run_id": "run-1",
            "started_at": None,
            "completed_at": None,
            "result_status": "succeeded",
            "input_manifest_sha256": None,
        }
        item = WATCH._scheduled_change_dict(row)
        self.assertEqual(item["event_type"], "scheduled-change")
        self.assertEqual(item["scheduled_enforcement_date"], "2027-04-01")
        self.assertFalse(item["legal_deadline"])
        self.assertEqual(item["source_truth"], "phase3-law-revision")

    def test_observed_change_can_exist_without_effective_change(self):
        temporal = Temporal("resolved", "rev-1")
        observed_row = {
            "law_revision_id": "rev-future",
            "first_seen_run_id": "run-new",
        }
        observed_event = {
            "event_id": "o" * 32,
            "event_type": "observed-change",
            "to_revision_id": "rev-future",
        }
        with patch.object(WATCH, "get_watch", return_value=watch_row()), \
             patch.object(WATCH, "_future_scheduled_changes", return_value=self.scheduled), \
             patch.object(WATCH, "_latest_successful_ingestion_run_info", return_value=latest_run()), \
             patch.object(WATCH, "_observed_revisions_since", return_value=[observed_row]), \
             patch.object(WATCH, "_insert_change_event", return_value="o" * 32) as insert_event, \
             patch.object(WATCH, "get_watch_event", return_value=observed_event):
            result = WATCH.evaluate_watch(
                self.conn,
                "a" * 32,
                evaluation_date=self.today,
                resolver=lambda conn, law_id, when: temporal,
            )
        self.assertEqual(result["state"], "no-change")
        self.assertEqual(result["baseline_revision_id"], "rev-1")
        self.assertEqual(result["baseline_ingestion_run_id"], "run-new")
        self.assertEqual(result["change_evidence"]["observed_changes"], [observed_event])
        self.assertIsNone(result["change_evidence"]["effective_change"])
        self.assertEqual(result["change_evidence"]["scheduled_changes"], self.scheduled)
        insert_event.assert_called_once_with(
            self.conn,
            watch_id="a" * 32,
            event_type="observed-change",
            from_revision_id=None,
            to_revision_id="rev-future",
            source_ingestion_run_id="run-new",
            temporal_status="resolved",
        )

    def test_observed_and_effective_changes_remain_separate(self):
        temporal = Temporal("resolved", "rev-2")
        observed_row = {"law_revision_id": "rev-2", "first_seen_run_id": "run-new"}
        observed_event = {"event_id": "o" * 32, "event_type": "observed-change"}
        effective_event = {"event_id": "e" * 32, "event_type": "effective-change"}
        with patch.object(WATCH, "get_watch", return_value=watch_row()), \
             patch.object(WATCH, "_future_scheduled_changes", return_value=[]), \
             patch.object(WATCH, "_latest_successful_ingestion_run_info", return_value=latest_run()), \
             patch.object(WATCH, "_observed_revisions_since", return_value=[observed_row]), \
             patch.object(WATCH, "_insert_change_event", return_value="o" * 32), \
             patch.object(WATCH, "_revision_source_run", return_value="run-new"), \
             patch.object(WATCH, "_insert_effective_event", return_value="e" * 32), \
             patch.object(WATCH, "get_watch_event", side_effect=[observed_event, effective_event]):
            result = WATCH.evaluate_watch(
                self.conn,
                "a" * 32,
                evaluation_date=self.today,
                resolver=lambda conn, law_id, when: temporal,
            )
        self.assertEqual(result["state"], "effective-change")
        self.assertEqual(result["event_id"], "e" * 32)
        self.assertEqual(result["change_evidence"]["observed_changes"], [observed_event])
        self.assertEqual(result["change_evidence"]["effective_change"], effective_event)
        self.assertEqual(result["baseline_revision_id"], "rev-2")
        self.assertEqual(result["baseline_ingestion_run_id"], "run-new")

    def test_blocked_temporal_keeps_baselines_but_returns_scheduled_source_data(self):
        temporal = Temporal("ambiguous")
        with patch.object(WATCH, "get_watch", return_value=watch_row()), \
             patch.object(WATCH, "_future_scheduled_changes", return_value=self.scheduled), \
             patch.object(WATCH, "_latest_successful_ingestion_run_info") as latest_info, \
             patch.object(WATCH, "_insert_change_event") as insert_event:
            result = WATCH.evaluate_watch(
                self.conn,
                "a" * 32,
                evaluation_date=self.today,
                resolver=lambda conn, law_id, when: temporal,
            )
        self.assertEqual(result["state"], "ambiguous")
        self.assertEqual(result["baseline_revision_id"], "rev-1")
        self.assertEqual(result["baseline_ingestion_run_id"], "run-base")
        self.assertEqual(result["change_evidence"]["scheduled_changes"], self.scheduled)
        latest_info.assert_not_called()
        insert_event.assert_not_called()
        self.assertEqual(self.conn.calls, [])

    def test_event_limit_is_validated_before_database_access(self):
        with self.assertRaises(ValueError):
            WATCH.list_watch_events(self.conn, "a" * 32, limit=0)
        with self.assertRaises(ValueError):
            WATCH.list_watch_events(self.conn, "a" * 32, limit=True)
        self.assertEqual(self.conn.calls, [])

    def test_event_projection_keeps_ingestion_and_revision_provenance(self):
        row = (
            "e" * 32, "a" * 32, "observed-change", None, "rev-2",
            None, None, "run-2", "resolved", None,
            None, None, "succeeded", "c" * 64,
            None, None, "Test Law", self.today, "amendment-enforcement",
            self.today, None, date(2027, 4, 1), None, "Law No. 1",
            "Amendment Law", "run-2",
            "129AC0000000089", None, self.today,
        )
        item = WATCH._event_dict(row)
        self.assertEqual(item["event_type"], "observed-change")
        self.assertEqual(item["source_ingestion_run"]["ingestion_run_id"], "run-2")
        self.assertEqual(item["source_ingestion_run"]["input_manifest_sha256"], "c" * 64)
        self.assertEqual(item["to_revision"]["law_revision_id"], "rev-2")
        self.assertEqual(item["to_revision"]["amendment_scheduled_enforcement_date"], "2027-04-01")
        self.assertEqual(item["law_revision_truth"], "phase3-law-revision")
        self.assertIsNone(item["navigation"]["compare"])
        self.assertEqual(
            item["navigation"]["confirmed_related_materials"]["relation_status"],
            "confirmed",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
