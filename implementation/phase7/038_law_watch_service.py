from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import re
import sys
import uuid
from typing import Any

HERE = Path(__file__).resolve().parent
PHASE5_DIR = HERE.parent / "phase5"
WORKSPACE_ID = "local"
LAW_ID_RE = re.compile(r"^[0-9A-Z]{15}$")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TEMPORAL = _load("legal_kb_phase76_temporal", PHASE5_DIR / "003_temporal_resolver.py")
def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_law_id(law_id: str) -> str:
    if not isinstance(law_id, str) or not LAW_ID_RE.fullmatch(law_id):
        raise ValueError("law_id must be a 15-character e-Gov law ID")
    return law_id


def _validate_hex32(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not HEX32_RE.fullmatch(value):
        raise ValueError(f"{field} must be a 32-character lowercase hex ID")
    return value


def _law_exists(conn: Any, law_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM legal_kb.law WHERE law_id = %s", (law_id,))
        return cur.fetchone() is not None


def _latest_successful_ingestion_run(conn: Any) -> str | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ingestion_run_id
            FROM legal_kb.ingestion_run
            WHERE result_status = 'succeeded'
            ORDER BY completed_at DESC NULLS LAST, started_at DESC, ingestion_run_id DESC
            LIMIT 1
        """)
        row = cur.fetchone()
    return None if row is None else str(row[0])
def _validate_theme_for_watch(conn: Any, theme_id: str, law_id: str) -> None:
    _validate_hex32(theme_id, field="theme_id")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT law_id
            FROM legal_kb.application_saved_theme
            WHERE workspace_id = %s AND theme_id = %s
        """, (WORKSPACE_ID, theme_id))
        row = cur.fetchone()
    if row is None:
        raise ValueError("theme_id was not found")
    if row[0] is not None and row[0] != law_id:
        raise ValueError("theme_id belongs to a different law_id")


WATCH_SELECT = """
SELECT w.watch_id, w.theme_id, w.law_id, l.law_num, latest.law_title,
       theme.title, w.baseline_revision_id, w.baseline_ingestion_run_id,
       w.enabled, w.last_evaluated_at, w.created_at, w.updated_at
FROM legal_kb.application_law_watch w
JOIN legal_kb.law l ON l.law_id = w.law_id
LEFT JOIN legal_kb.application_saved_theme theme ON theme.theme_id = w.theme_id
LEFT JOIN LATERAL (
    SELECT r.law_title FROM legal_kb.law_revision r
    WHERE r.law_id = w.law_id
    ORDER BY (r.current_revision_status = 'Current') DESC,
             r.revision_sequence DESC NULLS LAST,
             r.revision_id_effective_date DESC
    LIMIT 1
) latest ON true
"""
def _watch_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "watch_id": row[0],
        "theme_id": row[1],
        "law_id": row[2],
        "law_num": row[3],
        "law_title": row[4],
        "theme_title": row[5],
        "baseline_revision_id": row[6],
        "baseline_ingestion_run_id": row[7],
        "enabled": bool(row[8]),
        "last_evaluated_at": _iso(row[9]),
        "created_at": _iso(row[10]),
        "updated_at": _iso(row[11]),
    }


def get_watch(conn: Any, watch_id: str) -> dict[str, Any] | None:
    _validate_hex32(watch_id, field="watch_id")
    with conn.cursor() as cur:
        cur.execute(
            WATCH_SELECT + " WHERE w.workspace_id = %s AND w.watch_id = %s",
            (WORKSPACE_ID, watch_id),
        )
        row = cur.fetchone()
    return None if row is None else _watch_dict(row)


def list_watches(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            WATCH_SELECT + " WHERE w.workspace_id = %s ORDER BY w.updated_at DESC, w.watch_id",
            (WORKSPACE_ID,),
        )
        rows = cur.fetchall()
    return [_watch_dict(row) for row in rows]
def create_watch(
    conn: Any,
    *,
    law_id: str,
    theme_id: str | None = None,
) -> dict[str, Any]:
    law_id = _validate_law_id(law_id)
    if not _law_exists(conn, law_id):
        raise ValueError("law_id was not found")
    if theme_id is not None:
        _validate_theme_for_watch(conn, theme_id, law_id)

    watch_id = uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO legal_kb.application_law_watch
                (watch_id, workspace_id, theme_id, law_id)
            VALUES (%s, %s, %s, %s)
        """, (watch_id, WORKSPACE_ID, theme_id, law_id))
    watch = get_watch(conn, watch_id)
    if watch is None:
        raise RuntimeError("watch insert did not persist")
    return watch


def delete_watch(conn: Any, watch_id: str) -> bool:
    _validate_hex32(watch_id, field="watch_id")
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM legal_kb.application_law_watch
            WHERE workspace_id = %s AND watch_id = %s
        """, (WORKSPACE_ID, watch_id))
        return cur.rowcount > 0
def classify_watch_evaluation(
    baseline_revision_id: str | None,
    temporal_resolution: Any,
) -> str:
    status = str(temporal_resolution.status)
    if status != "resolved":
        return status
    selected = temporal_resolution.selected_revision_id
    if not selected:
        raise ValueError("resolved temporal result is missing selected_revision_id")
    if baseline_revision_id is None:
        return "initialized"
    if baseline_revision_id == selected:
        return "no-change"
    return "effective-change"


