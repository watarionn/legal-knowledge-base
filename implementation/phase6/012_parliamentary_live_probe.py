from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


adapter = load_module("phase62_adapter_live", "008_parliamentary_adapter.py")
persistence = load_module("phase62_persistence_live", "009_parliamentary_persistence.py")

DEFAULTS = (
    ("kokkai-ndl", "100105254X00119470520"),
    ("teikoku-ndl", "009213242X03119470330"),
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--min-interval-seconds", type=float, default=3.2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = adapter.ParliamentaryApiClient(
        min_interval_seconds=args.min_interval_seconds,
        user_agent="legal-knowledge-base/phase6.2-live-validation",
    )
    fetched_records = []
    for provider_code, issue_id in DEFAULTS:
        fetched_records.append(client.fetch_meeting(provider_code, issue_id))

    persisted = []
    if args.database_url:
        import psycopg

        run_id = f"phase62-live-{uuid.uuid4().hex[:12]}"
        with psycopg.connect(args.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO legal_kb.ingestion_run
                        (ingestion_run_id, started_at, result_status)
                    VALUES (%s, %s, 'succeeded')
                    """,
                    (run_id, datetime.now(timezone.utc)),
                )
            for fetched in fetched_records:
                persisted.append(
                    persistence.persist_fetched_meeting(
                        conn, fetched, ingestion_run_id=run_id
                    )
                )
            conn.commit()

    results = []
    for index, fetched in enumerate(fetched_records):
        meeting = fetched.meeting
        item = {
            "provider_code": fetched.provider.provider_code,
            "issue_id": meeting.issue_id,
            "session": meeting.session,
            "house": meeting.house,
            "meeting_name": meeting.meeting_name,
            "held_on": None if meeting.held_on is None else meeting.held_on.isoformat(),
            "speech_count": len(meeting.speeches),
            "payload_sha256": fetched.payload_sha256,
            "first_speech_id": meeting.speeches[0].speech_id if meeting.speeches else None,
            "last_speech_id": meeting.speeches[-1].speech_id if meeting.speeches else None,
        }
        if persisted:
            item.update(
                {
                    "external_document_id": persisted[index].external_document_id,
                    "snapshot_id": persisted[index].snapshot_id,
                    "source_file_id": persisted[index].source_file_id,
                }
            )
        results.append(item)

    print(
        json.dumps(
            {
                "status": "passed",
                "serial_requests": True,
                "min_interval_seconds": args.min_interval_seconds,
                "database_persisted": bool(persisted),
                "database_url_recorded": False,
                "credentials_recorded": False,
                "records": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
