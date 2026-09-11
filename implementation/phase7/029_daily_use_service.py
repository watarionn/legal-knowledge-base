from __future__ import annotations

from datetime import date
import re
import uuid
from typing import Any

WORKSPACE_ID = "local"
LAW_ID_RE = re.compile(r"^[0-9A-Z]{15}$")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_law_id(law_id: str) -> str:
    if not LAW_ID_RE.fullmatch(law_id or ""):
        raise ValueError("law_id must be a 15-character e-Gov law ID")
    return law_id


def _validate_limit(value: int, *, maximum: int = 100) -> int:
    if not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return value


def _law_exists(conn: Any, law_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM legal_kb.law WHERE law_id = %s", (law_id,))
        return cur.fetchone() is not None
LAW_SUMMARY_SQL = """
SELECT l.law_id, l.law_num, latest.law_title
FROM legal_kb.law l
LEFT JOIN LATERAL (
    SELECT r.law_title
    FROM legal_kb.law_revision r
    WHERE r.law_id = l.law_id
    ORDER BY (r.current_revision_status = 'Current') DESC,
             r.revision_sequence DESC NULLS LAST,
             r.revision_id_effective_date DESC
    LIMIT 1
) latest ON true
WHERE l.law_id = %s
"""


def get_law_summary(conn: Any, law_id: str) -> dict[str, Any] | None:
    law_id = _validate_law_id(law_id)
    with conn.cursor() as cur:
        cur.execute(LAW_SUMMARY_SQL, (law_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return {"law_id": row[0], "law_num": row[1], "law_title": row[2]}


def add_favorite(conn: Any, law_id: str) -> dict[str, Any] | None:
    law = get_law_summary(conn, law_id)
    if law is None:
        return None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO legal_kb.application_favorite_law (workspace_id, law_id)
            VALUES (%s, %s)
            ON CONFLICT (workspace_id, law_id) DO NOTHING
        """, (WORKSPACE_ID, law_id))
    law["favorite"] = True
    return law


def remove_favorite(conn: Any, law_id: str) -> bool:
    law_id = _validate_law_id(law_id)
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM legal_kb.application_favorite_law
            WHERE workspace_id = %s AND law_id = %s
        """, (WORKSPACE_ID, law_id))
        return cur.rowcount > 0
def list_favorites(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT f.law_id, l.law_num, latest.law_title, f.created_at
            FROM legal_kb.application_favorite_law f
            JOIN legal_kb.law l ON l.law_id = f.law_id
            LEFT JOIN LATERAL (
                SELECT r.law_title
                FROM legal_kb.law_revision r
                WHERE r.law_id = f.law_id
                ORDER BY (r.current_revision_status = 'Current') DESC,
                         r.revision_sequence DESC NULLS LAST,
                         r.revision_id_effective_date DESC
                LIMIT 1
            ) latest ON true
            WHERE f.workspace_id = %s
            ORDER BY f.created_at DESC, f.law_id
        """, (WORKSPACE_ID,))
        rows = cur.fetchall()
    return [
        {"law_id": row[0], "law_num": row[1], "law_title": row[2], "created_at": _iso(row[3])}
        for row in rows
    ]


def list_recent_laws(conn: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    limit = _validate_limit(limit, maximum=50)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT recent.law_id, l.law_num, latest.law_title,
                   recent.last_viewed_at, recent.view_count, recent.last_query_id
            FROM legal_kb.application_recent_law recent
            JOIN legal_kb.law l ON l.law_id = recent.law_id
            LEFT JOIN LATERAL (
                SELECT r.law_title FROM legal_kb.law_revision r
                WHERE r.law_id = recent.law_id
                ORDER BY (r.current_revision_status = 'Current') DESC,
                         r.revision_sequence DESC NULLS LAST,
                         r.revision_id_effective_date DESC LIMIT 1
            ) latest ON true
            WHERE recent.workspace_id = %s
            ORDER BY recent.last_viewed_at DESC, recent.law_id
            LIMIT %s
        """, (WORKSPACE_ID, limit))
        rows = cur.fetchall()
    return [
        {"law_id": r[0], "law_num": r[1], "law_title": r[2], "last_viewed_at": _iso(r[3]),
         "view_count": r[4], "last_query_id": r[5]}
        for r in rows
    ]
def record_query_activity(conn: Any, response: dict[str, Any]) -> None:
    query_id = str(response.get("query_id") or "")
    if not HEX32_RE.fullmatch(query_id):
        raise ValueError("query response has invalid query_id")
    question = str(response.get("question") or "").strip()
    if not question or len(question) > 4000:
        raise ValueError("query response has invalid question")

    law_resolution = response.get("law_resolution") or {}
    law_id = law_resolution.get("selected_law_id")
    if law_id is not None:
        _validate_law_id(str(law_id))
    law_title = law_resolution.get("selected_law_title")
    temporal = response.get("temporal_resolution") or {}
    temporal_status = temporal.get("status")

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO legal_kb.application_search_history
                (query_id, workspace_id, question, requested_as_of_date,
                 effective_as_of_date, law_id, law_title_snapshot,
                 response_status, temporal_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (query_id) DO NOTHING
        """, (
            query_id, WORKSPACE_ID, question, response.get("requested_as_of_date"),
            response.get("effective_as_of_date"), law_id, law_title,
            str(response.get("status") or "unknown"), temporal_status,
        ))
    if law_id is not None:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO legal_kb.application_recent_law
                    (workspace_id, law_id, last_query_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (workspace_id, law_id) DO UPDATE SET
                    last_viewed_at = now(),
                    view_count = legal_kb.application_recent_law.view_count + 1,
                    last_query_id = EXCLUDED.last_query_id
            """, (WORKSPACE_ID, law_id, query_id))


def list_search_history(conn: Any, *, limit: int = 30) -> list[dict[str, Any]]:
    limit = _validate_limit(limit)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT query_id, question, requested_as_of_date, effective_as_of_date,
                   law_id, law_title_snapshot, response_status, temporal_status, created_at
            FROM legal_kb.application_search_history
            WHERE workspace_id = %s
            ORDER BY created_at DESC, query_id DESC
            LIMIT %s
        """, (WORKSPACE_ID, limit))
        rows = cur.fetchall()
    return [
        {"query_id": r[0], "question": r[1], "requested_as_of_date": _iso(r[2]),
         "effective_as_of_date": _iso(r[3]), "law_id": r[4], "law_title": r[5],
         "status": r[6], "temporal_status": r[7], "created_at": _iso(r[8])}
        for r in rows
    ]
def create_saved_theme(
    conn: Any,
    *,
    title: str,
    question: str,
    law_id: str | None = None,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    title = (title or "").strip()
    question = (question or "").strip()
    if not 1 <= len(title) <= 120:
        raise ValueError("title must be between 1 and 120 characters")
    if not 1 <= len(question) <= 4000:
        raise ValueError("question must be between 1 and 4000 characters")
    if law_id is not None:
        _validate_law_id(law_id)
        if not _law_exists(conn, law_id):
            raise ValueError("law_id was not found")

    theme_id = uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO legal_kb.application_saved_theme
                (theme_id, workspace_id, title, question, law_id, as_of_date)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING created_at, updated_at
        """, (theme_id, WORKSPACE_ID, title, question, law_id, as_of_date))
        created_at, updated_at = cur.fetchone()
    return {
        "theme_id": theme_id,
        "title": title,
        "question": question,
        "law_id": law_id,
        "as_of_date": _iso(as_of_date),
        "created_at": _iso(created_at),
        "updated_at": _iso(updated_at),
    }


def list_saved_themes(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT theme_id, title, question, law_id, as_of_date, created_at, updated_at
            FROM legal_kb.application_saved_theme
            WHERE workspace_id = %s
            ORDER BY updated_at DESC, theme_id
        """, (WORKSPACE_ID,))
        rows = cur.fetchall()
    return [
        {"theme_id": r[0], "title": r[1], "question": r[2], "law_id": r[3],
         "as_of_date": _iso(r[4]), "created_at": _iso(r[5]), "updated_at": _iso(r[6])}
        for r in rows
    ]
def delete_saved_theme(conn: Any, theme_id: str) -> bool:
    if not HEX32_RE.fullmatch(theme_id or ""):
        raise ValueError("theme_id must be a 32-character lowercase hex ID")
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM legal_kb.application_saved_theme
            WHERE workspace_id = %s AND theme_id = %s
        """, (WORKSPACE_ID, theme_id))
        return cur.rowcount > 0


def clear_search_history(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM legal_kb.application_search_history WHERE workspace_id = %s",
            (WORKSPACE_ID,),
        )
        return cur.rowcount


def clear_recent_laws(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM legal_kb.application_recent_law WHERE workspace_id = %s",
            (WORKSPACE_ID,),
        )
        return cur.rowcount
def get_daily_state(
    conn: Any,
    *,
    recent_limit: int = 12,
    history_limit: int = 30,
) -> dict[str, Any]:
    return {
        "api_version": "1",
        "workspace_id": WORKSPACE_ID,
        "favorites": list_favorites(conn),
        "recent_laws": list_recent_laws(conn, limit=recent_limit),
        "search_history": list_search_history(conn, limit=history_limit),
        "saved_themes": list_saved_themes(conn),
        "source_truth": "phase7-application-state",
        "law_text_truth": "phase3-phase4",
    }
APPLICATION_STATE_RELATIONS = (
    "application_favorite_law",
    "application_recent_law",
    "application_search_history",
    "application_saved_theme",
)


def application_state_ready(conn: Any) -> bool:
    with conn.cursor() as cur:
        for name in APPLICATION_STATE_RELATIONS:
            cur.execute("SELECT to_regclass(%s)", (f"legal_kb.{name}",))
            if cur.fetchone()[0] is None:
                return False
    return True
