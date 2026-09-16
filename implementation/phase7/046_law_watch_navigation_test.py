from datetime import date, datetime, timezone
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase76c_watch", HERE / "038_law_watch_service.py"
)
assert SPEC and SPEC.loader
WATCH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = WATCH
SPEC.loader.exec_module(WATCH)

LAW_ID = "129AC0000000089"
EVENT_ID = "e" * 32
WATCH_ID = "a" * 32


def event_row(event_type: str = "effective-change", acknowledged_at=None):
    return (
        EVENT_ID, WATCH_ID, event_type, "rev-1" if event_type == "effective-change" else None,
        "rev-2", datetime(2026, 9, 16, tzinfo=timezone.utc), None,
        "run-2", "resolved", acknowledged_at,
        datetime(2026, 9, 16, tzinfo=timezone.utc),
        datetime(2026, 9, 16, 0, 1, tzinfo=timezone.utc),
        "succeeded", "c" * 64,
        date(2026, 1, 1), "amendment-enforcement",
        "Test Law", date(2026, 9, 1), "amendment-enforcement",
        date(2026, 6, 1), date(2026, 9, 1), None,
        None, "Law No. 1", "Amendment Law", "run-2",
        LAW_ID, date(2026, 1, 1), date(2026, 9, 1),
    )


class AckCursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = None

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def execute(self, sql, params=None):
        self.conn.calls.append((sql, params))
        self.result = (EVENT_ID,) if self.conn.found else None

    def fetchone(self):
        return self.result


class AckConnection:
    def __init__(self, found=True):
        self.found = found
        self.calls = []

    def cursor(self): return AckCursor(self)


class NavigationTest(unittest.TestCase):
    def test_effective_change_navigation_targets_existing_phase7_routes(self):
        item = WATCH._event_dict(event_row())
        nav = item["navigation"]
        self.assertEqual(item["law_id"], LAW_ID)
        self.assertFalse(item["acknowledged"])
        self.assertEqual(nav["history"]["as_of_date"], "2026-09-01")
        self.assertIn(f"/api/v1/laws/{LAW_ID}/history?", nav["history"]["path"])
        self.assertEqual(nav["compare"]["from_date"], "2026-01-01")
        self.assertEqual(nav["compare"]["to_date"], "2026-09-01")
        self.assertIn("from_date=2026-01-01", nav["compare"]["path"])
        self.assertIn("to_date=2026-09-01", nav["compare"]["path"])
        related = nav["confirmed_related_materials"]
        self.assertEqual(related["relation_status"], "confirmed")
        self.assertNotIn("include_nonconfirmed", related["path"])

    def test_observed_change_has_no_two_revision_compare(self):
        item = WATCH._event_dict(event_row("observed-change"))
        self.assertIsNone(item["navigation"]["compare"])
        self.assertIsNotNone(item["navigation"]["history"])
        self.assertIsNotNone(item["navigation"]["confirmed_related_materials"])

    def test_acknowledge_is_application_state_only_and_reconstructs_event(self):
        conn = AckConnection(found=True)
        acknowledged = dict(WATCH._event_dict(event_row()))
        acknowledged["acknowledged"] = True
        with patch.object(WATCH, "get_watch_event", return_value=acknowledged):
            result = WATCH.acknowledge_watch_event(conn, EVENT_ID)
        self.assertTrue(result["acknowledged"])
        self.assertEqual(len(conn.calls), 1)
        self.assertIn("COALESCE(e.acknowledged_at, now())", conn.calls[0][0])

    def test_acknowledge_missing_event_returns_none(self):
        conn = AckConnection(found=False)
        with patch.object(WATCH, "get_watch_event") as get_event:
            result = WATCH.acknowledge_watch_event(conn, EVENT_ID)
        self.assertIsNone(result)
        get_event.assert_not_called()

    def test_acknowledge_rejects_invalid_event_id_before_database_access(self):
        conn = AckConnection(found=True)
        with self.assertRaises(ValueError):
            WATCH.acknowledge_watch_event(conn, "bad")
        self.assertEqual(conn.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
