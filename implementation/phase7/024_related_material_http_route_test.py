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
spec = importlib.util.spec_from_file_location("phase74_http_server_tested", SERVER_PATH)
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
        cls.related_calls = []
        cls.detail_calls = []
        fake_psycopg = types.SimpleNamespace(connect=lambda url: FakeConnection())
        cls.old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = fake_psycopg
        cls.old_related = SERVER.RELATED.get_related_materials
        cls.old_detail = SERVER.RELATED.get_relation_detail

        def fake_related(conn, law_id, *, as_of_date, include_nonconfirmed=False):
            cls.related_calls.append({
                "law_id": law_id,
                "as_of_date": as_of_date.isoformat(),
                "include_nonconfirmed": include_nonconfirmed,
            })
            return {
                "law_id": law_id,
                "as_of_date": as_of_date.isoformat(),
                "material_count": 1,
                "include_nonconfirmed": include_nonconfirmed,
                "materials": [],
                "source_truth": "phase6-external-provenance",
            }
        def fake_detail(conn, source_relation_id):
            cls.detail_calls.append(source_relation_id)
            return {
                "source_relation_id": source_relation_id,
                "effective_state": "confirmed",
                "citation_ready": True,
                "assertions": [],
                "source_truth": "phase6-external-provenance",
            }

        SERVER.RELATED.get_related_materials = fake_related
        SERVER.RELATED.get_relation_detail = fake_detail
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
        SERVER.RELATED.get_related_materials = cls.old_related
        SERVER.RELATED.get_relation_detail = cls.old_detail
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

    def test_health_reports_phase74(self):
        status, body, _ = self.request("/api/v1/health")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["app_version"], "phase7-4-related-materials")

    def test_index_contains_related_panel(self):
        status, body, _ = self.request("/")
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("Phase 7-4", text)
        self.assertIn('id="related-panel"', text)
        self.assertIn('/related.js', text)

    def test_related_js_is_served(self):
        status, body, headers = self.request("/related.js")
        self.assertEqual(status, 200)
        self.assertIn(b"loadRelatedMaterials", body)
        self.assertIn("text/javascript", headers.get("Content-Type", ""))

    def test_default_related_materials_are_confirmed_only(self):
        path = "/api/v1/laws/129AC0000000089/related-materials?as_of_date=2026-09-11"
        status, body, _ = self.request(path)
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(payload["include_nonconfirmed"])
        self.assertFalse(self.related_calls[-1]["include_nonconfirmed"])
        self.assertEqual(self.related_calls[-1]["as_of_date"], "2026-09-11")

    def test_candidate_opt_in_is_propagated(self):
        path = (
            "/api/v1/laws/129AC0000000089/related-materials"
            "?as_of_date=2026-09-11&include_nonconfirmed=true"
        )
        status, body, _ = self.request(path)
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["include_nonconfirmed"])
        self.assertTrue(self.related_calls[-1]["include_nonconfirmed"])

    def test_invalid_candidate_flag_is_400(self):
        path = (
            "/api/v1/laws/129AC0000000089/related-materials"
            "?as_of_date=2026-09-11&include_nonconfirmed=maybe"
        )
        status, body, _ = self.request(path)
        payload = json.loads(body)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")

    def test_relation_detail_route(self):
        relation_id = "a" * 64
        status, body, _ = self.request(f"/api/v1/source-relations/{relation_id}")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["source_relation_id"], relation_id)
        self.assertEqual(self.detail_calls[-1], relation_id)

    def test_database_not_configured_is_503(self):
        old = self.server.state.database_url
        self.server.state.database_url = None
        try:
            status, body, _ = self.request(
                "/api/v1/laws/129AC0000000089/related-materials?as_of_date=2026-09-11"
            )
        finally:
            self.server.state.database_url = old
        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["code"], "DATABASE_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
