from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import re
import sys
import uuid
from typing import Any
from urllib.parse import urlencode

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


def _latest_successful_ingestion_run_info(conn: Any) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ingestion_run_id, started_at, completed_at, result_status,
                   input_manifest_sha256
            FROM legal_kb.ingestion_run
            WHERE result_status = 'succeeded'
            ORDER BY completed_at DESC NULLS LAST, started_at DESC, ingestion_run_id DESC
            LIMIT 1
        """)
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "ingestion_run_id": str(row[0]),
        "started_at": _iso(row[1]),
        "completed_at": _iso(row[2]),
        "result_status": row[3],
        "input_manifest_sha256": row[4],
    }


def _latest_successful_ingestion_run(conn: Any) -> str | None:
    info = _latest_successful_ingestion_run_info(conn)
    return None if info is None else info["ingestion_run_id"]
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


def _observed_revisions_since(
    conn: Any,
    *,
    law_id: str,
    baseline_run_id: str,
    through_run_id: str,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            WITH bounds AS (
                SELECT base.started_at AS baseline_started_at,
                       current.started_at AS through_started_at
                FROM legal_kb.ingestion_run base
                CROSS JOIN legal_kb.ingestion_run current
                WHERE base.ingestion_run_id = %s
                  AND current.ingestion_run_id = %s
            )
            SELECT lr.law_revision_id, lr.revision_sequence,
                   lr.revision_id_effective_date, lr.revision_date_kind,
                   lr.law_title, lr.amendment_promulgate_date,
                   lr.amendment_enforcement_date,
                   lr.amendment_scheduled_enforcement_date,
                   lr.amendment_law_id, lr.amendment_law_num,
                   lr.amendment_law_title, lr.first_seen_run_id,
                   first_run.started_at, first_run.completed_at,
                   first_run.result_status, first_run.input_manifest_sha256
            FROM legal_kb.law_revision lr
            JOIN legal_kb.ingestion_run first_run
              ON first_run.ingestion_run_id = lr.first_seen_run_id
            CROSS JOIN bounds
            WHERE lr.law_id = %s
              AND (first_run.started_at, first_run.ingestion_run_id)
                  > (bounds.baseline_started_at, %s)
              AND (first_run.started_at, first_run.ingestion_run_id)
                  <= (bounds.through_started_at, %s)
            ORDER BY first_run.started_at, first_run.ingestion_run_id,
                     lr.revision_sequence NULLS LAST, lr.law_revision_id
        """, (
            baseline_run_id, through_run_id, law_id,
            baseline_run_id, through_run_id,
        ))
        names = [column.name for column in cur.description]
        rows = [dict(zip(names, row)) for row in cur.fetchall()]
    return rows


