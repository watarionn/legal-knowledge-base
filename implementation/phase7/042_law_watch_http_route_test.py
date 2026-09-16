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
spec = importlib.util.spec_from_file_location("phase76_http_server_tested", SERVER_PATH)
assert spec and spec.loader
SERVER = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = SERVER
spec.loader.exec_module(SERVER)


class FakeCursor:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.last_sql = sql


class FakeConnection:
    def __init__(self): self.closed = False
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True; return False
    def cursor(self): return FakeCursor()
    def close(self): self.closed = True


class RouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_psycopg = types.SimpleNamespace(connect=lambda url: FakeConnection())
        cls.old_psycopg = sys.modules.get("psycopg")
        sys.modules["psycopg"] = fake_psycopg

        cls.old_ready = SERVER.WATCH.watch_state_ready
        cls.old_list = SERVER.WATCH.list_watches
        cls.old_list_events = SERVER.WATCH.list_watch_events
        cls.old_acknowledge = SERVER.WATCH.acknowledge_watch_event
        cls.old_create = SERVER.WATCH.create_watch
        cls.old_eval = SERVER.WATCH.evaluate_watch
        cls.old_eval_all = SERVER.WATCH.evaluate_all_watches
        cls.old_delete = SERVER.WATCH.delete_watch

        cls.calls = []
        SERVER.WATCH.watch_state_ready = lambda conn: True
        SERVER.WATCH.list_watches = lambda conn: [{"watch_id": "a" * 32, "law_id": "129AC0000000089"}]
        SERVER.WATCH.list_watch_events = lambda conn, watch_id, limit=100: [{
            "event_id": "e" * 32,
            "watch_id": watch_id,
            "event_type": "observed-change",
            "source_truth": "phase7-application-event",
        }]
        SERVER.WATCH.acknowledge_watch_event = lambda conn, event_id: {
            "event_id": event_id,
            "event_type": "effective-change",
            "acknowledged": True,
            "acknowledged_at": "2026-09-16T12:00:00+00:00",
        }
        SERVER.WATCH.create_watch = lambda conn, **kw: {
            "watch_id": "b" * 32, "law_id": kw["law_id"], "theme_id": kw.get("theme_id")
        }
        def evaluate_watch(conn, watch_id, *, evaluation_date):
            cls.calls.append(("one", watch_id, evaluation_date.isoformat()))
            return {
                "watch_id": watch_id,
                "law_id": "129AC0000000089",
                "evaluation_date": evaluation_date.isoformat(),
                "state": "initialized",
                "source_truth": "phase3-phase5",
            }
        def evaluate_all(conn, *, evaluation_date):
            cls.calls.append(("all", evaluation_date.isoformat()))
            return [{"watch_id": "a" * 32, "state": "no-change"}]
        SERVER.WATCH.evaluate_watch = evaluate_watch
        SERVER.WATCH.evaluate_all_watches = evaluate_all
        SERVER.WATCH.delete_watch = lambda conn, watch_id: True

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
        SERVER.WATCH.watch_state_ready = cls.old_ready
        SERVER.WATCH.list_watches = cls.old_list
        SERVER.WATCH.list_watch_events = cls.old_list_events
        SERVER.WATCH.acknowledge_watch_event = cls.old_acknowledge
        SERVER.WATCH.create_watch = cls.old_create
        SERVER.WATCH.evaluate_watch = cls.old_eval
        SERVER.WATCH.evaluate_all_watches = cls.old_eval_all
        SERVER.WATCH.delete_watch = cls.old_delete
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

    def test_list_watches(self):
        status, body, _ = self.request("/api/v1/watches")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["watches"][0]["watch_id"], "a" * 32)
        self.assertEqual(payload["source_truth"], "phase7-application-state")

    def test_list_watch_events(self):
        status, body, _ = self.request(
            "/api/v1/watches/" + "a" * 32 + "/events?limit=10"
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["events"][0]["event_type"], "observed-change")
        self.assertEqual(payload["source_truth"], "phase7-application-event")
        self.assertEqual(payload["law_revision_truth"], "phase3-law-revision")

    def test_watch_events_missing_watch_is_404(self):
        old = SERVER.WATCH.list_watch_events
        SERVER.WATCH.list_watch_events = lambda conn, watch_id, limit=100: None
        try:
            status, body, _ = self.request(
                "/api/v1/watches/" + "f" * 32 + "/events"
            )
        finally:
            SERVER.WATCH.list_watch_events = old
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "WATCH_NOT_FOUND")

    def test_watch_events_invalid_limit_is_400(self):
        status, body, _ = self.request(
            "/api/v1/watches/" + "a" * 32 + "/events?limit=abc"
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "INVALID_REQUEST")

    def test_acknowledge_watch_event(self):
        status, body, _ = self.request(
            "/api/v1/watch-events/" + "e" * 32 + "/acknowledge",
            method="POST",
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["acknowledged"])
        self.assertEqual(payload["event_id"], "e" * 32)

    def test_acknowledge_missing_event_is_404(self):
        old = SERVER.WATCH.acknowledge_watch_event
        SERVER.WATCH.acknowledge_watch_event = lambda conn, event_id: None
        try:
            status, body, _ = self.request(
                "/api/v1/watch-events/" + "f" * 32 + "/acknowledge",
                method="POST",
            )
        finally:
            SERVER.WATCH.acknowledge_watch_event = old
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "WATCH_EVENT_NOT_FOUND")

    def test_create_watch(self):
        status, body, _ = self.request(
            "/api/v1/watches", method="POST",
            payload={"law_id": "129AC0000000089"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["watch_id"], "b" * 32)

    def test_evaluate_one_watch(self):
        self.calls.clear()
        status, body, _ = self.request(
            "/api/v1/watches/" + "a" * 32 + "/evaluate",
            method="POST",
            payload={"evaluation_date": "2026-09-15"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "initialized")
        self.assertEqual(self.calls, [("one", "a" * 32, "2026-09-15")])

    def test_evaluate_all_watches(self):
        self.calls.clear()
        status, body, _ = self.request(
            "/api/v1/watches/evaluate",
            method="POST",
            payload={"evaluation_date": "2026-09-15"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["result_count"], 1)
        self.assertEqual(self.calls, [("all", "2026-09-15")])

    def test_delete_watch(self):
        status, body, _ = self.request(
            "/api/v1/watches/" + "a" * 32,
            method="DELETE",
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["removed"])

    def test_watch_state_not_configured_is_503(self):
        old = SERVER.WATCH.watch_state_ready
        SERVER.WATCH.watch_state_ready = lambda conn: False
        try:
            status, body, _ = self.request("/api/v1/watches")
        finally:
            SERVER.WATCH.watch_state_ready = old
        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["code"], "WATCH_STATE_NOT_CONFIGURED")

    def test_create_requires_body(self):
        status, body, _ = self.request("/api/v1/watches", method="POST")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main(verbosity=2)
