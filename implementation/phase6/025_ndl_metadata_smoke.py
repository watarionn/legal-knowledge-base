from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone

import psycopg

HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


adapter = _load("phase6_ndl_adapter_smoke", "022_ndl_metadata_adapter.py")
persistence = _load("phase6_ndl_persistence_smoke", "023_ndl_metadata_persistence.py")
DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=legal_kb user=legal_kb")
IDENTIFIER = "oai:ndlsearch.ndl.go.jp:R100000002-I123456789"


def raw_record(datestamp: str, *, deleted: bool) -> bytes:
    status = ' status="deleted"' if deleted else ""
    metadata = "" if deleted else '''<metadata>
      <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">
       <rdf:Description><dc:title>日本国憲法資料</dc:title><dcterms:issued>2026-09-01</dcterms:issued></rdf:Description>
      </rdf:RDF></metadata>'''
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <GetRecord><record><header{status}>
  <identifier>{IDENTIFIER}</identifier><datestamp>{datestamp}</datestamp>
  <setSpec>iss-ndl-opac</setSpec>
 </header>{metadata}</record></GetRecord>
</OAI-PMH>'''.encode("utf-8")


def fetched(raw: bytes, observed_at: datetime):
    record = adapter.parse_oai_get_record(raw, expected_identifier=IDENTIFIER)
    return adapter.FetchedOaiRecord(
        record=record,
        request_url=adapter.build_oai_get_record_url(IDENTIFIER),
        raw_payload=raw,
        payload_sha256=adapter.sha256_bytes(raw),
        observed_at=observed_at,
    )


def main() -> None:
    run_id = f"phase64-smoke-{uuid.uuid4().hex[:12]}"
    first = fetched(raw_record("2026-09-10T09:00:00Z", deleted=False), datetime.now(timezone.utc))
    second = fetched(raw_record("2026-09-11T09:00:00Z", deleted=True), datetime.now(timezone.utc))
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO legal_kb.ingestion_run "
                "(ingestion_run_id, started_at, result_status) VALUES (%s, %s, 'succeeded')",
                (run_id, datetime.now(timezone.utc)),
            )
        p1 = persistence.persist_oai_record(conn, first, ingestion_run_id=run_id)
        p2 = persistence.persist_oai_record(conn, second, ingestion_run_id=run_id)
        assert p1.external_document_id == p2.external_document_id
        assert p1.snapshot_id != p2.snapshot_id
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT oai_identifier, oai_datestamp, deleted,
                       source_file_sha256, metadata_xml_sha256
                FROM legal_kb.ndl_metadata_provenance(%s)
                """,
                (p1.external_document_id,),
            )
            rows = cur.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == IDENTIFIER
            assert rows[0][2] is False and rows[0][3].lower() == first.payload_sha256
            assert rows[0][4] == first.record.metadata_xml_sha256
            assert rows[1][2] is True and rows[1][3].lower() == second.payload_sha256
            assert rows[1][4] is None
            cur.execute(
                "SELECT count(*) FROM legal_kb.source_relation WHERE external_document_id = %s",
                (p1.external_document_id,),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "SELECT metadata_projection_jsonb ->> 'oai_deleted' "
                "FROM legal_kb.external_document WHERE external_document_id = %s",
                (p1.external_document_id,),
            )
            assert cur.fetchone()[0] == "true"
            cur.execute(
                "SELECT metadata_jsonb ->> 'bulk_list_records_enabled' "
                "FROM legal_kb.external_source_provider WHERE provider_code = %s",
                (adapter.PROVIDER_CODE,),
            )
            assert cur.fetchone()[0] == "false"
        conn.rollback()
    print("PHASE64_NDL_METADATA_SMOKE_OK")


if __name__ == "__main__":
    main()