def _future_scheduled_changes(
    conn: Any,
    *,
    law_id: str,
    evaluation_date: date,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT lr.law_revision_id, lr.revision_sequence,
                   lr.law_title, lr.revision_id_effective_date,
                   lr.revision_date_kind, lr.amendment_promulgate_date,
                   lr.amendment_enforcement_date,
                   lr.amendment_scheduled_enforcement_date,
                   lr.amendment_law_id, lr.amendment_law_num,
                   lr.amendment_law_title, lr.first_seen_run_id,
                   first_run.started_at, first_run.completed_at,
                   first_run.result_status, first_run.input_manifest_sha256
            FROM legal_kb.law_revision lr
            LEFT JOIN legal_kb.ingestion_run first_run
              ON first_run.ingestion_run_id = lr.first_seen_run_id
            WHERE lr.law_id = %s
              AND lr.amendment_scheduled_enforcement_date > %s
            ORDER BY lr.amendment_scheduled_enforcement_date,
                     lr.revision_sequence NULLS LAST, lr.law_revision_id
        """, (law_id, evaluation_date))
        names = [column.name for column in cur.description]
        rows = [dict(zip(names, row)) for row in cur.fetchall()]
    return [_scheduled_change_dict(row) for row in rows]


def _scheduled_change_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": "scheduled-change",
        "law_revision_id": row["law_revision_id"],
        "revision_sequence": row.get("revision_sequence"),
        "law_title": row.get("law_title"),
        "revision_id_effective_date": _iso(row.get("revision_id_effective_date")),
        "revision_date_kind": row.get("revision_date_kind"),
        "amendment_promulgate_date": _iso(row.get("amendment_promulgate_date")),
        "amendment_enforcement_date": _iso(row.get("amendment_enforcement_date")),
        "scheduled_enforcement_date": _iso(row.get("amendment_scheduled_enforcement_date")),
        "amendment_law_id": row.get("amendment_law_id"),
        "amendment_law_num": row.get("amendment_law_num"),
        "amendment_law_title": row.get("amendment_law_title"),
        "revision_first_seen_run": {
            "ingestion_run_id": row.get("first_seen_run_id"),
            "started_at": _iso(row.get("started_at")),
            "completed_at": _iso(row.get("completed_at")),
            "result_status": row.get("result_status"),
            "input_manifest_sha256": row.get("input_manifest_sha256"),
        },
        "source_truth": "phase3-law-revision",
        "legal_deadline": False,
    }


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


def _insert_change_event(
    conn: Any,
    *,
    watch_id: str,
    event_type: str,
    from_revision_id: str | None,
    to_revision_id: str | None,
    source_ingestion_run_id: str | None,
    temporal_status: str,
    effective_date: date | None = None,
) -> str:
    if event_type not in {"observed-change", "effective-change", "scheduled-change"}:
        raise ValueError("unsupported watch event type")
    event_id = uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO legal_kb.application_law_watch_event
                (event_id, watch_id, event_type, from_revision_id, to_revision_id,
                 effective_date, source_ingestion_run_id, temporal_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING event_id
        """, (
            event_id, watch_id, event_type, from_revision_id, to_revision_id,
            effective_date, source_ingestion_run_id, temporal_status,
        ))
        row = cur.fetchone()
    if row is not None:
        return str(row[0])
    with conn.cursor() as cur:
        cur.execute("""
            SELECT event_id
            FROM legal_kb.application_law_watch_event
            WHERE watch_id = %s
              AND event_type = %s
              AND COALESCE(from_revision_id, '') = COALESCE(%s, '')
              AND COALESCE(to_revision_id, '') = COALESCE(%s, '')
              AND COALESCE(source_ingestion_run_id, '') = COALESCE(%s, '')
            LIMIT 1
        """, (
            watch_id, event_type, from_revision_id, to_revision_id,
            source_ingestion_run_id,
        ))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("watch event insert was not recoverable")
    return str(row[0])


def _insert_effective_event(
    conn: Any,
    *,
    watch_id: str,
    from_revision_id: str,
    to_revision_id: str,
    source_ingestion_run_id: str,
) -> str:
    return _insert_change_event(
        conn,
        watch_id=watch_id,
        event_type="effective-change",
        from_revision_id=from_revision_id,
        to_revision_id=to_revision_id,
        source_ingestion_run_id=source_ingestion_run_id,
        temporal_status="resolved",
    )


EVENT_SELECT = """
SELECT e.event_id, e.watch_id, e.event_type,
       e.from_revision_id, e.to_revision_id,
       e.detected_at, e.effective_date,
       e.source_ingestion_run_id, e.temporal_status, e.acknowledged_at,
       source_run.started_at, source_run.completed_at,
       source_run.result_status, source_run.input_manifest_sha256,
       from_rev.revision_id_effective_date AS from_effective_date,
       from_rev.revision_date_kind AS from_revision_date_kind,
       to_rev.law_title AS to_law_title,
       to_rev.revision_id_effective_date AS to_effective_date,
       to_rev.revision_date_kind AS to_revision_date_kind,
       to_rev.amendment_promulgate_date,
       to_rev.amendment_enforcement_date,
       to_rev.amendment_scheduled_enforcement_date,
       to_rev.amendment_law_id, to_rev.amendment_law_num,
       to_rev.amendment_law_title, to_rev.first_seen_run_id,
       w.law_id, from_rev.valid_from AS from_valid_from,
       to_rev.valid_from AS to_valid_from
FROM legal_kb.application_law_watch_event e
JOIN legal_kb.application_law_watch w ON w.watch_id = e.watch_id
LEFT JOIN legal_kb.ingestion_run source_run
  ON source_run.ingestion_run_id = e.source_ingestion_run_id
LEFT JOIN legal_kb.law_revision from_rev
  ON from_rev.law_revision_id = e.from_revision_id
LEFT JOIN legal_kb.law_revision to_rev
  ON to_rev.law_revision_id = e.to_revision_id
"""


