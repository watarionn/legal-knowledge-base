from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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


identity = _load("phase6_identity_for_parliament", "003_external_source_identity.py")
adapter = _load("phase6_parliamentary_adapter_for_persistence", "008_parliamentary_adapter.py")


@dataclass(frozen=True)
class PersistedMeeting:
    external_document_id: str
    snapshot_id: str
    source_file_id: str
    part_count: int
    observation_count: int


def deterministic_source_file_id(fetched: Any) -> str:
    value = "\x1f".join(
        (
            "phase6-parliamentary-source-file-1.0",
            fetched.provider.provider_code,
            fetched.meeting.issue_id,
            fetched.payload_sha256,
        )
    )
    return "phase6-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _title(meeting: Any) -> str:
    values = [
        None if meeting.session is None else f"session {meeting.session}",
        meeting.house,
        meeting.meeting_name,
        None if meeting.issue is None else f"issue {meeting.issue}",
    ]
    return " / ".join(str(value) for value in values if value not in (None, ""))


def persist_fetched_meeting(
    conn: psycopg.Connection,
    fetched: Any,
    *,
    ingestion_run_id: str,
) -> PersistedMeeting:
    provider = fetched.provider
    meeting = fetched.meeting
    external_id = identity.external_document_id(provider.provider_code, meeting.issue_id)
    snap_id = identity.snapshot_id(external_id, fetched.payload_sha256)
    source_file_id = deterministic_source_file_id(fetched)
    observed_at = fetched.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.external_source_provider
                (provider_code, source_family, authority_name, base_url,
                 transport_kind, provider_id_strategy, source_truth_role,
                 metadata_jsonb)
            VALUES (%s, %s, 'National Diet Library', %s,
                    'http-json-xml', 'provider-explicit issueID/speechID',
                    'official-proceedings', %s::jsonb)
            ON CONFLICT (provider_code) DO UPDATE SET
                active = true,
                metadata_jsonb = EXCLUDED.metadata_jsonb,
                updated_at = now()
            """,
            (
                provider.provider_code,
                provider.source_family,
                provider.base_url,
                json.dumps(
                    {"meeting_endpoint": provider.meeting_endpoint, "recordPacking": "json"},
                    ensure_ascii=False,
                ),
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.source_file
                (source_file_id, source_family, source_url, retrieved_at,
                 media_type, byte_size, sha256, immutable, ingestion_run_id)
            VALUES (%s, %s, %s, %s, 'application/json', %s, %s, true, %s)
            ON CONFLICT (source_file_id) DO NOTHING
            """,
            (
                source_file_id,
                provider.source_family,
                fetched.request_url,
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
            VALUES (%s, %s, %s, 'meeting-record', %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (provider_code, provider_document_id) DO UPDATE SET
                issued_on = EXCLUDED.issued_on,
                title = EXCLUDED.title,
                canonical_url = EXCLUDED.canonical_url,
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                metadata_projection_jsonb = EXCLUDED.metadata_projection_jsonb,
                updated_at = now()
            """,
            (
                external_id,
                provider.provider_code,
                meeting.issue_id,
                meeting.held_on,
                _title(meeting),
                meeting.meeting_url,
                ingestion_run_id,
                ingestion_run_id,
                json.dumps(dict(meeting.metadata), ensure_ascii=False),
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

        observations = 0
        for speech in meeting.speeches:
            part_id = adapter.external_part_id(external_id, speech.speech_id)
            cur.execute(
                """
                INSERT INTO legal_kb.external_document_part
                    (external_part_id, external_document_id, provider_part_id,
                     part_kind, part_order, first_seen_run_id, last_seen_run_id)
                VALUES (%s, %s, %s, 'speech', %s, %s, %s)
                ON CONFLICT (external_document_id, provider_part_id) DO UPDATE SET
                    last_seen_run_id = EXCLUDED.last_seen_run_id,
                    updated_at = now()
                WHERE legal_kb.external_document_part.part_order = EXCLUDED.part_order
                RETURNING external_part_id
                """,
                (
                    part_id,
                    external_id,
                    speech.speech_id,
                    speech.speech_order,
                    ingestion_run_id,
                    ingestion_run_id,
                ),
            )
            if cur.fetchone() is None:
                raise RuntimeError("provider part identity changed its speech order")
            speech_sha = adapter.text_sha256(speech.speech_text)
            observation_id = adapter.part_observation_id(part_id, snap_id, speech_sha)
            metadata = dict(speech.metadata)
            metadata["speechURL"] = speech.speech_url
            cur.execute(
                """
                INSERT INTO legal_kb.external_document_part_observation
                    (part_observation_id, external_part_id, snapshot_id,
                     observed_at, text_sha256, text_projection,
                     metadata_projection_jsonb)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (external_part_id, snapshot_id) DO NOTHING
                RETURNING part_observation_id
                """,
                (
                    observation_id,
                    part_id,
                    snap_id,
                    observed_at,
                    speech_sha,
                    speech.speech_text,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )

            inserted = cur.fetchone()
            if inserted is not None:
                observations += 1
                continue
            cur.execute(
                """
                SELECT text_sha256
                FROM legal_kb.external_document_part_observation
                WHERE external_part_id = %s AND snapshot_id = %s
                """,
                (part_id, snap_id),
            )
            existing = cur.fetchone()
            if existing is None or existing[0] != speech_sha:
                raise RuntimeError("same speech snapshot produced different text hash")

    return PersistedMeeting(
        external_document_id=external_id,
        snapshot_id=snap_id,
        source_file_id=source_file_id,
        part_count=len(meeting.speeches),
        observation_count=observations,
    )
