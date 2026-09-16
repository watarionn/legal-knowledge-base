from __future__ import annotations

import argparse
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
SERVICE_PATH = HERE / "038_law_watch_service.py"


def _load_service():
    spec = importlib.util.spec_from_file_location(
        "phase76b_watch_smoke_service", SERVICE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load law watch service")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _counts(conn) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM legal_kb.application_law_watch")
        watches = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM legal_kb.application_law_watch_event")
        events = int(cur.fetchone()[0])
    return watches, events


def _insert_synthetic_success_run(conn, baseline_run_id: str) -> str:
    run_id = "phase76b-smoke-" + uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute("""
            SELECT max(started_at), max(COALESCE(completed_at, started_at))
            FROM legal_kb.ingestion_run
        """)
        max_started, max_completed = cur.fetchone()
        if max_started is None or max_completed is None:
            raise RuntimeError("ingestion_run is empty")
        cur.execute("""
            INSERT INTO legal_kb.ingestion_run
                (ingestion_run_id, started_at, completed_at, result_status)
            VALUES (%s, %s + interval '1 second', %s + interval '1 second', 'succeeded')
        """, (run_id, max_started, max_completed))
    return run_id


def _pick_other_revision(conn, law_id: str, selected_revision_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT law_revision_id
            FROM legal_kb.law_revision
            WHERE law_id = %s AND law_revision_id <> %s
            ORDER BY revision_sequence DESC NULLS LAST, law_revision_id DESC
            LIMIT 1
        """, (law_id, selected_revision_id))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("law needs at least two revisions for observed smoke")
    return str(row[0])


def _find_two_resolved_dates(service, conn, law_id: str) -> tuple[date, date]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT valid_from
            FROM legal_kb.law_revision
            WHERE law_id = %s AND valid_from IS NOT NULL
            ORDER BY valid_from DESC
            LIMIT 40
        """, (law_id,))
        candidates = [row[0] for row in cur.fetchall()]
    resolved: list[tuple[date, str]] = []
    for when in candidates:
        result = service.TEMPORAL.resolve_as_of(conn, law_id, when)
        if result.status == "resolved" and result.selected_revision_id:
            if all(item[1] != result.selected_revision_id for item in resolved):
                resolved.append((when, result.selected_revision_id))
        if len(resolved) >= 2:
            break
    if len(resolved) < 2:
        raise RuntimeError("could not find two resolved revision dates")
    newer, older = resolved[0], resolved[1]
    return older[0], newer[0]


