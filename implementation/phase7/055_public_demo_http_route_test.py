from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import types
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
SERVER_PATH = HERE / "003_web_server.py"
spec = importlib.util.spec_from_file_location("phase8_public_demo_server", SERVER_PATH)
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


class FakeQueryService:
    def __init__(self, calls):
        self.calls = calls

    def query(self, conn, payload, *, answer_provider=None):
        self.calls.append({"payload": payload, "answer_provider": answer_provider})
        return {
            "status": "evidence-only",
            "query_id": "public-demo-test",
            "effective_as_of_date": "2026-09-16",
            "law_resolution": {"selected_law_id": "129AC0000000089"},
            "temporal_resolution": {"status": "resolved"},
            "retrieval": {"status": "ok"},
            "evidence": [],
            "answer": {"status": "not-configured"},
        }


class PublicDemoRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_public_demo = os.environ.get("LEGAL_KB_PUBLIC_DEMO")
        cls.old_answer_provider = os.environ.get("LEGAL_KB_ANSWER_PROVIDER")
        os.environ["LEGAL_KB_PUBLIC_DEMO"] = "1"
        os.environ["LEGAL_KB_ANSWER_PROVIDER"] = "ollama"

        cls.old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = types.SimpleNamespace(connect=lambda _url: FakeConnection())
        cls.old_related = SERVER.RELATED.get_related_materials
        cls.related_calls = []
        def fake_related(conn, law_id, *, as_of_date, include_nonconfirmed=False):
            cls.related_calls.append(include_nonconfirmed)
            return {
                "law_id": law_id,
                "as_of_date": as_of_date.isoformat(),
                "revision_scope_available": True,
                "temporal_resolution": {"status": "resolved"},
                "include_nonconfirmed": include_nonconfirmed,
                "material_count": 0,
                "materials": [],
            }
        SERVER.RELATED.get_related_materials = fake_related

        cls.query_calls = []
        state = SERVER.AppState()
        state.database_url = "mock://database"
        state.query_service = FakeQueryService(cls.query_calls)
        cls.state = state
        cls.server = SERVER.LegalKbHttpServer(("127.0.0.1", 0), SERVER.Handler, state)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        SERVER.RELATED.get_related_materials = cls.old_related
        if cls.old_psycopg is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = cls.old_psycopg
        if cls.old_public_demo is None:
            os.environ.pop("LEGAL_KB_PUBLIC_DEMO", None)
        else:
            os.environ["LEGAL_KB_PUBLIC_DEMO"] = cls.old_public_demo
        if cls.old_answer_provider is None:
            os.environ.pop("LEGAL_KB_ANSWER_PROVIDER", None)
        else:
            os.environ["LEGAL_KB_ANSWER_PROVIDER"] = cls.old_answer_provider

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

    def test_public_state_disables_answer_provider(self):
        self.assertTrue(self.state.public_demo)
        self.assertIsNone(self.state.answer_provider)

    def test_public_root_uses_separate_ui(self):
        status, body, _ = self.request("/")
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("Public Demo", text)
        self.assertNotIn("daily.js", text)
        self.assertNotIn("マイリスト", text)
    def test_private_static_asset_is_blocked(self):
        status, body, _ = self.request("/daily.js")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "PUBLIC_DEMO_NOT_AVAILABLE")

    def test_public_security_headers(self):
        status, _, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
        self.assertIn("frame-ancestors 'none'", headers.get("Content-Security-Policy", ""))
        self.assertIn("camera=()", headers.get("Permissions-Policy", ""))
        self.assertNotIn("Python", headers.get("Server", ""))

    def test_public_health_is_sanitized(self):
        status, body, _ = self.request("/api/v1/health")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "public-demo")
        self.assertNotIn("database", payload)
        self.assertNotIn("answer_model", payload)

    def test_private_get_routes_are_blocked(self):
        for path in (
            "/api/v1/watches",
            "/api/v1/daily-state",
            "/api/v1/source-relations/abc",
            "/api/v1/evidence/abc",
        ):
            status, body, _ = self.request(path)
            self.assertEqual(status, 404, path)
            self.assertEqual(json.loads(body)["error"]["code"], "PUBLIC_DEMO_NOT_AVAILABLE")

    def test_private_write_routes_are_blocked(self):
        status, body, _ = self.request("/api/v1/watches", method="POST", payload={"law_id": "129AC0000000089"})
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "PUBLIC_DEMO_NOT_AVAILABLE")
        status, body, _ = self.request("/api/v1/favorites/129AC0000000089", method="PUT", payload={})
        self.assertEqual(status, 405)
        self.assertEqual(json.loads(body)["error"]["code"], "PUBLIC_DEMO_READ_ONLY")
        status, body, _ = self.request("/api/v1/recent-laws", method="DELETE")
        self.assertEqual(status, 405)
        self.assertEqual(json.loads(body)["error"]["code"], "PUBLIC_DEMO_READ_ONLY")
    def test_query_is_evidence_only_and_not_persisted(self):
        self.query_calls.clear()
        self.state.evidence_cache.clear()
        status, body, _ = self.request(
            "/api/v1/query",
            method="POST",
            payload={"question": "民法の第90条を確認したい"},
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["status"], "evidence-only")
        self.assertIsNone(self.query_calls[-1]["answer_provider"])
        self.assertEqual(self.state.evidence_cache, {})

    def test_public_query_busy_guard_returns_429(self):
        old_guard = self.state.public_query_guard
        guard = SERVER.PublicQueryGuard(30, 1)
        allowed, _ = guard.try_enter()
        self.assertTrue(allowed)
        self.state.public_query_guard = guard
        try:
            status, body, headers = self.request(
                "/api/v1/query", method="POST", payload={"question": "民法第90条"}
            )
        finally:
            guard.leave()
            self.state.public_query_guard = old_guard
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(body)["error"]["code"], "PUBLIC_DEMO_BUSY")
        self.assertEqual(headers.get("Retry-After"), "1")

    def test_public_query_rate_guard_returns_429(self):
        old_guard = self.state.public_query_guard
        self.state.public_query_guard = SERVER.PublicQueryGuard(1, 1)
        try:
            first, _, _ = self.request(
                "/api/v1/query", method="POST", payload={"question": "民法第90条"}
            )
            second, body, headers = self.request(
                "/api/v1/query", method="POST", payload={"question": "民法第90条"}
            )
        finally:
            self.state.public_query_guard = old_guard
        self.assertEqual(first, 200)
        self.assertEqual(second, 429)
        self.assertEqual(json.loads(body)["error"]["code"], "PUBLIC_DEMO_RATE_LIMIT")
        self.assertEqual(headers.get("Retry-After"), "60")

    def test_public_question_limit(self):
        status, body, _ = self.request(
            "/api/v1/query", method="POST", payload={"question": "x" * 801}
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "INVALID_REQUEST")

    def test_related_materials_force_confirmed_only(self):
        self.related_calls.clear()
        status, body, _ = self.request(
            "/api/v1/laws/129AC0000000089/related-materials?as_of_date=2026-09-16&include_nonconfirmed=true"
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertFalse(payload["include_nonconfirmed"])
        self.assertEqual(self.related_calls, [False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
