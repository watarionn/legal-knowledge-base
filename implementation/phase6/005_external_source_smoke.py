from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import uuid
from datetime import date, datetime, timezone

import psycopg

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase6_identity", HERE / "003_external_source_identity.py"
)
identity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = identity
assert SPEC.loader is not None
SPEC.loader.exec_module(identity)

DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=legal_kb user=legal_kb")


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    run_id = f"phase6-smoke-{uuid.uuid4().hex[:12]}"
    source_file_id = f"phase6-source-{uuid.uuid4().hex[:12]}"
    law_source_file_id = f"phase6-law-source-{uuid.uuid4().hex[:12]}"
    payload_sha = sha("phase6 synthetic official payload")
    source_xml_sha = sha("phase6 synthetic law xml")
    provider_code = "kokkai-ndl"
    provider_document_id = "100105254X00119470520"
    external_id = identity.external_document_id(provider_code, provider_document_id)
    snap_id = identity.snapshot_id(external_id, payload_sha)
    law_id = "425AC0000000027"
    revision_id = f"{law_id}_20260101_{law_id}"
    document_id = sha(revision_id + "\x1f" + source_xml_sha)

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
            cur.execute(
                """
                INSERT INTO legal_kb.source_file
                    (source_file_id, source_family, retrieved_at, sha256,
                     immutable, ingestion_run_id)
                VALUES
                    (%s, 'phase6-smoke-external', %s, %s, true, %s),
                    (%s, 'phase6-smoke-law', %s, %s, true, %s)
                """,
                (
                    source_file_id,
                    datetime.now(timezone.utc),
                    payload_sha,
                    run_id,
                    law_source_file_id,
                    datetime.now(timezone.utc),
                    source_xml_sha,
                    run_id,
                ),
            )
            cur.execute(
                """
                INSERT INTO legal_kb.law
                    (law_id, law_type, first_seen_run_id, last_seen_run_id)
                VALUES (%s, 'Act', %s, %s)
                """,
                (law_id, run_id, run_id),
            )
            cur.execute(
                """
                INSERT INTO legal_kb.law_revision
                    (law_revision_id, law_id, law_type,
                     revision_id_effective_date, revision_id_amending_law_id,
                     first_seen_run_id, last_seen_run_id)
                VALUES (%s, %s, 'Act', %s, %s, %s, %s)
                """,
                (revision_id, law_id, date(2026, 1, 1), law_id, run_id, run_id),
            )
            cur.execute(
                """
                INSERT INTO legal_kb.law_document
                    (document_id, law_revision_id, source_file_id, ingestion_run_id,
                     source_xml_sha256, parser_version, root_tag_name,
                     parse_status, schema_validation_status)
                VALUES (%s, %s, %s, %s, %s, 'phase6-smoke', 'Law',
                        'succeeded', 'not-checked')
                RETURNING document_pk
                """,
                (document_id, revision_id, law_source_file_id, run_id, source_xml_sha),
            )
            document_pk = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO legal_kb.provision_node
                    (document_pk, document_order, node_id, ordinal, path_index,
                     depth, tag_name, attributes_jsonb, mixed_content_jsonb)
                VALUES (%s, 1, decode(%s, 'hex'), 1, 1, 0, 'Law',
                        '{}'::jsonb, '[]'::jsonb)
                """,
                (document_pk, sha("phase6-node")),
            )
            cur.execute(
                """
                INSERT INTO legal_kb.external_source_provider
                    (provider_code, source_family, authority_name, base_url,
                     transport_kind, provider_id_strategy, source_truth_role)
                VALUES
                    (%s, 'diet-minutes', '国立国会図書館',
                     'https://kokkai.ndl.go.jp/', 'http-json-xml',
                     'provider-explicit issueID', 'official-proceedings')
                """,
                (provider_code,),
            )
            cur.execute(
                """
                INSERT INTO legal_kb.external_document
                    (external_document_id, provider_code, provider_document_id,
                     document_kind, issued_on, title,
                     first_seen_run_id, last_seen_run_id)
                VALUES (%s, %s, %s, 'meeting-record', %s, %s, %s, %s)
                """,
                (
                    external_id,
                    provider_code,
                    provider_document_id,
                    date(2026, 1, 1),
                    'Synthetic meeting',
                    run_id,
                    run_id,
                ),
            )
            cur.execute(
                """
                INSERT INTO legal_kb.external_document_snapshot
                    (snapshot_id, external_document_id, source_file_id,
                     ingestion_run_id, observed_at, payload_sha256)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    snap_id,
                    external_id,
                    source_file_id,
                    run_id,
                    datetime.now(timezone.utc),
                    payload_sha,
                ),
            )
            target_id = identity.target_identifier(
                target_kind="provision_node",
                document_pk=document_pk,
                document_order=1,
            )
            relation_id = identity.source_relation_id(
                external_id, "provision_node", target_id, "discusses"
            )
            cur.execute(
                """
                INSERT INTO legal_kb.source_relation
                    (source_relation_id, external_document_id, target_kind,
                     target_document_pk, target_document_order, relation_kind)
                VALUES (%s, %s, 'provision_node', %s, 1, 'discusses')
                """,
                (relation_id, external_id, document_pk),
            )
            evidence = {"match": "synthetic explicit reference"}
            assertion_id = identity.relation_assertion_id(
                relation_id, "provider-explicit", evidence
            )
            cur.execute(
                """
                INSERT INTO legal_kb.source_relation_assertion
                    (relation_assertion_id, source_relation_id, snapshot_id,
                     ingestion_run_id, assertion_basis, assertion_status,
                     evidence_jsonb, observed_at)
                VALUES (%s, %s, %s, %s, 'provider-explicit', 'confirmed',
                        %s::jsonb, %s)
                """,
                (
                    assertion_id,
                    relation_id,
                    snap_id,
                    run_id,
                    json.dumps(evidence, ensure_ascii=False),
                    datetime.now(timezone.utc),
                ),
            )
            cur.execute(
                """
                SELECT provider_code, provider_document_id, source_file_sha256,
                       target_kind, target_identifier, target_xml_path,
                       relation_kind, assertion_status
                FROM legal_kb.external_relation_provenance(%s)
                """,
                (relation_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == provider_code
            assert row[1] == provider_document_id
            assert row[2].lower() == payload_sha
            assert row[3] == "provision_node"
            assert row[4] == f"{document_pk}:1"
            assert row[5] == "/Law[1]"
            assert row[6] == "discusses"
            assert row[7] == "confirmed"

            candidate_evidence = {"query": "synthetic"}
            candidate_assertion_id = identity.relation_assertion_id(
                relation_id, "text-match", candidate_evidence
            )
            cur.execute(
                """
                INSERT INTO legal_kb.source_relation_assertion
                    (relation_assertion_id, source_relation_id, snapshot_id,
                     ingestion_run_id, assertion_basis, assertion_status,
                     evidence_jsonb, observed_at)
                VALUES (%s, %s, %s, %s, 'text-match', 'candidate',
                        %s::jsonb, %s)
                """,
                (
                    candidate_assertion_id,
                    relation_id,
                    snap_id,
                    run_id,
                    json.dumps(candidate_evidence),
                    datetime.now(timezone.utc),
                ),
            )
            cur.execute(
                """
                SELECT array_agg(assertion_status ORDER BY assertion_status)
                FROM legal_kb.source_relation_assertion
                WHERE source_relation_id = %s
                """,
                (relation_id,),
            )
            assert cur.fetchone()[0] == ["candidate", "confirmed"]

        conn.rollback()

    print("PHASE61_EXTERNAL_SOURCE_SMOKE_OK")


if __name__ == "__main__":
    main()
