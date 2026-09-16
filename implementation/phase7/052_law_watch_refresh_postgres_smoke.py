from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


WATCH = _load('phase76d_smoke_watch', '038_law_watch_service.py')
REFRESH = _load('phase76d_smoke_refresh', '048_law_watch_refresh_service.py')


def counts(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM legal_kb.application_law_watch')
        watches = int(cur.fetchone()[0])
        cur.execute('SELECT count(*) FROM legal_kb.application_law_watch_event')
        events = int(cur.fetchone()[0])
    return watches, events


def run(database_url: str, law_id: str) -> dict:
    import psycopg

    with psycopg.connect(database_url) as before_conn:
        before = counts(before_conn)

    watch_id = uuid.uuid4().hex
    event_id = uuid.uuid4().hex
    result = {"status": "passed", "law_id": law_id, "database_url_recorded": False}

    conn = psycopg.connect(database_url)
    try:
        conn.execute('BEGIN')
        with conn.cursor() as cur:
            cur.execute('SELECT law_revision_id FROM legal_kb.law_revision WHERE law_id=%s ORDER BY revision_sequence DESC NULLS LAST LIMIT 1', (law_id,))
            revision_id = cur.fetchone()[0]
            cur.execute("SELECT ingestion_run_id FROM legal_kb.ingestion_run WHERE result_status='succeeded' ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1")
            run_id = cur.fetchone()[0]
            cur.execute('''INSERT INTO legal_kb.application_law_watch
                (watch_id,workspace_id,law_id,baseline_revision_id,baseline_ingestion_run_id,enabled)
                VALUES (%s,'local',%s,%s,%s,true)''', (watch_id, law_id, revision_id, run_id))
            cur.execute('''INSERT INTO legal_kb.application_law_watch_event
                (event_id,watch_id,event_type,to_revision_id,source_ingestion_run_id,temporal_status)
                VALUES (%s,%s,'observed-change',%s,%s,'resolved')''', (event_id, watch_id, revision_id, run_id))
        law_ids = REFRESH.enabled_watch_law_ids(conn)
        if law_id not in law_ids:
            raise AssertionError('enabled watch law_id was not selected')
        watches = WATCH.list_watches(conn)
        inserted = next((item for item in watches if item['watch_id'] == watch_id), None)
        if inserted is None:
            raise AssertionError('inserted watch was not listed')
        if inserted['unacknowledged_event_count'] != 1:
            raise AssertionError('unacknowledged event count was not projected')
        if not inserted['last_unacknowledged_at']:
            raise AssertionError('last_unacknowledged_at was not projected')

        first_lock = REFRESH.try_refresh_lock(conn)
        if not first_lock:
            raise AssertionError('first advisory lock acquisition failed')
        second_conn = psycopg.connect(database_url)
        try:
            second_lock = REFRESH.try_refresh_lock(second_conn)
        finally:
            second_conn.close()
        if second_lock:
            raise AssertionError('concurrent advisory lock was not rejected')
        REFRESH.release_refresh_lock(conn)

        result.update({
            'enabled_watch_selected': True,
            'unacknowledged_event_count': inserted['unacknowledged_event_count'],
            'advisory_lock_conflict_rejected': True,
        })
    finally:
        conn.rollback()
        conn.close()

    with psycopg.connect(database_url) as after_conn:
        after = counts(after_conn)
    result['rollback_preserved_application_state_counts'] = after == before
    if after != before:
        raise AssertionError('refresh smoke left application state behind')
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--database-url', default=os.environ.get('LEGAL_KB_DATABASE_URL'))
    parser.add_argument('--law-id', default='129AC0000000089')
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit('LEGAL_KB_DATABASE_URL or --database-url is required')
    print(json.dumps(
        run(args.database_url, args.law_id),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == '__main__':
    main()
