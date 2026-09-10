from __future__ import annotations

import argparse
import importlib.util
import json
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


adapter = _load("phase6_ndl_adapter_live", "022_ndl_metadata_adapter.py")
persistence = _load("phase6_ndl_persistence_live", "023_ndl_metadata_persistence.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--item-token", default="R000000004-I026731256")
    parser.add_argument("--raw-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    expected_identifier = adapter.token_to_oai_identifier(args.item_token)
    client = adapter.NdlSearchClient(min_interval_seconds=3.0)
    query = f'itemno="{args.item_token}"'
    total, discoveries, sru_url, sru_raw = client.discover_sru(query, maximum_records=1)
    if total < 1 or len(discoveries) != 1:
        raise RuntimeError("exact SRU itemno discovery did not return one record")
    discovery = discoveries[0]
    if discovery.oai_identifier != expected_identifier:
        raise RuntimeError("SRU discovery token does not match requested item token")
    fetched = client.get_oai_record(expected_identifier, metadata_prefix="dcndl_v3")

    raw_dir = pathlib.Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{args.item_token}_dcndl_v3.xml"
    raw_path.write_bytes(fetched.raw_payload)

    run_id = f"phase64-live-{uuid.uuid4().hex[:12]}"
    with psycopg.connect(args.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO legal_kb.ingestion_run "
                "(ingestion_run_id, started_at, result_status) VALUES (%s, %s, 'succeeded')",
                (run_id, datetime.now(timezone.utc)),
            )
        persisted = persistence.persist_oai_record(
            conn,
            fetched,
            ingestion_run_id=run_id,
            stored_path=str(raw_path),
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT oai_identifier, oai_datestamp, deleted, metadata_prefix,
                       set_specs, source_file_sha256, metadata_xml_sha256
                FROM legal_kb.ndl_metadata_provenance(%s)
                """,
                (persisted.external_document_id,),
            )
            provenance = cur.fetchall()
            if len(provenance) != 1:
                raise RuntimeError("expected exactly one NDL provenance row")
            row = provenance[0]
            if row[0] != expected_identifier or row[2] is not False:
                raise RuntimeError("stored OAI identity/deletion state mismatch")
            if row[5].lower() != fetched.payload_sha256:
                raise RuntimeError("source_file SHA provenance mismatch")
            cur.execute(
                "SELECT count(*) FROM legal_kb.source_relation WHERE external_document_id = %s",
                (persisted.external_document_id,),
            )
            relation_count = cur.fetchone()[0]
            if relation_count != 0:
                raise RuntimeError("Phase 6.4 must not create automatic legal relations")
        conn.commit()

    record = fetched.record
    result = {
        "status": "passed",
        "provider_code": adapter.PROVIDER_CODE,
        "sru_exact_item_discovery": True,
        "sru_total": total,
        "oai_identifier": record.oai_identifier,
        "repository_number": record.repository_number,
        "item_number": record.item_number,
        "oai_datestamp": record.oai_datestamp,
        "set_specs": list(record.set_specs),
        "metadata_prefix": record.metadata_prefix,
        "deleted": record.deleted,
        "title": record.title,
        "issued_on": None if record.issued_on is None else record.issued_on.isoformat(),
        "raw_xml_bytes": len(fetched.raw_payload),
        "oai_payload_sha256": fetched.payload_sha256,
        "metadata_xml_sha256": record.metadata_xml_sha256,
        "sru_response_sha256": adapter.sha256_bytes(sru_raw),
        "serial_requests": True,
        "min_interval_seconds": client.min_interval_seconds,
        "bulk_list_records_enabled": False,
        "automatic_legal_relations": relation_count,
        "database_url_recorded": False,
        "credentials_recorded": False,
        "external_document_id": persisted.external_document_id,
        "snapshot_id": persisted.snapshot_id,
        "source_file_id": persisted.source_file_id,
        "observation_id": persisted.observation_id,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("PHASE64_LIVE_NDL_METADATA_INGEST_OK")


if __name__ == "__main__":
    main()
