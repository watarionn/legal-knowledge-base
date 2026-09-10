from __future__ import annotations

import hashlib
import importlib.util
import os
import pathlib
import sys
import uuid
from datetime import date, datetime, timezone

import psycopg

HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


identity = _load("phase65_identity_smoke", "003_external_source_identity.py")
persistence = _load("phase65_persistence_smoke", "030_cross_source_linkage_persistence.py")
retrieval = _load("phase65_retrieval_smoke", "033_external_relation_retrieval.py")
DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=legal_kb user=legal_kb")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def main() -> None:
    run_id = f"phase65-smoke-{uuid.uuid4().hex[:12]}"
    law_id = "405AC0000000088"
    revision_id = f"{law_id}_20260401_506AC0000000046"
    provider_code = "kokkai-ndl"
    provider_document_id = "100105254X00119470520"
    external_id = identity.external_document_id(provider_code, provider_document_id)
    payload_sha = sha("phase65 synthetic meeting payload")
    source_file_id = f"phase65-source-{uuid.uuid4().hex[:12]}"
    snapshot_id = identity.snapshot_id(external_id, payload_sha)
    part_id = sha(external_id + "speech-1")
    part_observation_id = sha(part_id + snapshot_id)
    now = datetime.now(timezone.utc)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO legal_kb.ingestion_run
                    (ingestion_run_id, started_at, result_status)
                VALUES (%s, %s, 'succeeded')
            """, (run_id, now))
            cur.execute("""
                INSERT INTO legal_kb.source_file
                    (source_file_id, source_family, retrieved_at, sha256,
                     immutable, ingestion_run_id)
                VALUES (%s, 'phase65-smoke', %s, %s, true, %s)
            """, (source_file_id, now, payload_sha, run_id))
            cur.execute("""
                INSERT INTO legal_kb.law
                    (law_id, law_num, law_type, promulgation_date,
                     first_seen_run_id, last_seen_run_id)
                VALUES (%s, '平成五年法律第八十八号', 'Act', %s, %s, %s)
            """, (law_id, date(1993, 11, 12), run_id, run_id))
            cur.execute("""
                INSERT INTO legal_kb.law_revision
                    (law_revision_id, law_id, law_type, law_title,
                     amendment_law_id, amendment_law_num,
                     revision_id_effective_date, revision_id_amending_law_id,
                     first_seen_run_id, last_seen_run_id)
                VALUES (%s, %s, 'Act', '行政手続法',
                        '506AC0000000046', '令和六年法律第四十六号',
                        %s, '506AC0000000046', %s, %s)
            """, (revision_id, law_id, date(2026, 4, 1), run_id, run_id))
            cur.execute("""
                INSERT INTO legal_kb.external_source_provider
                    (provider_code, source_family, authority_name, base_url,
                     transport_kind, provider_id_strategy, source_truth_role)
                VALUES (%s, 'diet-minutes', '国立国会図書館',
                        'https://kokkai.ndl.go.jp/', 'http-json-xml',
                        'provider-explicit issueID', 'official-proceedings')
            """, (provider_code,))
            cur.execute("""
                INSERT INTO legal_kb.external_document
                    (external_document_id, provider_code, provider_document_id,
                     document_kind, issued_on, title,
                     first_seen_run_id, last_seen_run_id)
                VALUES (%s, %s, %s, 'meeting-record', %s,
                        'Synthetic committee meeting', %s, %s)
            """, (external_id, provider_code, provider_document_id,
                  date(2026, 4, 1), run_id, run_id))
            cur.execute("""
                INSERT INTO legal_kb.external_document_snapshot
                    (snapshot_id, external_document_id, source_file_id,
                     ingestion_run_id, observed_at, payload_sha256)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (snapshot_id, external_id, source_file_id, run_id, now, payload_sha))
            cur.execute("""
                INSERT INTO legal_kb.external_document_part
                    (external_part_id, external_document_id, provider_part_id,
                     part_kind, part_order, first_seen_run_id, last_seen_run_id)
                VALUES (%s, %s, 'speech-1', 'speech', 1, %s, %s)
            """, (part_id, external_id, run_id, run_id))
            speech = '行政手続法（平成五年法律第八十八号）の運用について質問します。'
            cur.execute("""
                INSERT INTO legal_kb.external_document_part_observation
                    (part_observation_id, external_part_id, snapshot_id,
                     observed_at, text_sha256, text_projection)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (part_observation_id, part_id, snapshot_id, now, sha(speech), speech))

        result = persistence.persist_automatic_linkage(conn, external_id, run_id)
        assert result.relation_count == 1
        assert result.assertion_count == 2
        with conn.cursor() as cur:
            cur.execute("""
                SELECT source_relation_id, effective_state, candidate_count,
                       confirmed_count, rejected_count
                FROM legal_kb.source_relation_effective_state
                WHERE external_document_id = %s AND target_law_id = %s
            """, (external_id, law_id))
            relation_id, state, candidate_count, confirmed_count, rejected_count = cur.fetchone()
            assert state == 'candidate'
            assert (candidate_count, confirmed_count, rejected_count) == (2, 0, 0)
        assert retrieval.fetch_external_source_envelopes(
            conn, target_kind="law", target_id=law_id
        ) == ()
        candidate_rows = retrieval.fetch_external_source_envelopes(
            conn, target_kind="law", target_id=law_id, include_nonconfirmed=True
        )
        assert len(candidate_rows) == 1
        assert candidate_rows[0].effective_state == "candidate"
        assert candidate_rows[0].citation_ready is False
        assert candidate_rows[0].source_file_sha256.lower() == payload_sha

        persistence.record_manual_review(
            conn,
            source_relation_id=relation_id,
            ingestion_run_id=run_id,
            decision="confirmed",
            rationale="Synthetic reviewer confirmed the exact relation.",
            snapshot_id=snapshot_id,
        )
        confirmed_rows = retrieval.fetch_external_source_envelopes(
            conn, target_kind="law", target_id=law_id
        )
        assert len(confirmed_rows) == 1
        assert confirmed_rows[0].effective_state == "confirmed"
        assert confirmed_rows[0].citation_ready is True

        persistence.record_manual_review(
            conn,
            source_relation_id=relation_id,
            ingestion_run_id=run_id,
            decision="rejected",
            rationale="Synthetic conflicting review for conflict-state validation.",
            snapshot_id=snapshot_id,
        )
        assert retrieval.fetch_external_source_envelopes(
            conn, target_kind="law", target_id=law_id
        ) == ()
        conflicted_rows = retrieval.fetch_external_source_envelopes(
            conn, target_kind="law", target_id=law_id, include_nonconfirmed=True
        )
        assert len(conflicted_rows) == 1
        assert conflicted_rows[0].effective_state == "conflicted"
        assert conflicted_rows[0].citation_ready is False

        conn.rollback()

    print("PHASE65_CROSS_SOURCE_LINKAGE_SMOKE_OK")


if __name__ == "__main__":
    main()
