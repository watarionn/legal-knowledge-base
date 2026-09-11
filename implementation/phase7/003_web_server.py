#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
MAX_REQUEST_BYTES = 64 * 1024


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SERVICE = _load("legal_kb_phase7_query_service", HERE / "002_query_service.py")
HISTORY = _load("legal_kb_phase7_history_service", HERE / "012_law_history_service.py")
COMPARE = _load("legal_kb_phase7_article_compare", HERE / "017_article_compare_service.py")
RELATED = _load("legal_kb_phase7_related_material", HERE / "022_related_material_service.py")
DAILY = _load("legal_kb_phase7_daily_use", HERE / "029_daily_use_service.py")


class AppState:
    def __init__(self) -> None:
        self.database_url = os.environ.get("LEGAL_KB_DATABASE_URL") or None
        self.query_service = SERVICE.QueryService()
        self.evidence_cache: dict[str, dict[str, Any]] = {}

    def remember_evidence(self, response: dict[str, Any]) -> None:
        for item in response.get("evidence") or []:
            evidence_id = item.get("evidence_id")
            if isinstance(evidence_id, str) and evidence_id:
                self.evidence_cache[evidence_id] = item
        if len(self.evidence_cache) > 512:
            for key in list(self.evidence_cache)[:128]:
                self.evidence_cache.pop(key, None)


class LegalKbHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class, state: AppState):
        super().__init__(server_address, handler_class)
        self.state = state