def _insert_effective_event(
    conn: Any,
    *,
    watch_id: str,
    from_revision_id: str,
    to_revision_id: str,
    source_ingestion_run_id: str,
) -> str:
    event_id = uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO legal_kb.application_law_watch_event
                (event_id, watch_id, event_type, from_revision_id, to_revision_id,
                 source_ingestion_run_id, temporal_status)
            VALUES (%s, %s, 'effective-change', %s, %s, %s, 'resolved')
            ON CONFLICT DO NOTHING
            RETURNING event_id
        """, (event_id, watch_id, from_revision_id, to_revision_id, source_ingestion_run_id))
        row = cur.fetchone()
    if row is not None:
        return str(row[0])
    with conn.cursor() as cur:
        cur.execute("""
            SELECT event_id
            FROM legal_kb.application_law_watch_event
            WHERE watch_id = %s
              AND event_type = 'effective-change'
              AND COALESCE(from_revision_id, '') = %s
              AND COALESCE(to_revision_id, '') = %s
              AND COALESCE(source_ingestion_run_id, '') = %s
            LIMIT 1
        """, (watch_id, from_revision_id, to_revision_id, source_ingestion_run_id))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("effective-change event insert was not recoverable")
    return str(row[0])


def _evaluation_response(
    watch: dict[str, Any],
    *,
    evaluation_date: date,
    state: str,
    temporal_resolution: Any,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "api_version": "1",
        "watch_id": watch["watch_id"],
        "law_id": watch["law_id"],
        "evaluation_date": evaluation_date.isoformat(),
        "state": state,
        "baseline_revision_id": watch.get("baseline_revision_id"),
        "temporal_resolution": temporal_resolution.to_dict(),
        "event_id": event_id,
        "source_truth": "phase3-phase5",
    }
def _revision_source_run(conn: Any, revision_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT first_seen_run_id
            FROM legal_kb.law_revision
            WHERE law_revision_id = %s
        """, (revision_id,))
        row = cur.fetchone()
    return None if row is None or row[0] is None else str(row[0])


def evaluate_watch(
    conn: Any,
    watch_id: str,
    *,
    evaluation_date: date,
    resolver: Any | None = None,
) -> dict[str, Any] | None:
    if not isinstance(evaluation_date, date):
        raise TypeError("evaluation_date must be datetime.date")
    watch = get_watch(conn, watch_id)
    if watch is None:
        return None

    resolve = resolver or TEMPORAL.resolve_as_of
    temporal = resolve(conn, watch["law_id"], evaluation_date)
    state = classify_watch_evaluation(watch.get("baseline_revision_id"), temporal)
    if state in {"ambiguous", "unresolved", "not-found"}:
        return _evaluation_response(
            watch, evaluation_date=evaluation_date, state=state, temporal_resolution=temporal
        )
    selected_revision_id = temporal.selected_revision_id
    if not selected_revision_id:
        raise RuntimeError("resolved temporal result has no selected revision")

    event_id = None
    if state == "initialized":
        baseline_run = _latest_successful_ingestion_run(conn)
        if baseline_run is None:
            raise RuntimeError("no successful ingestion run is available for watch baseline")
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE legal_kb.application_law_watch
                SET baseline_revision_id = %s,
                    baseline_ingestion_run_id = %s,
                    last_evaluated_at = now(),
                    updated_at = now()
                WHERE workspace_id = %s AND watch_id = %s
            """, (selected_revision_id, baseline_run, WORKSPACE_ID, watch_id))
        watch["baseline_revision_id"] = selected_revision_id
        watch["baseline_ingestion_run_id"] = baseline_run
    elif state == "no-change":
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE legal_kb.application_law_watch
                SET last_evaluated_at = now(), updated_at = now()
                WHERE workspace_id = %s AND watch_id = %s
            """, (WORKSPACE_ID, watch_id))
    elif state == "effective-change":
        from_revision_id = str(watch["baseline_revision_id"])
        source_run = _revision_source_run(conn, selected_revision_id)
        if source_run is None:
            raise RuntimeError("selected revision is missing first_seen_run_id provenance")
        event_id = _insert_effective_event(
            conn,
            watch_id=watch_id,
            from_revision_id=from_revision_id,
            to_revision_id=selected_revision_id,
            source_ingestion_run_id=source_run,
        )
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE legal_kb.application_law_watch
                SET baseline_revision_id = %s,
                    last_evaluated_at = now(),
                    updated_at = now()
                WHERE workspace_id = %s AND watch_id = %s
            """, (selected_revision_id, WORKSPACE_ID, watch_id))
        watch["baseline_revision_id"] = selected_revision_id
    else:
        raise RuntimeError(f"unexpected watch evaluation state: {state}")

    return _evaluation_response(
        watch,
        evaluation_date=evaluation_date,
        state=state,
        temporal_resolution=temporal,
        event_id=event_id,
    )


def evaluate_all_watches(
    conn: Any,
    *,
    evaluation_date: date,
    resolver: Any | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT watch_id
            FROM legal_kb.application_law_watch
            WHERE workspace_id = %s AND enabled = true
            ORDER BY created_at, watch_id
        """, (WORKSPACE_ID,))
        watch_ids = [str(row[0]) for row in cur.fetchall()]
    results = []
    for watch_id in watch_ids:
        result = evaluate_watch(
            conn, watch_id, evaluation_date=evaluation_date, resolver=resolver
        )
        if result is not None:
            results.append(result)
    return results
WATCH_STATE_RELATIONS = (
    "application_law_watch",
    "application_law_watch_event",
)


def watch_state_ready(conn: Any) -> bool:
    with conn.cursor() as cur:
        for name in WATCH_STATE_RELATIONS:
            cur.execute("SELECT to_regclass(%s)", (f"legal_kb.{name}",))
            if cur.fetchone()[0] is None:
                return False
    return True