def _event_navigation(row: tuple[Any, ...]) -> dict[str, Any]:
    law_id = str(row[26])
    from_date = _iso(row[27])
    to_date = _iso(row[28])
    history = None
    related = None
    compare = None
    if to_date:
        history = {
            "path": f"/api/v1/laws/{law_id}/history?" + urlencode({"as_of_date": to_date}),
            "as_of_date": to_date,
        }
        related = {
            "path": f"/api/v1/laws/{law_id}/related-materials?" + urlencode({"as_of_date": to_date}),
            "as_of_date": to_date,
            "relation_status": "confirmed",
        }
    if row[2] == "effective-change" and from_date and to_date:
        compare = {
            "path": f"/api/v1/laws/{law_id}/compare?" + urlencode({"from_date": from_date, "to_date": to_date}),
            "from_date": from_date,
            "to_date": to_date,
        }
    return {
        "history": history,
        "compare": compare,
        "confirmed_related_materials": related,
    }


def _event_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "event_id": row[0],
        "watch_id": row[1],
        "event_type": row[2],
        "from_revision_id": row[3],
        "to_revision_id": row[4],
        "detected_at": _iso(row[5]),
        "effective_date": _iso(row[6]),
        "temporal_status": row[8],
        "acknowledged_at": _iso(row[9]),
        "acknowledged": row[9] is not None,
        "law_id": row[26],
        "navigation": _event_navigation(row),
        "source_ingestion_run": {
            "ingestion_run_id": row[7],
            "started_at": _iso(row[10]),
            "completed_at": _iso(row[11]),
            "result_status": row[12],
            "input_manifest_sha256": row[13],
        },
        "from_revision": None if row[3] is None else {
            "law_revision_id": row[3],
            "revision_id_effective_date": _iso(row[14]),
            "revision_date_kind": row[15],
        },
        "to_revision": None if row[4] is None else {
            "law_revision_id": row[4],
            "law_title": row[16],
            "revision_id_effective_date": _iso(row[17]),
            "revision_date_kind": row[18],
            "amendment_promulgate_date": _iso(row[19]),
            "amendment_enforcement_date": _iso(row[20]),
            "amendment_scheduled_enforcement_date": _iso(row[21]),
            "amendment_law_id": row[22],
            "amendment_law_num": row[23],
            "amendment_law_title": row[24],
            "first_seen_run_id": row[25],
        },
        "source_truth": "phase7-application-event",
        "law_revision_truth": "phase3-law-revision",
    }


def get_watch_event(conn: Any, event_id: str) -> dict[str, Any] | None:
    _validate_hex32(event_id, field="event_id")
    with conn.cursor() as cur:
        cur.execute(
            EVENT_SELECT + " WHERE w.workspace_id = %s AND e.event_id = %s",
            (WORKSPACE_ID, event_id),
        )
        row = cur.fetchone()
    return None if row is None else _event_dict(row)