class Handler(BaseHTTPRequestHandler):
    server_version = "LegalKBPhase7/0.1"

    @property
    def state(self) -> AppState:
        return self.server.state  # type: ignore[attr-defined]

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'",
        )
        self.send_header("Cache-Control", "no-store")

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_error_json(
        self,
        status: int,
        code: str,
        message: str,
        query_id: str | None = None,
    ) -> None:
        self._send_json(
            status,
            {"error": {"code": code, "message": message, "query_id": query_id}},
        )

    def _serve_static(self, filename: str, content_type: str) -> None:
        path = WEB_DIR / filename
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self._send_error_json(404, "NOT_FOUND", "resource not found")
            return
        self._send_bytes(200, body, content_type)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_static("app.js", "text/javascript; charset=utf-8")
            return
        if path == "/compare.js":
            self._serve_static("compare.js", "text/javascript; charset=utf-8")
            return
        if path == "/related.js":
            self._serve_static("related.js", "text/javascript; charset=utf-8")
            return
        if path == "/daily.js":
            self._serve_static("daily.js", "text/javascript; charset=utf-8")
            return
        if path == "/api/v1/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "database": "configured" if self.state.database_url else "not-configured",
                    "answer_provider": "not-configured",
                    "vector_provider": "not-configured",
                    "app_version": "phase7-5-daily-use",
                },
            )
            return
        if path == "/api/v1/daily-state":
            if not self.state.database_url:
                self._send_error_json(503, "DATABASE_NOT_CONFIGURED", "LEGAL_KB_DATABASE_URL is not configured")
                return
            params = parse_qs(urlsplit(self.path).query)
            try:
                recent_limit = int(params.get("recent_limit", ["12"])[-1])
                history_limit = int(params.get("history_limit", ["30"])[-1])
            except ValueError:
                self._send_error_json(400, "INVALID_REQUEST", "limits must be integers")
                return
            try:
                import psycopg
                conn = psycopg.connect(self.state.database_url)
            except ImportError:
                self._send_error_json(503, "PSYCOPG_NOT_INSTALLED", "psycopg is required for database queries")
                return
            except Exception:
                self._send_error_json(503, "DATABASE_UNAVAILABLE", "database connection failed")
                return
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("SET TRANSACTION READ ONLY")
                    if not DAILY.application_state_ready(conn):
                        self._send_error_json(503, "APPLICATION_STATE_NOT_CONFIGURED", "Phase 7 application state schema is not configured")
                        return
                    state = DAILY.get_daily_state(conn, recent_limit=recent_limit, history_limit=history_limit)
                self._send_json(200, state)
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
            except Exception as exc:
                self.log_error("daily state query failed: %s", exc.__class__.__name__)
                self._send_error_json(500, "DAILY_STATE_QUERY_FAILED", "daily state query failed")
            finally:
                conn.close()
            return
        related_prefix = "/api/v1/laws/"
        related_suffix = "/related-materials"
        if path.startswith(related_prefix) and path.endswith(related_suffix):
            law_id = path[len(related_prefix):-len(related_suffix)].strip("/")
            if not self.state.database_url:
                self._send_error_json(503, "DATABASE_NOT_CONFIGURED", "LEGAL_KB_DATABASE_URL is not configured")
                return
            params = parse_qs(urlsplit(self.path).query)
            try:
                as_of = HISTORY.parse_as_of_date(params.get("as_of_date", [None])[-1])
                raw_flag = (params.get("include_nonconfirmed", ["false"])[-1] or "false").lower()
                if raw_flag not in {"true", "false"}:
                    raise ValueError("include_nonconfirmed must be true or false")
                include_nonconfirmed = raw_flag == "true"
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
                return
            try:
                import psycopg
                conn = psycopg.connect(self.state.database_url)
            except ImportError:
                self._send_error_json(503, "PSYCOPG_NOT_INSTALLED", "psycopg is required for database queries")
                return
            except Exception:
                self._send_error_json(503, "DATABASE_UNAVAILABLE", "database connection failed")
                return
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("SET TRANSACTION READ ONLY")
                    related = RELATED.get_related_materials(
                        conn,
                        law_id,
                        as_of_date=as_of,
                        include_nonconfirmed=include_nonconfirmed,
                    )
                if related is None:
                    self._send_error_json(404, "LAW_NOT_FOUND", "law was not found")
                else:
                    self._send_json(200, related)
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
            except Exception as exc:
                self.log_error("related material query failed: %s", exc.__class__.__name__)
                self._send_error_json(500, "RELATED_MATERIAL_QUERY_FAILED", "related material query failed")
            finally:
                conn.close()
            return
        relation_prefix = "/api/v1/source-relations/"
        if path.startswith(relation_prefix):
            source_relation_id = path[len(relation_prefix):].strip("/")
            if not self.state.database_url:
                self._send_error_json(503, "DATABASE_NOT_CONFIGURED", "LEGAL_KB_DATABASE_URL is not configured")
                return
            try:
                import psycopg
                conn = psycopg.connect(self.state.database_url)
            except ImportError:
                self._send_error_json(503, "PSYCOPG_NOT_INSTALLED", "psycopg is required for database queries")
                return
            except Exception:
                self._send_error_json(503, "DATABASE_UNAVAILABLE", "database connection failed")
                return
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("SET TRANSACTION READ ONLY")
                    detail = RELATED.get_relation_detail(conn, source_relation_id)
                if detail is None:
                    self._send_error_json(404, "SOURCE_RELATION_NOT_FOUND", "source relation was not found")
                else:
                    self._send_json(200, detail)
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
            except Exception as exc:
                self.log_error("source relation detail failed: %s", exc.__class__.__name__)
                self._send_error_json(500, "SOURCE_RELATION_DETAIL_FAILED", "source relation detail failed")
            finally:
                conn.close()
            return
        compare_prefix = "/api/v1/laws/"
        compare_suffix = "/compare"
        if path.startswith(compare_prefix) and path.endswith(compare_suffix):
            law_id = path[len(compare_prefix):-len(compare_suffix)].strip("/")
            if not self.state.database_url:
                self._send_error_json(503, "DATABASE_NOT_CONFIGURED", "LEGAL_KB_DATABASE_URL is not configured")
                return
            params = parse_qs(urlsplit(self.path).query)
            from_raw = params.get("from_date", [None])[-1]
            to_raw = params.get("to_date", [None])[-1]
            article_num = params.get("article_num", [None])[-1]
            scope_key = params.get("scope_key", [None])[-1]
            try:
                if not from_raw or not to_raw:
                    raise ValueError("from_date and to_date are required")
                from_date = HISTORY.parse_as_of_date(from_raw)
                to_date = HISTORY.parse_as_of_date(to_raw)
                article_num = COMPARE.parse_article_num(article_num)
                scope_key = COMPARE.parse_scope_key(scope_key)
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
                return
            try:
                import psycopg
                conn = psycopg.connect(self.state.database_url)
            except ImportError:
                self._send_error_json(503, "PSYCOPG_NOT_INSTALLED", "psycopg is required for database queries")
                return
            except Exception:
                self._send_error_json(503, "DATABASE_UNAVAILABLE", "database connection failed")
                return
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("SET TRANSACTION READ ONLY")
                    comparison = COMPARE.get_article_comparison(
                        conn, law_id, from_date=from_date, to_date=to_date, article_num=article_num, scope_key=scope_key
                    )
                self._send_json(200, comparison)
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
            except Exception as exc:
                self.log_error("article comparison failed: %s", exc.__class__.__name__)
                self._send_error_json(500, "ARTICLE_COMPARE_FAILED", "article comparison failed")
            finally:
                conn.close()
            return
        history_prefix = "/api/v1/laws/"
        history_suffix = "/history"
        if path.startswith(history_prefix) and path.endswith(history_suffix):
            law_id = path[len(history_prefix):-len(history_suffix)].strip("/")
            if not self.state.database_url:
                self._send_error_json(503, "DATABASE_NOT_CONFIGURED", "LEGAL_KB_DATABASE_URL is not configured")
                return
            try:
                as_of_raw = parse_qs(urlsplit(self.path).query).get("as_of_date", [None])[-1]
                as_of = HISTORY.parse_as_of_date(as_of_raw)
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
                return
            try:
                import psycopg
                conn = psycopg.connect(self.state.database_url)
            except ImportError:
                self._send_error_json(503, "PSYCOPG_NOT_INSTALLED", "psycopg is required for database queries")
                return
            except Exception:
                self._send_error_json(503, "DATABASE_UNAVAILABLE", "database connection failed")
                return
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("SET TRANSACTION READ ONLY")
                    history = HISTORY.get_law_history(conn, law_id, as_of_date=as_of)
                if history is None:
                    self._send_error_json(404, "LAW_NOT_FOUND", "law was not found")
                else:
                    self._send_json(200, history)
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
            except Exception as exc:
                self.log_error("history query failed: %s", exc.__class__.__name__)
                self._send_error_json(500, "HISTORY_QUERY_FAILED", "history query failed")
            finally:
                conn.close()
            return
        prefix = "/api/v1/evidence/"
        if path.startswith(prefix):
            evidence_id = path[len(prefix):]
            item = self.state.evidence_cache.get(evidence_id)
            if item is None:
                self._send_error_json(
                    404,
                    "EVIDENCE_NOT_FOUND",
                    "evidence is unknown or expired",
                )
            else:
                self._send_json(200, item)
            return
        self._send_error_json(404, "NOT_FOUND", "endpoint not found")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/v1/saved-themes":
            raw_length = self.headers.get("Content-Length")
            try:
                content_length = int(raw_length or "0")
                if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                    raise ValueError("invalid request body length")
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be a JSON object")
                theme_date = HISTORY.parse_as_of_date(payload.get("as_of_date")) if payload.get("as_of_date") else None
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
                return
            if not self.state.database_url:
                self._send_error_json(503, "DATABASE_NOT_CONFIGURED", "LEGAL_KB_DATABASE_URL is not configured")
                return
            try:
                import psycopg
                conn = psycopg.connect(self.state.database_url)
                with conn:
                    if not DAILY.application_state_ready(conn):
                        self._send_error_json(503, "APPLICATION_STATE_NOT_CONFIGURED", "Phase 7 application state schema is not configured")
                        return
                    theme = DAILY.create_saved_theme(conn, title=payload.get("title", ""), question=payload.get("question", ""), law_id=payload.get("law_id"), as_of_date=theme_date)
                self._send_json(201, theme)
            except ValueError as exc:
                self._send_error_json(400, "INVALID_REQUEST", str(exc))
            except Exception as exc:
                self.log_error("saved theme create failed: %s", exc.__class__.__name__)
                self._send_error_json(500, "SAVED_THEME_CREATE_FAILED", "saved theme create failed")
            finally:
                if 'conn' in locals(): conn.close()
            return
        if path != "/api/v1/query":
            self._send_error_json(404, "NOT_FOUND", "endpoint not found")
            return
        raw_length = self.headers.get("Content-Length")
        try:
            content_length = int(raw_length or "0")
        except ValueError:
            self._send_error_json(400, "INVALID_REQUEST", "invalid Content-Length")
            return
        if content_length <= 0:
            self._send_error_json(400, "INVALID_REQUEST", "request body is required")
            return
        if content_length > MAX_REQUEST_BYTES:
            self._send_error_json(413, "REQUEST_TOO_LARGE", "request body is too large")
            return
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error_json(
                400,
                "INVALID_JSON",
                "request body must be UTF-8 JSON",
            )
            return

        if not self.state.database_url:
            self._send_error_json(
                503,
                "DATABASE_NOT_CONFIGURED",
                "LEGAL_KB_DATABASE_URL is not configured",
            )
            return
        try:
            import psycopg
        except ImportError:
            self._send_error_json(
                503,
                "PSYCOPG_NOT_INSTALLED",
                "psycopg is required for database queries",
            )
            return

        try:
            conn = psycopg.connect(self.state.database_url)
        except Exception:
            self._send_error_json(
                503,
                "DATABASE_UNAVAILABLE",
                "database connection failed",
            )
            return

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                response = self.state.query_service.query(conn, payload)
            self.state.remember_evidence(response)
            try:
                with conn:
                    if DAILY.application_state_ready(conn):
                        DAILY.record_query_activity(conn, response)
            except Exception as activity_exc:
                self.log_error("daily activity persistence failed: %s", activity_exc.__class__.__name__)
            self._send_json(200, response)
        except SERVICE.CONTRACT.RequestValidationError as exc:
            self._send_error_json(400, "INVALID_REQUEST", str(exc))
        except SERVICE.Phase7ConfigurationError as exc:
            self._send_error_json(503, "APPLICATION_NOT_CONFIGURED", str(exc))
        except Exception as exc:
            self.log_error("query failed: %s", exc.__class__.__name__)
            self._send_error_json(500, "QUERY_FAILED", "query processing failed")
        finally:
            conn.close()

    def do_PUT(self) -> None:
        path = self.path.split("?", 1)[0]
        prefix = "/api/v1/favorites/"
        if not path.startswith(prefix):
            self._send_error_json(405, "METHOD_NOT_ALLOWED", "method not allowed")
            return
        law_id = path[len(prefix):].strip("/")
        if not self.state.database_url:
            self._send_error_json(503, "DATABASE_NOT_CONFIGURED", "LEGAL_KB_DATABASE_URL is not configured")
            return
        conn = None
        try:
            import psycopg
            conn = psycopg.connect(self.state.database_url)
            with conn:
                if not DAILY.application_state_ready(conn):
                    self._send_error_json(503, "APPLICATION_STATE_NOT_CONFIGURED", "Phase 7 application state schema is not configured")
                    return
                favorite = DAILY.add_favorite(conn, law_id)
            if favorite is None:
                self._send_error_json(404, "LAW_NOT_FOUND", "law was not found")
            else:
                self._send_json(200, favorite)
        except ValueError as exc:
            self._send_error_json(400, "INVALID_REQUEST", str(exc))
        except Exception as exc:
            self.log_error("favorite update failed: %s", exc.__class__.__name__)
            self._send_error_json(500, "FAVORITE_UPDATE_FAILED", "favorite update failed")
        finally:
            if conn is not None: conn.close()

    def do_DELETE(self) -> None:
        path = self.path.split("?", 1)[0]
        if not self.state.database_url:
            self._send_error_json(503, "DATABASE_NOT_CONFIGURED", "LEGAL_KB_DATABASE_URL is not configured")
            return
        conn = None
        try:
            import psycopg
            conn = psycopg.connect(self.state.database_url)
            with conn:
                if not DAILY.application_state_ready(conn):
                    self._send_error_json(503, "APPLICATION_STATE_NOT_CONFIGURED", "Phase 7 application state schema is not configured")
                    return
                if path.startswith("/api/v1/favorites/"):
                    law_id = path[len("/api/v1/favorites/"):].strip("/")
                    removed = DAILY.remove_favorite(conn, law_id)
                elif path.startswith("/api/v1/saved-themes/"):
                    theme_id = path[len("/api/v1/saved-themes/"):].strip("/")
                    removed = DAILY.delete_saved_theme(conn, theme_id)
                elif path == "/api/v1/search-history":
                    self._send_json(200, {"removed_count": DAILY.clear_search_history(conn)})
                    return
                elif path == "/api/v1/recent-laws":
                    self._send_json(200, {"removed_count": DAILY.clear_recent_laws(conn)})
                    return
                else:
                    self._send_error_json(405, "METHOD_NOT_ALLOWED", "method not allowed")
                    return
            self._send_json(200, {"removed": bool(removed)})
        except ValueError as exc:
            self._send_error_json(400, "INVALID_REQUEST", str(exc))
        except Exception as exc:
            self.log_error("daily state delete failed: %s", exc.__class__.__name__)
            self._send_error_json(500, "DAILY_STATE_DELETE_FAILED", "daily state delete failed")
        finally:
            if conn is not None: conn.close()


def main() -> None:
    host = os.environ.get("LEGAL_KB_HOST", "127.0.0.1")
    raw_port = os.environ.get("LEGAL_KB_PORT", "8765")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise SystemExit("LEGAL_KB_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("LEGAL_KB_PORT must be in 1..65535")
    state = AppState()
    server = LegalKbHttpServer((host, port), Handler, state)
    print(f"Legal KB Phase 7-5: http://{host}:{port}")
    print("Database:", "configured" if state.database_url else "not configured")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
