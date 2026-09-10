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


adapter = _load("phase6_gazette_adapter_smoke", "015_official_gazette_adapter.py")
persistence = _load("phase6_gazette_persistence_smoke", "016_official_gazette_persistence.py")
DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=legal_kb user=legal_kb")
def main() -> None:
    run_id = f"phase63-smoke-{uuid.uuid4().hex[:12]}"
    issue = adapter.GazetteIssueSpec(date(2026, 8, 10), "regular", 1765)
    pdf_url = (
        "https://www.kanpo.go.jp/20260810/20260810h01765/pdf/"
        "20260810h01765full00010032.pdf"
    )
    asset = adapter.GazettePdfAssetSpec(issue, pdf_url, 1, 32)
    payload = (
        b"%PDF-1.7\n/Type /Sig\n/ByteRange [0 10 20 30]\n"
        b"/DocTimeStamp\n/ByteRange [0 1 2 3]\n/ETSI.CAdES.detached\n%%EOF"
    )
    fetched = adapter.FetchedGazetteAsset(
        asset=asset,
        raw_payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        observed_at=datetime.now(timezone.utc),
        certificate=adapter.inspect_pdf_signature_structure(payload),
    )

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO legal_kb.ingestion_run "
                "(ingestion_run_id, started_at, result_status) VALUES (%s, %s, 'succeeded')",
                (run_id, datetime.now(timezone.utc)),
            )
        persisted = persistence.persist_fetched_gazette_asset(
            conn,
            fetched,
            ingestion_run_id=run_id,
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT provider_document_id, publication_kind, issue_number,
                       page_start, page_end, source_file_sha256,
                       asset_payload_sha256, cryptographic_verification_status
                FROM legal_kb.official_gazette_asset_provenance(%s)
                """,
                (persisted.gazette_asset_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "derived:2026-08-10:regular:1765"
            assert row[1] == "regular"
            assert row[2] == 1765
            assert row[3:5] == (1, 32)
            assert row[5].lower() == fetched.payload_sha256
            assert row[6].lower() == fetched.payload_sha256
            assert row[7] == "not-checked"

            cur.execute(
                """
                SELECT signature_field_count, document_timestamp_count,
                       byte_range_count, cades_detached_count
                FROM legal_kb.official_gazette_certificate_observation
                WHERE snapshot_id = %s
                """,
                (persisted.snapshot_id,),
            )
            cert = cur.fetchone()
            assert cert == (1, 1, 2, 1)
            cur.execute(
                "SELECT count(*) FROM legal_kb.source_relation WHERE external_document_id = %s",
                (persisted.external_document_id,),
            )
            assert cur.fetchone()[0] == 0

            cur.execute(
                "SELECT metadata_jsonb ->> 'crawler' FROM legal_kb.external_source_provider "
                "WHERE provider_code = %s",
                (adapter.PROVIDER_CODE,),
            )
            assert cur.fetchone()[0] == "false"

        conn.rollback()

    print("PHASE63_OFFICIAL_GAZETTE_SMOKE_OK")


if __name__ == "__main__":
    main()
