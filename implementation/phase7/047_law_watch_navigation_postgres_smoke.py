import argparse
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


WATCH = _load("phase76c_watch_smoke", "038_law_watch_service.py")
COMPARE = _load("phase76c_compare_smoke", "017_article_compare_service.py")
RELATED = _load("phase76c_related_smoke", "022_related_material_service.py")


def _counts(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM legal_kb.application_law_watch")
        watches = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM legal_kb.application_law_watch_event")
        events = int(cur.fetchone()[0])
    return watches, events


def _find_two_resolved_dates(conn, law_id: str):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT valid_from
            FROM legal_kb.law_revision
            WHERE law_id = %s AND valid_from IS NOT NULL
            ORDER BY valid_from DESC
            LIMIT 40
        """, (law_id,))
        candidates = [row[0] for row in cur.fetchall()]
    resolved = []
    for when in candidates:
        result = WATCH.TEMPORAL.resolve_as_of(conn, law_id, when)
        if result.status == "resolved" and result.selected_revision_id:
            if all(item[1] != result.selected_revision_id for item in resolved):
                resolved.append((when, result.selected_revision_id))
        if len(resolved) >= 2:
            break
    if len(resolved) < 2:
        raise RuntimeError("could not find two resolved revision dates")
    newer, older = resolved[0], resolved[1]
    return older[0], newer[0]


def _assert_confirmed_only(payload):
    if payload.get("include_nonconfirmed"):
        raise AssertionError("related materials unexpectedly included nonconfirmed relations")
    for material in payload.get("materials", []):
        for relation in material.get("relations", []):
            if relation.get("effective_state") != "confirmed":
                raise AssertionError("non-confirmed relation leaked into default navigation")


def run(database_url: str, *, law_id: str) -> dict:
    import psycopg

    with psycopg.connect(database_url) as conn:
        if not WATCH.watch_state_ready(conn):
            raise RuntimeError("law watch schema is not ready")
        before_counts = _counts(conn)
        conn.rollback()

    result = {}
    with psycopg.connect(database_url) as conn:
        old_date, new_date = _find_two_resolved_dates(conn, law_id)
        created = WATCH.create_watch(conn, law_id=law_id)
        older = WATCH.evaluate_watch(
            conn, created["watch_id"], evaluation_date=old_date
        )
        newer = WATCH.evaluate_watch(
            conn, created["watch_id"], evaluation_date=new_date
        )
        if older is None or newer is None:
            raise AssertionError("watch disappeared during navigation smoke")
        if older["state"] != "initialized" or newer["state"] != "effective-change":
            raise AssertionError("could not produce effective-change")
        event = newer["change_evidence"]["effective_change"]
        if not event:
            raise AssertionError("effective-change event missing")

        compare_nav = event["navigation"]["compare"]
        related_nav = event["navigation"]["confirmed_related_materials"]
        if not compare_nav or not related_nav:
            raise AssertionError("navigation metadata missing")
        compare_qs = parse_qs(urlsplit(compare_nav["path"]).query)
        related_qs = parse_qs(urlsplit(related_nav["path"]).query)
        compare_from = date.fromisoformat(compare_qs["from_date"][-1])
        compare_to = date.fromisoformat(compare_qs["to_date"][-1])
        related_date = date.fromisoformat(related_qs["as_of_date"][-1])

        comparison = COMPARE.get_article_comparison(
            conn, law_id, from_date=compare_from, to_date=compare_to
        )
        if comparison["from"]["law_revision_id"] != event["from_revision_id"]:
            raise AssertionError("compare navigation resolved the wrong from revision")
        if comparison["to"]["law_revision_id"] != event["to_revision_id"]:
            raise AssertionError("compare navigation resolved the wrong to revision")

        related = RELATED.get_related_materials(
            conn, law_id, as_of_date=related_date, include_nonconfirmed=False
        )
        if related is None:
            raise AssertionError("related navigation law was not found")
        _assert_confirmed_only(related)

        ack1 = WATCH.acknowledge_watch_event(conn, event["event_id"])
        ack2 = WATCH.acknowledge_watch_event(conn, event["event_id"])
        if not ack1 or not ack2:
            raise AssertionError("acknowledge lost the event")
        if not ack1["acknowledged"] or not ack1["acknowledged_at"]:
            raise AssertionError("event was not acknowledged")
        if ack1["acknowledged_at"] != ack2["acknowledged_at"]:
            raise AssertionError("acknowledge was not idempotent")

        result = {
            "status": "passed",
            "law_id": law_id,
            "event_id": event["event_id"],
            "from_revision_id": event["from_revision_id"],
            "to_revision_id": event["to_revision_id"],
            "compare_status": comparison["status"],
            "compare_navigation_resolved_exact_revisions": True,
            "related_include_nonconfirmed": related["include_nonconfirmed"],
            "related_material_count": related["material_count"],
            "acknowledge_idempotent": True,
            "database_url_recorded": False,
        }
        conn.rollback()

    with psycopg.connect(database_url) as conn:
        after_counts = _counts(conn)
    result["rollback_preserved_application_state_counts"] = after_counts == before_counts
    if after_counts != before_counts:
        raise AssertionError("navigation smoke left application state behind")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("LEGAL_KB_DATABASE_URL"))
    parser.add_argument("--law-id", default="129AC0000000089")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("LEGAL_KB_DATABASE_URL or --database-url is required")
    print(json.dumps(
        run(args.database_url, law_id=args.law_id),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
