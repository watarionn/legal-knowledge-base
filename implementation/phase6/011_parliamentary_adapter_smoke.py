from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone

import psycopg

HERE = pathlib.Path(__file__).resolve().parent
DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=legal_kb user=legal_kb")
DIET_ISSUE = "100105254X00119470520"
IMPERIAL_ISSUE = "009213242X03119470330"


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


adapter = load_module("phase62_adapter_smoke", "008_parliamentary_adapter.py")
persistence = load_module("phase62_persistence_smoke", "009_parliamentary_persistence.py")


def payload(issue_id: str, *, imperial: bool) -> bytes:
    speech = {
        "speechID": issue_id + "_000",
        "speechOrder": 0,
        "speaker": "Synthetic Speaker",
        "speakerYomi": "synthetic",
        "speakerGroup": "Synthetic Group",
        "speakerPosition": "Synthetic Position",
        "speech": "Synthetic parliamentary speech",
        "startPage": 1,
        "speechURL": f"https://example.invalid/{issue_id}/0",
    }
    if imperial:
        speech.update({"speakerElection": "Synthetic Election", "officeTerm": "Synthetic Term"})
    else:
        speech.update({
            "speakerRole": "Synthetic Role",
            "createTime": "2026-01-01T00:00:00+09:00",
            "updateTime": "2026-01-01T00:00:00+09:00",
        })
    meeting = {
        "issueID": issue_id,
        "imageKind": "meeting",
        "searchObject": "body",
        "session": 92 if imperial else 1,
        "nameOfHouse": "Synthetic House",
        "nameOfMeeting": "Synthetic Meeting",
        "issue": "1",
        "date": "1947-03-30" if imperial else "1947-05-20",
        "speechRecord": [speech],
        "meetingURL": f"https://example.invalid/{issue_id}",
        "pdfURL": f"https://example.invalid/{issue_id}.pdf",
    }
    return json.dumps({"numberOfRecords": 1, "meetingRecord": [meeting]}).encode("utf-8")


def fetched(provider_code: str, issue_id: str, raw: bytes):
    provider = adapter.PROVIDERS[provider_code]
    meeting = adapter.parse_meeting_response(provider, issue_id, raw)
    return adapter.FetchedMeeting(
        provider=provider,
        request_url=adapter.build_meeting_url(provider, issue_id),
        raw_payload=raw,
        payload_sha256=adapter.hashlib.sha256(raw).hexdigest(),
        meeting=meeting,
        observed_at=datetime.now(timezone.utc),
    )


def main() -> None:
    run_id = f"phase62-smoke-{uuid.uuid4().hex[:12]}"
    diet = fetched("kokkai-ndl", DIET_ISSUE, payload(DIET_ISSUE, imperial=False))
    imperial = fetched(
        "teikoku-ndl", IMPERIAL_ISSUE, payload(IMPERIAL_ISSUE, imperial=True)
    )
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO legal_kb.ingestion_run
                    (ingestion_run_id, started_at, result_status)
                VALUES (%s, %s, 'succeeded')
                """,
                (run_id, datetime.now(timezone.utc)),
            )
        diet_result = persistence.persist_fetched_meeting(
            conn, diet, ingestion_run_id=run_id
        )
        imperial_result = persistence.persist_fetched_meeting(
            conn, imperial, ingestion_run_id=run_id
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT provider_code, count(*)
                FROM legal_kb.external_document
                WHERE external_document_id IN (%s, %s)
                GROUP BY provider_code
                ORDER BY provider_code
                """,
                (diet_result.external_document_id, imperial_result.external_document_id),
            )
            provider_rows = cur.fetchall()
            assert provider_rows == [("kokkai-ndl", 1), ("teikoku-ndl", 1)]
            cur.execute(
                """
                SELECT count(*)
                FROM legal_kb.external_document_part
                WHERE external_document_id IN (%s, %s)
                """,
                (diet_result.external_document_id, imperial_result.external_document_id),
            )
            assert cur.fetchone()[0] == 2
            cur.execute(
                """
                SELECT metadata_projection_jsonb
                FROM legal_kb.external_document_part_observation o
                JOIN legal_kb.external_document_part p USING (external_part_id)
                WHERE p.external_document_id = %s
                """,
                (imperial_result.external_document_id,),
            )
            imperial_metadata = cur.fetchone()[0]
            assert imperial_metadata["speakerElection"] == "Synthetic Election"
            assert imperial_metadata["officeTerm"] == "Synthetic Term"

            cur.execute(
                """
                SELECT external_part_id
                FROM legal_kb.external_document_part
                WHERE external_document_id = %s
                """,
                (diet_result.external_document_id,),
            )
            diet_part_id = cur.fetchone()[0]
            cur.execute(
                """
                SELECT provider_code, provider_document_id, provider_part_id,
                       source_file_sha256, text_sha256
                FROM legal_kb.parliamentary_part_provenance(%s)
                """,
                (diet_part_id,),
            )
            provenance = cur.fetchone()
            assert provenance[0] == "kokkai-ndl"
            assert provenance[1] == DIET_ISSUE
            assert provenance[2] == DIET_ISSUE + "_000"
            assert provenance[3] == diet.payload_sha256
            assert provenance[4] == adapter.text_sha256("Synthetic parliamentary speech")

        repeat = persistence.persist_fetched_meeting(conn, diet, ingestion_run_id=run_id)
        assert repeat.observation_count == 0

        changed_speech = replace(
            diet.meeting.speeches[0], speech_text="Changed without changing raw payload"
        )
        changed_meeting = replace(diet.meeting, speeches=(changed_speech,))
        drift = replace(diet, meeting=changed_meeting)
        drift_blocked = False
        try:
            persistence.persist_fetched_meeting(conn, drift, ingestion_run_id=run_id)
        except RuntimeError:
            drift_blocked = True
        assert drift_blocked is True
        conn.rollback()

    print("PHASE62_PARLIAMENTARY_ADAPTER_SMOKE_OK")


if __name__ == "__main__":
    main()
