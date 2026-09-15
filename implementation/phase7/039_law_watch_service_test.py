from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("phase76_watch", HERE / "038_law_watch_service.py")
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
    def __init__(self, conn): self.conn = conn
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.conn.calls.append((sql, params))

class FakeConnection:
    def __init__(self): self.calls = []
    def cursor(self): return FakeCursor(self)


def watch_row(baseline: str | None) -> dict:
    return {
        "watch_id": "a" * 32,
        "theme_id": None,
        "law_id": "129AC0000000089",
        "baseline_revision_id": baseline,
        "baseline_ingestion_run_id": "run-base" if baseline else None,
        "enabled": True,
    }


class ClassifierTest(unittest.TestCase):
    def test_initializes_without_baseline(self):
        self.assertEqual(
            WATCH.classify_watch_evaluation(None, Temporal("resolved", "rev-1")),
            "initialized",
        )

    def test_no_change_for_same_revision(self):
        self.assertEqual(
            WATCH.classify_watch_evaluation("rev-1", Temporal("resolved", "rev-1")),
            "no-change",
        )

    def test_effective_change_for_new_revision(self):
        self.assertEqual(
            WATCH.classify_watch_evaluation("rev-1", Temporal("resolved", "rev-2")),
            "effective-change",
        )

    def test_temporal_blocking_state_is_preserved(self):
        for state in ("ambiguous", "unresolved", "not-found"):
            with self.subTest(state=state):
                self.assertEqual(
                    WATCH.classify_watch_evaluation("rev-1", Temporal(state)),
                    state,
                )


class EvaluationTest(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()
        self.today = date(2026, 9, 15)

    def test_initialization_sets_baseline_without_event(self):
        temporal = Temporal("resolved", "rev-1")
        resolver = lambda conn, law_id, when: temporal
        with patch.object(WATCH, "get_watch", return_value=watch_row(None)), \
             patch.object(WATCH, "_latest_successful_ingestion_run", return_value="run-1"):
            result = WATCH.evaluate_watch(
                self.conn, "a" * 32, evaluation_date=self.today, resolver=resolver
            )
        self.assertEqual(result["state"], "initialized")
        self.assertEqual(result["baseline_revision_id"], "rev-1")
        self.assertIsNone(result["event_id"])
        self.assertEqual(len(self.conn.calls), 1)
        self.assertIn("baseline_ingestion_run_id", self.conn.calls[0][0])

    def test_blocked_temporal_does_not_write(self):
        temporal = Temporal("ambiguous")
        resolver = lambda conn, law_id, when: temporal
        with patch.object(WATCH, "get_watch", return_value=watch_row("rev-1")):
            result = WATCH.evaluate_watch(
                self.conn, "a" * 32, evaluation_date=self.today, resolver=resolver
            )
        self.assertEqual(result["state"], "ambiguous")
        self.assertEqual(self.conn.calls, [])

    def test_no_change_updates_only_evaluation_timestamp(self):
        temporal = Temporal("resolved", "rev-1")
        resolver = lambda conn, law_id, when: temporal
        with patch.object(WATCH, "get_watch", return_value=watch_row("rev-1")):
            result = WATCH.evaluate_watch(
                self.conn, "a" * 32, evaluation_date=self.today, resolver=resolver
            )
        self.assertEqual(result["state"], "no-change")
        self.assertEqual(len(self.conn.calls), 1)
        self.assertIn("last_evaluated_at", self.conn.calls[0][0])
        self.assertNotIn("baseline_ingestion_run_id =", self.conn.calls[0][0])

    def test_effective_change_persists_event_then_advances_revision(self):
        temporal = Temporal("resolved", "rev-2")
        resolver = lambda conn, law_id, when: temporal
        with patch.object(WATCH, "get_watch", return_value=watch_row("rev-1")), \
             patch.object(WATCH, "_revision_source_run", return_value="run-2"), \
             patch.object(WATCH, "_insert_effective_event", return_value="e" * 32) as insert_event:
            result = WATCH.evaluate_watch(
                self.conn, "a" * 32, evaluation_date=self.today, resolver=resolver
            )
        self.assertEqual(result["state"], "effective-change")
        self.assertEqual(result["baseline_revision_id"], "rev-2")
        self.assertEqual(result["event_id"], "e" * 32)
        insert_event.assert_called_once()
        self.assertEqual(len(self.conn.calls), 1)
        self.assertIn("baseline_revision_id", self.conn.calls[0][0])

    def test_non_string_hex_id_is_rejected(self):
        with self.assertRaises(ValueError):
            WATCH._validate_hex32(123, field="theme_id")

    def test_invalid_watch_id_is_rejected(self):
        with self.assertRaises(ValueError):
            WATCH.get_watch(self.conn, "bad")


if __name__ == "__main__":
    unittest.main(verbosity=2)
