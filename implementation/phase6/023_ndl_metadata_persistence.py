from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from dataclasses import dataclass
from datetime import timezone
from typing import Any

import psycopg

HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


identity = _load("phase6_identity_for_ndl", "003_external_source_identity.py")
adapter = _load("phase6_ndl_metadata_adapter_for_persistence", "022_ndl_metadata_adapter.py")


@dataclass(frozen=True)
class PersistedNdlMetadata:
    external_document_id: str
    snapshot_id: str
    source_file_id: str
    observation_id: str


def deterministic_source_file_id(fetched: Any) -> str:
    value = "\x1f".join((
        "phase6-ndl-source-file-1.0",
        fetched.record.oai_identifier,
        fetched.payload_sha256,
    ))
    return "phase6-ndl-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def persist_oai_record(
    conn: psycopg.Connection,
    fetched: Any,
    *,
    ingestion_run_id: str,
    stored_path: str | None = None,
) -> PersistedNdlMetadata:
    record = fetched.record
    external_id = identity.external_document_id(adapter.PROVIDER_CODE, record.oai_identifier)
    snap_id = identity.snapshot_id(external_id, fetched.payload_sha256)
    source_file_id = deterministic_source_file_id(fetched)
    observation_id = adapter.metadata_observation_id(record, snap_id)
    observed_at = fetched.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    canonical_url = adapter.canonical_bib_url(record.oai_identifier)
    projection = dict(record.projection)
    projection["oai_identifier"] = record.oai_identifier
    projection["repository_number"] = record.repository_number
    projection["item_number"] = record.item_number

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.external_source_provider
                (provider_code, source_family, authority_name, base_url,
                 transport_kind, provider_id_strategy, source_truth_role,
                 metadata_jsonb)
            VALUES (%s, 'ndl-search', 'National Diet Library', %s,
                    'sru-opensearch-oai-pmh', 'OAI-PMH metadata identifier',
                    'bibliographic-metadata', %s::jsonb)
            ON CONFLICT (provider_code) DO UPDATE SET
                active = true,
                metadata_jsonb = EXCLUDED.metadata_jsonb,
                updated_at = now()
            """,
            (
                adapter.PROVIDER_CODE,
                adapter.BASE_URL,
                json.dumps({
                    "sru": adapter.SRU_URL,
                    "oai_pmh": adapter.OAI_URL,
                    "default_metadata_prefix": adapter.DEFAULT_METADATA_PREFIX,
                    "bulk_list_records_enabled": False,
                }, ensure_ascii=False),
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.source_file
                (source_file_id, source_family, source_url, stored_path,
                 retrieved_at, media_type, byte_size, sha256,
                 immutable, ingestion_run_id)
            VALUES (%s, 'ndl-search', %s, %s, %s,
                    'application/xml', %s, %s, true, %s)
            ON CONFLICT (source_file_id) DO NOTHING
            """,
            (
                source_file_id,
                fetched.request_url,
                stored_path,
                observed_at,
                len(fetched.raw_payload),
                fetched.payload_sha256,
                ingestion_run_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.external_document
                (external_document_id, provider_code, provider_document_id,
                 document_kind, issued_on, title, canonical_url,
                 first_seen_run_id, last_seen_run_id, metadata_projection_jsonb)
            VALUES (%s, %s, %s, 'bibliographic-metadata', %s, %s, %s,
                    %s, %s, %s::jsonb)
            ON CONFLICT (provider_code, provider_document_id) DO UPDATE SET
                issued_on = COALESCE(EXCLUDED.issued_on, legal_kb.external_document.issued_on),
                title = COALESCE(EXCLUDED.title, legal_kb.external_document.title),
                canonical_url = EXCLUDED.canonical_url,
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                metadata_projection_jsonb = EXCLUDED.metadata_projection_jsonb,
                updated_at = now()
            """,
            (
                external_id,
                adapter.PROVIDER_CODE,
                record.oai_identifier,
                record.issued_on,
                record.title,
                canonical_url,
                ingestion_run_id,
                ingestion_run_id,
                json.dumps(projection, ensure_ascii=False),
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.external_document_snapshot
                (snapshot_id, external_document_id, source_file_id,
                 ingestion_run_id, observed_at, payload_sha256,
                 response_locator, response_metadata_jsonb)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (external_document_id, payload_sha256) DO NOTHING
            """,
            (
                snap_id,
                external_id,
                source_file_id,
                ingestion_run_id,
                observed_at,
                fetched.payload_sha256,
                fetched.request_url,
                json.dumps({"byte_size": len(fetched.raw_payload)}, ensure_ascii=False),
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.ndl_metadata_observation
                (ndl_metadata_observation_id, external_document_id, snapshot_id,
                 oai_identifier, repository_number, item_number, oai_datestamp,
                 metadata_prefix, deleted, set_specs, metadata_xml_sha256,
                 projection_jsonb, observed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s::jsonb, %s)
            ON CONFLICT (external_document_id, snapshot_id) DO NOTHING
            RETURNING ndl_metadata_observation_id
            """,
            (
                observation_id,
                external_id,
                snap_id,
                record.oai_identifier,
                record.repository_number,
                record.item_number,
                record.oai_datestamp,
                record.metadata_prefix,
                record.deleted,
                list(record.set_specs),
                record.metadata_xml_sha256,
                json.dumps(record.projection, ensure_ascii=False),
                observed_at,
            ),
        )
        inserted = cur.fetchone()
        if inserted is None:
            cur.execute(
                """
                SELECT ndl_metadata_observation_id, oai_datestamp,
                       metadata_xml_sha256, deleted
                FROM legal_kb.ndl_metadata_observation
                WHERE external_document_id = %s AND snapshot_id = %s
                """,
                (external_id, snap_id),
            )
            existing = cur.fetchone()
            if existing is None or existing != (
                observation_id,
                record.oai_datestamp,
                record.metadata_xml_sha256,
                record.deleted,
            ):
                raise RuntimeError("same NDL snapshot produced different metadata observation")

    return PersistedNdlMetadata(
        external_document_id=external_id,
        snapshot_id=snap_id,
        source_file_id=source_file_id,
        observation_id=observation_id,
    )
