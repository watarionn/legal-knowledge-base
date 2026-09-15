from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "037_law_watch_schema.sql"
REQUIRED_RELATIONS = (
    "application_law_watch",
    "application_law_watch_event",
)
PREREQUISITE_RELATIONS = (
    "law",
    "law_revision",
    "ingestion_run",
    "application_saved_theme",
)


def classify_state(existing: set[str]) -> tuple[str, tuple[str, ...]]:
    present = set(REQUIRED_RELATIONS).intersection(existing)
    if not present:
        return "empty", REQUIRED_RELATIONS
    missing = tuple(name for name in REQUIRED_RELATIONS if name not in present)
    if not missing:
        return "ready", ()
    return "partial", missing
def _relation_exists(conn: Any, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"legal_kb.{name}",))
        return cur.fetchone()[0] is not None


def inspect_state(conn: Any) -> tuple[str, tuple[str, ...]]:
    existing = {name for name in REQUIRED_RELATIONS if _relation_exists(conn, name)}
    return classify_state(existing)


def verify_prerequisites(conn: Any) -> None:
    missing = [name for name in PREREQUISITE_RELATIONS if not _relation_exists(conn, name)]
    if missing:
        raise RuntimeError(f"Phase 7-5 prerequisite schema is missing: {missing}")


def bootstrap(database_url: str) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(database_url) as conn:
        verify_prerequisites(conn)
        state, missing = inspect_state(conn)
    if state == "partial":
        raise RuntimeError(f"partial law watch schema; missing={list(missing)}")
    if state == "empty":
        with psycopg.connect(database_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        action = "applied"
    else:
        action = "skipped-ready"

    with psycopg.connect(database_url) as conn:
        final_state, final_missing = inspect_state(conn)
    if final_state != "ready":
        raise RuntimeError(f"law watch bootstrap incomplete; missing={list(final_missing)}")
    return {
        "status": "passed",
        "schema": "phase7-6a-law-watch",
        "action": action,
        "relations": list(REQUIRED_RELATIONS),
        "database_url_recorded": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("LEGAL_KB_DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("LEGAL_KB_DATABASE_URL or --database-url is required")
    print(json.dumps(bootstrap(args.database_url), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
