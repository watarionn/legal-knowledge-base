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


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


adapter = _load("phase65_live_parliament", "008_parliamentary_adapter.py")
parliament = _load("phase65_live_parliament_persistence", "009_parliamentary_persistence.py")
linkage = _load("phase65_live_linkage", "030_cross_source_linkage_persistence.py")
retrieval = _load("phase65_live_retrieval", "033_external_relation_retrieval.py")

DEFAULT_ISSUE_ID = "122114080X01420260716"
DEFAULT_TARGET_LAW_ID = "405AC0000000088"

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--issue-id", default=DEFAULT_ISSUE_ID)
    parser.add_argument("--target-law-id", default=DEFAULT_TARGET_LAW_ID)
    parser.add_argument("--min-interval-seconds", type=float, default=3.2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    import psycopg

    client = adapter.ParliamentaryApiClient(
        min_interval_seconds=args.min_interval_seconds,
        user_agent="legal-knowledge-base/phase6.5-live-validation",
    )
    fetched = client.fetch_meeting("kokkai-ndl", args.issue_id)
    run_id = f"phase65-live-{uuid.uuid4().hex[:12]}"

    with psycopg.connect(args.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM legal_kb.law WHERE law_id = %s", (args.target_law_id,))
            if cur.fetchone() is None:
                raise RuntimeError("target Phase 3 law is missing")
            cur.execute("""
                INSERT INTO legal_kb.ingestion_run
                    (ingestion_run_id, started_at, result_status)
                VALUES (%s, %s, 'succeeded')
            """, (run_id, datetime.now(timezone.utc)))
        persisted = parliament.persist_fetched_meeting(
            conn, fetched, ingestion_run_id=run_id
        )
        linked = linkage.persist_automatic_linkage(
            conn, persisted.external_document_id, run_id
        )
        default_rows = retrieval.fetch_external_source_envelopes(
            conn, target_kind="law", target_id=args.target_law_id
        )
        all_rows = retrieval.fetch_external_source_envelopes(
            conn,
            target_kind="law",
            target_id=args.target_law_id,
            include_nonconfirmed=True,
        )
        candidate_rows = [row for row in all_rows if row.effective_state == "candidate"]
        target_mentions = [
            speech for speech in fetched.meeting.speeches
            if "行政手続法" in (speech.speech_text or "")
        ]
        if not target_mentions:
            raise RuntimeError("live meeting no longer contains expected exact law-title mention")
        if default_rows:
            raise RuntimeError("automatic candidate unexpectedly became default citation-ready retrieval")
        if not candidate_rows:
            raise RuntimeError("expected candidate relation was not generated")
        if any(row.citation_ready for row in candidate_rows):
            raise RuntimeError("candidate relation became citation-ready")

        result = {
            "status": "passed",
            "provider_code": fetched.provider.provider_code,
            "issue_id": fetched.meeting.issue_id,
            "held_on": None if fetched.meeting.held_on is None else fetched.meeting.held_on.isoformat(),
            "speech_count": len(fetched.meeting.speeches),
            "exact_title_mention_count": len(target_mentions),
            "target_law_id": args.target_law_id,
            "relation_count_inserted": linked.relation_count,
            "assertion_count_inserted": linked.assertion_count,
            "candidate_relation_count": len(candidate_rows),
            "default_retrieval_count": len(default_rows),
            "candidate_citation_ready": any(row.citation_ready for row in candidate_rows),
            "payload_sha256": fetched.payload_sha256,
            "source_file_id": persisted.source_file_id,
            "snapshot_id": persisted.snapshot_id,
            "database_url_recorded": False,
            "credentials_recorded": False,
        }
        conn.rollback()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("PHASE65_LIVE_CROSS_SOURCE_LINKAGE_OK")


if __name__ == "__main__":
    main()
