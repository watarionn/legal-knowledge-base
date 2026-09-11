from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
SERVER_PATH = HERE / "003_web_server.py"
spec = importlib.util.spec_from_file_location("phase75_http_server_tested", SERVER_PATH)
assert spec and spec.loader
SERVER = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = SERVER
spec.loader.exec_module(SERVER)


class FakeCursor:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.last_sql = sql


class FakeConnection:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return FakeCursor()
    def close(self): pass


class RouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = []
        fake_psycopg = types.SimpleNamespace(connect=lambda url: FakeConnection())
        cls.old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = fake_psycopg

        cls.old_ready = SERVER.DAILY.application_state_ready
        cls.old_state = SERVER.DAILY.get_daily_state
        cls.old_add = SERVER.DAILY.add_favorite
        cls.old_remove = SERVER.DAILY.remove_favorite
        cls.old_create = SERVER.DAILY.create_saved_theme
        cls.old_delete = SERVER.DAILY.delete_saved_theme
        cls.old_clear_history = SERVER.DAILY.clear_search_history
        cls.old_clear_recent = SERVER.DAILY.clear_recent_laws
        cls.old_record = SERVER.DAILY.record_query_activity

        SERVER.DAILY.application_state_ready = lambda conn: True
        SERVER.DAILY.get_daily_state = lambda conn, **kw: {
            "api_version": "1", "favorites": [], "recent_laws": [],
            "search_history": [], "saved_themes": [],
            "source_truth": "phase7-application-state",
        }
        SERVER.DAILY.add_favorite = lambda conn, law_id: {
            "law_id": law_id, "law_title": "民法", "favorite": True,
        }
        SERVER.DAILY.remove_favorite = lambda conn, law_id: True
        SERVER.DAILY.create_saved_theme = lambda conn, **kw: {
            "theme_id": "d" * 32, "title": kw["title"],
            "question": kw["question"], "law_id": kw.get("law_id"),
            "as_of_date": kw.get("as_of_date").isoformat() if kw.get("as_of_date") else None,
        }
        SERVER.DAILY.delete_saved_theme = lambda conn, theme_id: True
        SERVER.DAILY.clear_search_history = lambda conn: 3
        SERVER.DAILY.clear_recent_laws = lambda conn: 2
        cls.activity_calls = []
        def failing_record(conn, response):
            cls.activity_calls.append(response['query_id'])
            raise RuntimeError('simulated application-state failure')
        SERVER.DAILY.record_query_activity = failing_record

        state = SERVER.AppState()
        state.database_url = "mock://database"
        state.query_service = types.SimpleNamespace(query=lambda conn, payload: {
            'api_version': '1', 'query_id': 'c' * 32,
            'question': payload.get('question', ''),
            'requested_as_of_date': payload.get('as_of_date'),
            'effective_as_of_date': payload.get('as_of_date') or '2026-09-11',
            'status': 'evidence-only',
            'law_resolution': {'status': 'resolved', 'selected_law_id': '129AC0000000089', 'selected_law_title': '民法'},
            'temporal_resolution': {'status': 'resolved'},
            'evidence': [], 'answer': {'status': 'evidence-only'},
        })
        cls.server = SERVER.LegalKbHttpServer(("127.0.0.1", 0), SERVER.Handler, state)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        SERVER.DAILY.application_state_ready = cls.old_ready
        SERVER.DAILY.get_daily_state = cls.old_state
        SERVER.DAILY.add_favorite = cls.old_add
        SERVER.DAILY.remove_favorite = cls.old_remove
        SERVER.DAILY.create_saved_theme = cls.old_create
        SERVER.DAILY.delete_saved_theme = cls.old_delete
        SERVER.DAILY.clear_search_history = cls.old_clear_history
        SERVER.DAILY.clear_recent_laws = cls.old_clear_recent
        SERVER.DAILY.record_query_activity = cls.old_record
        if cls.old_psycopg is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = cls.old_psycopg

    def request(self, path: str, *, method: str = "GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read(), response.headers
        except HTTPError as exc:
            status, body, headers = exc.code, exc.read(), exc.headers
            exc.close()
            return status, body, headers

    def test_health_reports_phase75(self):
        status, body, _ = self.request("/api/v1/health")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["app_version"], "phase7-5-daily-use")

    def test_daily_js_is_served(self):
        status, body, headers = self.request("/daily.js")
        self.assertEqual(status, 200)
        self.assertIn(b"loadDailyState", body)
        self.assertIn("text/javascript", headers.get("Content-Type", ""))

    def test_daily_state_route(self):
        status, body, _ = self.request("/api/v1/daily-state")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["source_truth"], "phase7-application-state")

    def test_add_and_remove_favorite(self):
        law_id = "129AC0000000089"
        status, body, _ = self.request(f"/api/v1/favorites/{law_id}", method="PUT")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["law_id"], law_id)
        status, body, _ = self.request(f"/api/v1/favorites/{law_id}", method="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["removed"])

    def test_create_and_delete_saved_theme(self):
        payload = {
            "title": "民法90条",
            "question": "民法の第90条を確認したい",
            "law_id": "129AC0000000089",
            "as_of_date": "2026-09-11",
        }
        status, body, _ = self.request("/api/v1/saved-themes", method="POST", payload=payload)
        created = json.loads(body)
        self.assertEqual(status, 201)
        self.assertEqual(created["title"], "民法90条")
        status, body, _ = self.request(
            f"/api/v1/saved-themes/{created['theme_id']}", method="DELETE"
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["removed"])

    def test_clear_history_and_recent(self):
        status, body, _ = self.request("/api/v1/search-history", method="DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["removed_count"], 3)
        status, body, _ = self.request("/api/v1/recent-laws", method="DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["removed_count"], 2)

    def test_invalid_limit_is_400(self):
        status, body, _ = self.request("/api/v1/daily-state?recent_limit=abc")
        payload = json.loads(body)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")

    def test_query_succeeds_when_activity_persistence_fails(self):
        self.activity_calls.clear()
        status, body, _ = self.request(
            "/api/v1/query", method="POST",
            payload={"question": "民法の第90条を確認したい", "as_of_date": "2026-09-11"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "evidence-only")
        self.assertEqual(self.activity_calls, ["c" * 32])

    def test_database_not_configured_is_503(self):
        old = self.server.state.database_url
        self.server.state.database_url = None
        try:
            status, body, _ = self.request("/api/v1/daily-state")
        finally:
            self.server.state.database_url = old
        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["code"], "DATABASE_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
