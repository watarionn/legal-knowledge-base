from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("phase75_daily", HERE / "029_daily_use_service.py")
assert SPEC and SPEC.loader
DAILY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DAILY
SPEC.loader.exec_module(DAILY)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 1
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.conn.calls.append((sql, params))
    def fetchone(self):
        return self.conn.fetchone_values.pop(0) if self.conn.fetchone_values else None
    def fetchall(self): return []


class FakeConnection:
    def __init__(self, fetchone_values=None):
        self.calls = []
        self.fetchone_values = list(fetchone_values or [])
    def cursor(self): return FakeCursor(self)

class ValidationTest(unittest.TestCase):
    def test_law_id_validation(self):
        self.assertEqual(DAILY._validate_law_id("129AC0000000089"), "129AC0000000089")
        with self.assertRaises(ValueError): DAILY._validate_law_id("civil-code")

    def test_limit_validation(self):
        self.assertEqual(DAILY._validate_limit(12), 12)
        with self.assertRaises(ValueError): DAILY._validate_limit(0)
        with self.assertRaises(ValueError): DAILY._validate_limit(101)

    def test_theme_rejects_empty_title_before_db(self):
        with self.assertRaises(ValueError):
            DAILY.create_saved_theme(FakeConnection(), title="", question="民法を確認", law_id=None)


class PersistenceContractTest(unittest.TestCase):
    def test_record_query_writes_history_and_recent_for_resolved_law(self):
        conn = FakeConnection()
        DAILY.record_query_activity(conn, {
            "query_id": "a" * 32,
            "question": "民法の第90条を確認したい",
            "requested_as_of_date": "2026-09-11",
            "effective_as_of_date": "2026-09-11",
            "status": "evidence-only",
            "law_resolution": {"selected_law_id": "129AC0000000089", "selected_law_title": "民法"},
            "temporal_resolution": {"status": "resolved"},
        })
        self.assertEqual(len(conn.calls), 2)
        self.assertIn("application_search_history", conn.calls[0][0])
        self.assertIn("application_recent_law", conn.calls[1][0])
    def test_record_query_without_resolved_law_writes_history_only(self):
        conn = FakeConnection()
        DAILY.record_query_activity(conn, {
            "query_id": "b" * 32,
            "question": "よく分からない質問",
            "requested_as_of_date": None,
            "effective_as_of_date": "2026-09-11",
            "status": "law-candidates",
            "law_resolution": {"selected_law_id": None, "selected_law_title": None},
            "temporal_resolution": None,
        })
        self.assertEqual(len(conn.calls), 1)
        self.assertIn("application_search_history", conn.calls[0][0])

    def test_application_state_ready_requires_all_relations(self):
        ready = FakeConnection(fetchone_values=[("x",), ("x",), ("x",), ("x",)])
        self.assertTrue(DAILY.application_state_ready(ready))
        missing = FakeConnection(fetchone_values=[("x",), (None,)])
        self.assertFalse(DAILY.application_state_ready(missing))

    def test_invalid_query_id_is_rejected(self):
        with self.assertRaises(ValueError):
            DAILY.record_query_activity(FakeConnection(), {
                "query_id": "bad", "question": "q", "effective_as_of_date": "2026-09-11",
                "status": "ok", "law_resolution": {}, "temporal_resolution": None,
            })


if __name__ == "__main__":
    unittest.main(verbosity=2)
