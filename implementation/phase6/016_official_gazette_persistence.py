from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from dataclasses import dataclass
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


identity = _load("phase6_identity_for_gazette", "003_external_source_identity.py")
adapter = _load("phase6_gazette_adapter_for_persistence", "015_official_gazette_adapter.py")
@dataclass(frozen=True)
class PersistedGazetteAsset:
    external_document_id: str
    snapshot_id: str
    source_file_id: str
    gazette_asset_id: str


def deterministic_source_file_id(fetched: Any) -> str:
    value = "\x1f".join(
        (
            "phase6-official-gazette-source-file-1.0",
            adapter.PROVIDER_CODE,
            fetched.asset.pdf_url,
            fetched.payload_sha256,
        )
    )
    return "phase6-gazette-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_title(issue: Any) -> str:
    labels = {
        "regular": "本紙",
        "extra": "号外",
        "government-procurement": "政府調達",
        "special-extra": "特別号外",
        "index": "目録",
    }
    return f"官報 {labels[issue.publication_kind]} 第{issue.issue_number}号"
def persist_fetched_gazette_asset(
    conn: psycopg.Connection,
    fetched: Any,
    *,
    ingestion_run_id: str,
    stored_path: str | None = None,
) -> PersistedGazetteAsset:
    issue = fetched.asset.issue
    external_id = identity.external_document_id(
        adapter.PROVIDER_CODE,
        issue.provider_document_id,
    )
    snapshot_id = identity.snapshot_id(external_id, fetched.payload_sha256)
    source_file_id = deterministic_source_file_id(fetched)
    observed_at = fetched.observed_at

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.external_source_provider
                (provider_code, source_family, authority_name, base_url,
                 transport_kind, provider_id_strategy, source_truth_role,
                 metadata_jsonb)
            VALUES (%s, 'official-gazette', 'Cabinet Office, Government of Japan', %s,
                    'html-pdf',
                    'derived issued_on + publication_kind + issue_number; not an official ID',
                    'official-publication', %s::jsonb)
            ON CONFLICT (provider_code) DO UPDATE SET
                active = true,
                metadata_jsonb = EXCLUDED.metadata_jsonb,
                updated_at = now()
            """,
            (
                adapter.PROVIDER_CODE,
                adapter.BASE_URL,
                json.dumps({"acquisition_mode": "explicit-issue-only", "crawler": False}),
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.source_file
                (source_file_id, source_family, source_url, stored_path, retrieved_at,
                 media_type, byte_size, sha256, original_file_name,
                 immutable, ingestion_run_id)
            VALUES (%s, 'official-gazette', %s, %s, %s, 'application/pdf',
                    %s, %s, %s, true, %s)
            ON CONFLICT (source_file_id) DO NOTHING
            """,
            (
                source_file_id,
                fetched.asset.pdf_url,
                stored_path,
                observed_at,
                fetched.byte_size,
                fetched.payload_sha256,
                pathlib.PurePosixPath(fetched.asset.pdf_url).name,
                ingestion_run_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.external_document
                (external_document_id, provider_code, provider_document_id,
                 document_kind, issued_on, title, canonical_url,
                 first_seen_run_id, last_seen_run_id, metadata_projection_jsonb)
            VALUES (%s, %s, %s, 'official-gazette-issue', %s, %s, %s,
                    %s, %s, %s::jsonb)
            ON CONFLICT (provider_code, provider_document_id) DO UPDATE SET
                issued_on = EXCLUDED.issued_on,
                title = EXCLUDED.title,
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                metadata_projection_jsonb = EXCLUDED.metadata_projection_jsonb,
                updated_at = now()
            """,
            (
                external_id, adapter.PROVIDER_CODE, issue.provider_document_id,
                issue.issued_on, issue_title(issue), None,
                ingestion_run_id, ingestion_run_id,
                json.dumps({"publication_kind": issue.publication_kind,
                            "issue_number": issue.issue_number}, ensure_ascii=False),
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
                snapshot_id, external_id, source_file_id, ingestion_run_id,
                observed_at, fetched.payload_sha256, fetched.asset.pdf_url,
                json.dumps({"page_start": fetched.asset.page_start,
                            "page_end": fetched.asset.page_end,
                            "byte_size": fetched.byte_size}),
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.official_gazette_issue
                (external_document_id, issued_on, publication_kind,
                 issue_number, derived_provider_key)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (external_document_id) DO NOTHING
            """,
            (external_id, issue.issued_on, issue.publication_kind,
             issue.issue_number, issue.provider_document_id),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.official_gazette_asset
                (gazette_asset_id, external_document_id, snapshot_id,
                 page_start, page_end, pdf_url, payload_sha256, byte_size)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (gazette_asset_id) DO NOTHING
            """,
            (
                fetched.asset.id, external_id, snapshot_id,
                fetched.asset.page_start, fetched.asset.page_end,
                fetched.asset.pdf_url, fetched.payload_sha256, fetched.byte_size,
            ),
        )
        cert = fetched.certificate
        cur.execute(
            """
            INSERT INTO legal_kb.official_gazette_certificate_observation
                (snapshot_id, signature_field_count, document_timestamp_count,
                 byte_range_count, cades_detached_count,
                 cryptographic_verification_status, verifier_name,
                 verifier_version, details_jsonb, observed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (snapshot_id) DO NOTHING
            """,
            (
                snapshot_id, cert.signature_field_count,
                cert.document_timestamp_count, cert.byte_range_count,
                cert.cades_detached_count, cert.cryptographic_verification_status,
                cert.verifier_name, cert.verifier_version,
                json.dumps(dict(cert.details or {}), ensure_ascii=False), observed_at,
            ),
        )

    return PersistedGazetteAsset(
        external_document_id=external_id,
        snapshot_id=snapshot_id,
        source_file_id=source_file_id,
        gazette_asset_id=fetched.asset.id,
    )
