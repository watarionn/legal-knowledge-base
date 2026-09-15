from __future__ import annotations

import argparse
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "037_law_watch_schema.sql"
SERVICE_PATH = HERE / "038_law_watch_service.py"


def _load_service():
    spec = importlib.util.spec_from_file_location("phase76_watch_smoke_service", SERVICE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load law watch service")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _schema_sql() -> str:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    return sql.replace("BEGIN;", "", 1).rsplit("COMMIT;", 1)[0]
def _relation_state(conn) -> tuple[bool, bool]:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('legal_kb.application_law_watch')")
        watch_exists = cur.fetchone()[0] is not None
        cur.execute("SELECT to_regclass('legal_kb.application_law_watch_event')")
        event_exists = cur.fetchone()[0] is not None
    return watch_exists, event_exists


def run(database_url: str, *, law_id: str, evaluation_date: date) -> dict:
    import psycopg

    service = _load_service()
    before_state = None
    result = {}
    with psycopg.connect(database_url) as conn:
        before_state = _relation_state(conn)
        if before_state[0] != before_state[1]:
            raise RuntimeError("partial law watch schema exists")
        if not before_state[0]:
            with conn.cursor() as cur:
                cur.execute(_schema_sql())
        if not service.watch_state_ready(conn):
            raise RuntimeError("law watch schema is not ready")
        created = service.create_watch(conn, law_id=law_id)
        first = service.evaluate_watch(
            conn, created["watch_id"], evaluation_date=evaluation_date
        )
        second = service.evaluate_watch(
            conn, created["watch_id"], evaluation_date=evaluation_date
        )
        listed = service.list_watches(conn)
        removed = service.delete_watch(conn, created["watch_id"])
        result = {
            "status": "passed",
            "schema_was_present": before_state[0],
            "law_id": law_id,
            "evaluation_date": evaluation_date.isoformat(),
            "first_state": first["state"],
            "first_baseline_revision_id": first["baseline_revision_id"],
            "second_state": second["state"],
            "listed_count": len(listed),
            "removed": removed,
            "database_url_recorded": False,
        }
        if first["state"] != "initialized" or second["state"] != "no-change":
            raise AssertionError("unexpected deterministic watch states")
        conn.rollback()
    with psycopg.connect(database_url) as conn:
        after_state = _relation_state(conn)
    result["schema_restored_after_rollback"] = after_state == before_state
    if after_state != before_state:
        raise AssertionError("law watch smoke did not restore original schema state")
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