def _find_scheduled_law(conn, evaluation_date: date) -> str | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT law_id
            FROM legal_kb.law_revision
            WHERE amendment_scheduled_enforcement_date > %s
            ORDER BY amendment_scheduled_enforcement_date, law_id
            LIMIT 1
        """, (evaluation_date,))
        row = cur.fetchone()
    return None if row is None else str(row[0])


def run(database_url: str, *, law_id: str, evaluation_date: date) -> dict:
    import psycopg

    service = _load_service()
    with psycopg.connect(database_url) as conn:
        if not service.watch_state_ready(conn):
            raise RuntimeError("law watch schema is not ready")
        before_counts = _counts(conn)
        conn.rollback()

    result: dict[str, object] = {}
    observed_revision_id = None
    original_first_seen_run_id = None
    synthetic_run_id = None
    with psycopg.connect(database_url) as conn:
        created = service.create_watch(conn, law_id=law_id)
        initialized = service.evaluate_watch(
            conn, created["watch_id"], evaluation_date=evaluation_date
        )
        if initialized is None or initialized["state"] != "initialized":
            raise AssertionError("watch did not initialize")
        selected_revision_id = str(initialized["baseline_revision_id"])
        baseline_run_id = str(initialized["baseline_ingestion_run_id"])

        synthetic_run_id = _insert_synthetic_success_run(conn, baseline_run_id)
        observed_revision_id = _pick_other_revision(conn, law_id, selected_revision_id)
        with conn.cursor() as cur:
            cur.execute("SELECT first_seen_run_id FROM legal_kb.law_revision WHERE law_revision_id = %s", (observed_revision_id,))
            original_first_seen_run_id = cur.fetchone()[0]
            cur.execute("""
                UPDATE legal_kb.law_revision
                SET first_seen_run_id = %s
                WHERE law_revision_id = %s
            """, (synthetic_run_id, observed_revision_id))

        observed = service.evaluate_watch(
            conn, created["watch_id"], evaluation_date=evaluation_date
        )
        observed_again = service.evaluate_watch(
            conn, created["watch_id"], evaluation_date=evaluation_date
        )
        observed_items = observed["change_evidence"]["observed_changes"]
        if observed["state"] != "no-change" or len(observed_items) != 1:
            raise AssertionError("observed-change was not isolated from effective-change")
        if observed_items[0]["to_revision_id"] != observed_revision_id:
            raise AssertionError("observed event points to the wrong revision")
        if observed["change_evidence"]["effective_change"] is not None:
            raise AssertionError("observed-only evaluation produced effective-change")
        if observed_again["change_evidence"]["observed_changes"]:
            raise AssertionError("observed-change was duplicated on repeat evaluation")
        events = service.list_watch_events(conn, created["watch_id"])
        if events is None or not any(e["event_type"] == "observed-change" for e in events):
            raise AssertionError("observed event could not be reconstructed")

        old_date, new_date = _find_two_resolved_dates(service, conn, law_id)
        effective_watch = service.create_watch(conn, law_id=law_id)
        older = service.evaluate_watch(
            conn, effective_watch["watch_id"], evaluation_date=old_date
        )
        newer = service.evaluate_watch(
            conn, effective_watch["watch_id"], evaluation_date=new_date
        )
        if older is None or newer is None:
            raise AssertionError("effective-change smoke watch disappeared")
        if older["state"] != "initialized" or newer["state"] != "effective-change":
            raise AssertionError("strict resolver did not produce effective-change")
        effective_event = newer["change_evidence"]["effective_change"]
        if not effective_event or effective_event["event_type"] != "effective-change":
            raise AssertionError("effective-change evidence was not reconstructed")

        scheduled_law_id = _find_scheduled_law(conn, evaluation_date)
        scheduled_count = 0
        if scheduled_law_id is not None:
            scheduled_watch = service.create_watch(conn, law_id=scheduled_law_id)
            scheduled_result = service.evaluate_watch(
                conn, scheduled_watch["watch_id"], evaluation_date=evaluation_date
            )
            if scheduled_result is None:
                raise AssertionError("scheduled watch disappeared")
            scheduled_items = scheduled_result["change_evidence"]["scheduled_changes"]
            scheduled_count = len(scheduled_items)
            if not scheduled_items or any(item["legal_deadline"] for item in scheduled_items):
                raise AssertionError("scheduled dates were not exposed safely")

        result = {
            "status": "passed",
            "law_id": law_id,
            "evaluation_date": evaluation_date.isoformat(),
            "observed_revision_id": observed_revision_id,
            "observed_event_count": len(observed_items),
            "repeat_observed_event_count": len(
                observed_again["change_evidence"]["observed_changes"]
            ),
            "effective_from_date": old_date.isoformat(),
            "effective_to_date": new_date.isoformat(),
            "effective_event_type": effective_event["event_type"],
            "scheduled_law_id": scheduled_law_id,
            "scheduled_change_count": scheduled_count,
            "database_url_recorded": False,
        }
        conn.rollback()

    with psycopg.connect(database_url) as conn:
        after_counts = _counts(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM legal_kb.ingestion_run WHERE ingestion_run_id = %s", (synthetic_run_id,))
            synthetic_run_exists = cur.fetchone() is not None
            cur.execute("SELECT first_seen_run_id FROM legal_kb.law_revision WHERE law_revision_id = %s", (observed_revision_id,))
            restored_first_seen_run_id = cur.fetchone()[0]
    result["rollback_preserved_application_state_counts"] = after_counts == before_counts
    result["synthetic_ingestion_run_rolled_back"] = not synthetic_run_exists
    result["revision_provenance_restored"] = restored_first_seen_run_id == original_first_seen_run_id
    if after_counts != before_counts:
        raise AssertionError("law watch smoke left application state behind")
    if synthetic_run_exists:
        raise AssertionError("synthetic ingestion run survived rollback")
    if restored_first_seen_run_id != original_first_seen_run_id:
        raise AssertionError("revision provenance was not restored by rollback")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("LEGAL_KB_DATABASE_URL"))
    parser.add_argument("--law-id", default="129AC0000000089")
    parser.add_argument("--evaluation-date", default=date.today().isoformat())
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("LEGAL_KB_DATABASE_URL or --database-url is required")
    try:
        evaluation_date = date.fromisoformat(args.evaluation_date)
    except ValueError as exc:
        raise SystemExit("--evaluation-date must be YYYY-MM-DD") from exc
    print(json.dumps(
        run(args.database_url, law_id=args.law_id, evaluation_date=evaluation_date),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