def acknowledge_watch_event(conn: Any, event_id: str) -> dict[str, Any] | None:
    _validate_hex32(event_id, field="event_id")
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE legal_kb.application_law_watch_event e
            SET acknowledged_at = COALESCE(e.acknowledged_at, now())
            FROM legal_kb.application_law_watch w
            WHERE e.watch_id = w.watch_id
              AND w.workspace_id = %s
              AND e.event_id = %s
            RETURNING e.event_id
        """, (WORKSPACE_ID, event_id))
        row = cur.fetchone()
    if row is None:
        return None
    event = get_watch_event(conn, event_id)
    if event is None:
        raise RuntimeError("acknowledged event could not be reconstructed")
    return event


def list_watch_events(
    conn: Any,
    watch_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]] | None:
    _validate_hex32(watch_id, field="watch_id")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise ValueError("limit must be an integer from 1 to 200")
    if get_watch(conn, watch_id) is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            EVENT_SELECT + " WHERE w.workspace_id = %s AND e.watch_id = %s "
            "ORDER BY e.detected_at DESC, e.event_id DESC LIMIT %s",
            (WORKSPACE_ID, watch_id, limit),
        )
        rows = cur.fetchall()
    return [_event_dict(row) for row in rows]


def _evaluation_response(
    watch: dict[str, Any],
    *,
    evaluation_date: date,
    state: str,
    temporal_resolution: Any,
    event_id: str | None = None,
    observed_changes: list[dict[str, Any]] | None = None,
    effective_change: dict[str, Any] | None = None,
    scheduled_changes: list[dict[str, Any]] | None = None,
    evaluated_through_ingestion_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "api_version": "1",
        "watch_id": watch["watch_id"],
        "law_id": watch["law_id"],
        "evaluation_date": evaluation_date.isoformat(),
        "state": state,
        "baseline_revision_id": watch.get("baseline_revision_id"),
        "baseline_ingestion_run_id": watch.get("baseline_ingestion_run_id"),
        "temporal_resolution": temporal_resolution.to_dict(),
        "event_id": event_id,
        "change_evidence": {
            "observed_changes": observed_changes or [],
            "effective_change": effective_change,
            "scheduled_changes": scheduled_changes or [],
            "evaluated_through_ingestion_run": evaluated_through_ingestion_run,
            "scheduled_changes_are_legal_deadlines": False,
        },
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

    scheduled_changes = _future_scheduled_changes(
        conn, law_id=watch["law_id"], evaluation_date=evaluation_date
    )
    resolve = resolver or TEMPORAL.resolve_as_of
    temporal = resolve(conn, watch["law_id"], evaluation_date)
    state = classify_watch_evaluation(watch.get("baseline_revision_id"), temporal)
    if state in {"ambiguous", "unresolved", "not-found"}:
        return _evaluation_response(
            watch,
            evaluation_date=evaluation_date,
            state=state,
            temporal_resolution=temporal,
            scheduled_changes=scheduled_changes,
        )

    selected_revision_id = temporal.selected_revision_id
    if not selected_revision_id:
        raise RuntimeError("resolved temporal result has no selected revision")
    latest_run = _latest_successful_ingestion_run_info(conn)
    if latest_run is None:
        raise RuntimeError("no successful ingestion run is available for watch evaluation")
    latest_run_id = str(latest_run["ingestion_run_id"])

    if state == "initialized":
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE legal_kb.application_law_watch
                SET baseline_revision_id = %s,
                    baseline_ingestion_run_id = %s,
                    last_evaluated_at = now(),
                    updated_at = now()
                WHERE workspace_id = %s AND watch_id = %s
            """, (selected_revision_id, latest_run_id, WORKSPACE_ID, watch_id))
        watch["baseline_revision_id"] = selected_revision_id
        watch["baseline_ingestion_run_id"] = latest_run_id
        return _evaluation_response(
            watch,
            evaluation_date=evaluation_date,
            state=state,
            temporal_resolution=temporal,
            scheduled_changes=scheduled_changes,
            evaluated_through_ingestion_run=latest_run,
        )

    baseline_run_id = watch.get("baseline_ingestion_run_id")
    if not baseline_run_id:
        raise RuntimeError("watch baseline is missing ingestion provenance")

    observed_rows = []
    if baseline_run_id != latest_run_id:
        observed_rows = _observed_revisions_since(
            conn,
            law_id=watch["law_id"],
            baseline_run_id=str(baseline_run_id),
            through_run_id=latest_run_id,
        )
    observed_events: list[dict[str, Any]] = []
    for row in observed_rows:
        source_run_id = row.get("first_seen_run_id")
        if not source_run_id:
            raise RuntimeError("observed revision is missing first_seen_run_id provenance")
        observed_event_id = _insert_change_event(
            conn,
            watch_id=watch_id,
            event_type="observed-change",
            from_revision_id=None,
            to_revision_id=str(row["law_revision_id"]),
            source_ingestion_run_id=str(source_run_id),
            temporal_status="resolved",
        )
        event = get_watch_event(conn, observed_event_id)
        if event is None:
            raise RuntimeError("observed-change event could not be reconstructed")
        observed_events.append(event)

    event_id = None
    effective_event = None
    if state == "effective-change":
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
        effective_event = get_watch_event(conn, event_id)
        if effective_event is None:
            raise RuntimeError("effective-change event could not be reconstructed")

    with conn.cursor() as cur:
        if state == "effective-change":
            cur.execute("""
                UPDATE legal_kb.application_law_watch
                SET baseline_revision_id = %s,
                    baseline_ingestion_run_id = %s,
                    last_evaluated_at = now(),
                    updated_at = now()
                WHERE workspace_id = %s AND watch_id = %s
            """, (
                selected_revision_id, latest_run_id, WORKSPACE_ID, watch_id,
            ))
            watch["baseline_revision_id"] = selected_revision_id
        elif state == "no-change":
            cur.execute("""
                UPDATE legal_kb.application_law_watch
                SET baseline_ingestion_run_id = %s,
                    last_evaluated_at = now(),
                    updated_at = now()
                WHERE workspace_id = %s AND watch_id = %s
            """, (latest_run_id, WORKSPACE_ID, watch_id))
        else:
            raise RuntimeError(f"unexpected watch evaluation state: {state}")
    watch["baseline_ingestion_run_id"] = latest_run_id

    return _evaluation_response(
        watch,
        evaluation_date=evaluation_date,
        state=state,
        temporal_resolution=temporal,
        event_id=event_id,
        observed_changes=observed_events,
        effective_change=effective_event,
        scheduled_changes=scheduled_changes,
        evaluated_through_ingestion_run=latest_run,
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
