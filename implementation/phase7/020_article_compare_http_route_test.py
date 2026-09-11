from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
SERVER_PATH = HERE / "003_web_server.py"
spec = importlib.util.spec_from_file_location("phase73_http_server_tested", SERVER_PATH)
assert spec and spec.loader
SERVER = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = SERVER
spec.loader.exec_module(SERVER)


class FakeCursor:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql): self.last_sql = sql


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
        cls.old_compare = SERVER.COMPARE.get_article_comparison

        def fake_compare(conn, law_id, *, from_date, to_date, article_num=None, scope_key=None):
            cls.calls.append({
                "law_id": law_id,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "article_num": article_num,
                "scope_key": scope_key,
            })
            return {
                "status": "ok",
                "source_truth": "phase3-phase4",
                "article_num": article_num,
                "scope_key": scope_key,
            }

        SERVER.COMPARE.get_article_comparison = fake_compare
        state = SERVER.AppState()
        state.database_url = "mock://database"
        cls.server = SERVER.LegalKbHttpServer(("127.0.0.1", 0), SERVER.Handler, state)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        SERVER.COMPARE.get_article_comparison = cls.old_compare
        if cls.old_psycopg is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = cls.old_psycopg

    def request(self, path: str):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urlopen(url, timeout=5) as response:
                return response.status, response.read(), response.headers
        except HTTPError as exc:
            status = exc.code
            body = exc.read()
            headers = exc.headers
            exc.close()
            return status, body, headers

    def test_health_reports_phase73(self):
        status, body, _ = self.request("/api/v1/health")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["app_version"], "phase7-3-compare")

    def test_index_contains_phase73_compare_panel(self):
        status, body, _ = self.request("/")
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("Phase 7-3", text)
        self.assertIn('id="compare-panel"', text)
        self.assertIn('/compare.js', text)
    def test_compare_js_is_served(self):
        status, body, headers = self.request("/compare.js")
        self.assertEqual(status, 200)
        self.assertIn(b"submitComparison", body)
        self.assertIn("text/javascript", headers.get("Content-Type", ""))

    def test_valid_compare_propagates_scope(self):
        path = (
            "/api/v1/laws/129AC0000000089/compare"
            "?from_date=2026-09-10&to_date=2027-07-01"
            "&article_num=891&scope_key=main"
        )
        status, body, _ = self.request(path)
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["scope_key"], "main")
        self.assertEqual(self.calls[-1]["article_num"], "891")
        self.assertEqual(self.calls[-1]["scope_key"], "main")

    def test_range_article_num_is_accepted(self):
        path = (
            "/api/v1/laws/129AC0000000089/compare"
            "?from_date=2026-09-10&to_date=2027-07-01&article_num=155%3A157"
        )
        status, _, _ = self.request(path)
        self.assertEqual(status, 200)
        self.assertEqual(self.calls[-1]["article_num"], "155:157")

    def test_missing_dates_is_400(self):
        status, body, _ = self.request("/api/v1/laws/129AC0000000089/compare?from_date=2026-09-10")
        payload = json.loads(body)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")

    def test_invalid_scope_is_400(self):
        path = (
            "/api/v1/laws/129AC0000000089/compare"
            "?from_date=2026-09-10&to_date=2027-07-01&scope_key=unknown"
        )
        status, body, _ = self.request(path)
        payload = json.loads(body)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")

    def test_database_not_configured_is_503(self):
        old = self.server.state.database_url
        self.server.state.database_url = None
        try:
            status, body, _ = self.request(
                "/api/v1/laws/129AC0000000089/compare?from_date=2026-09-10&to_date=2027-07-01"
            )
        finally:
            self.server.state.database_url = old
        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["code"], "DATABASE_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
