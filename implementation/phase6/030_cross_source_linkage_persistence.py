from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


identity = _load("phase6_link_identity", "003_external_source_identity.py")
linker = _load("phase6_linker", "029_cross_source_linker.py")


@dataclass(frozen=True)
class LinkagePersistResult:
    relation_count: int
    assertion_count: int


def load_law_catalog(conn) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT l.law_id, l.law_num,
                   coalesce(array_agg(DISTINCT lr.law_title)
                     FILTER (WHERE lr.law_title IS NOT NULL), ARRAY[]::text[])
            FROM legal_kb.law l
            LEFT JOIN legal_kb.law_revision lr ON lr.law_id = l.law_id
            GROUP BY l.law_id, l.law_num
            ORDER BY l.law_id
        """)
        laws = tuple(linker.LawCatalogEntry(r[0], r[1], tuple(r[2])) for r in cur.fetchall())
        cur.execute("""
            SELECT law_revision_id, law_id, amendment_law_id,
                   amendment_law_num, amendment_law_title
            FROM legal_kb.law_revision
            WHERE amendment_law_id IS NOT NULL
               OR amendment_law_num IS NOT NULL
               OR amendment_law_title IS NOT NULL
            ORDER BY law_revision_id
        """)
        revisions = tuple(
            linker.RevisionCatalogEntry(r[0], r[1], r[2], r[3], r[4])
            for r in cur.fetchall()
        )
    return laws, revisions


def _flatten_projection(projection: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for key in ("title", "alternative", "description", "subject", "identifier"):
        values = projection.get(key, [])
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if isinstance(value, str) and value.strip():
                result.append((f"ndl:{key}[{index}]", value))
    return result

def load_external_text_sources(conn, external_document_id: str) -> tuple[str, str, list[tuple[str, str]]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.provider_code, p.source_family, d.title
            FROM legal_kb.external_document d
            JOIN legal_kb.external_source_provider p USING (provider_code)
            WHERE d.external_document_id = %s
        """, (external_document_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("external document does not exist")
        provider_code, source_family, title = row

        if provider_code in {"kokkai-ndl", "teikoku-ndl"}:
            cur.execute("""
                SELECT p.provider_part_id, o.text_projection
                FROM legal_kb.external_document_part p
                JOIN LATERAL (
                    SELECT po.text_projection
                    FROM legal_kb.external_document_part_observation po
                    WHERE po.external_part_id = p.external_part_id
                    ORDER BY po.observed_at DESC, po.part_observation_id DESC
                    LIMIT 1
                ) o ON true
                WHERE p.external_document_id = %s
                ORDER BY p.part_order, p.provider_part_id
            """, (external_document_id,))
            sources = [(f"speech:{pid}", text) for pid, text in cur.fetchall() if text]
        elif provider_code == "ndl-search":
            cur.execute("""
                SELECT deleted, projection_jsonb
                FROM legal_kb.ndl_metadata_observation
                WHERE external_document_id = %s
                ORDER BY observed_at DESC, ndl_metadata_observation_id DESC
                LIMIT 1
            """, (external_document_id,))
            latest = cur.fetchone()
            sources = [] if latest is None or latest[0] else _flatten_projection(latest[1])
        else:
            sources = []
    if title and provider_code != "kanpo-cao":
        sources.insert(0, ("external-document:title", title))
    return provider_code, source_family, sources

def _latest_snapshot_id(conn, external_document_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT snapshot_id
            FROM legal_kb.external_document_snapshot
            WHERE external_document_id = %s
            ORDER BY observed_at DESC, snapshot_id DESC
            LIMIT 1
        """, (external_document_id,))
        row = cur.fetchone()
    if row is None:
        raise ValueError("external document has no snapshot")
    return row[0]


def persist_automatic_linkage(conn, external_document_id: str, ingestion_run_id: str) -> LinkagePersistResult:
    provider_code, _source_family, text_sources = load_external_text_sources(conn, external_document_id)
    laws, revisions = load_law_catalog(conn)
    proposals = linker.build_link_proposals(
        provider_code=provider_code,
        text_sources=text_sources,
        laws=laws,
        revisions=revisions,
    )
    snapshot_id = _latest_snapshot_id(conn, external_document_id)
    relation_count = 0
    assertion_count = 0

    with conn.cursor() as cur:
        for proposal in proposals:
            target_id = proposal.target_id
            relation_id = identity.source_relation_id(
                external_document_id, proposal.target_kind, target_id, proposal.relation_kind
            )
            if proposal.target_kind == "law":
                target_sql = (target_id, None)
            elif proposal.target_kind == "law_revision":
                target_sql = (None, target_id)
            else:
                raise ValueError("automatic linkage supports law/law_revision only")
            cur.execute("""
                INSERT INTO legal_kb.source_relation
                    (source_relation_id, external_document_id, target_kind,
                     target_law_id, target_law_revision_id, relation_kind)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_relation_id) DO NOTHING
            """, (
                relation_id,
                external_document_id,
                proposal.target_kind,
                target_sql[0],
                target_sql[1],
                proposal.relation_kind,
            ))
            relation_count += cur.rowcount

            for signal in proposal.signals:
                evidence = {
                    "automatic": True,
                    "provider_code": provider_code,
                    "signal_kind": signal.signal_kind,
                    "matched_value": signal.matched_value,
                    "source_locator": signal.source_locator,
                    "snapshot_id": snapshot_id,
                }
                assertion_id = identity.relation_assertion_id(
                    relation_id, signal.assertion_basis, evidence
                )
                cur.execute("""
                    INSERT INTO legal_kb.source_relation_assertion
                        (relation_assertion_id, source_relation_id, snapshot_id,
                         ingestion_run_id, assertion_basis, assertion_status,
                         source_locator, evidence_jsonb, observed_at)
                    VALUES (%s, %s, %s, %s, %s, 'candidate', %s, %s::jsonb, %s)
                    ON CONFLICT (relation_assertion_id) DO NOTHING
                """, (
                    assertion_id, relation_id, snapshot_id, ingestion_run_id,
                    signal.assertion_basis, signal.source_locator,
                    json.dumps(evidence, ensure_ascii=False), datetime.now(timezone.utc),
                ))
                assertion_count += cur.rowcount
    return LinkagePersistResult(relation_count, assertion_count)

def record_manual_review(
    conn,
    *,
    source_relation_id: str,
    ingestion_run_id: str,
    decision: str,
    rationale: str,
    reviewer_ref: str | None = None,
    snapshot_id: str | None = None,
) -> str:
    if decision not in {"confirmed", "rejected"}:
        raise ValueError("manual decision must be confirmed or rejected")
    if not rationale.strip():
        raise ValueError("manual review requires rationale")
    evidence = {
        "manual_review": True,
        "decision": decision,
        "rationale": rationale.strip(),
    }
    if reviewer_ref:
        evidence["reviewer_ref"] = reviewer_ref
    assertion_id = identity.relation_assertion_id(
        source_relation_id, "manual", evidence
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM legal_kb.source_relation WHERE source_relation_id = %s", (source_relation_id,))
        if cur.fetchone() is None:
            raise ValueError("source relation does not exist")
        cur.execute("""
            INSERT INTO legal_kb.source_relation_assertion
                (relation_assertion_id, source_relation_id, snapshot_id,
                 ingestion_run_id, assertion_basis, assertion_status,
                 source_locator, evidence_jsonb, observed_at)
            VALUES (%s, %s, %s, %s, 'manual', %s,
                    'manual-review', %s::jsonb, %s)
            ON CONFLICT (relation_assertion_id) DO NOTHING
        """, (
            assertion_id, source_relation_id, snapshot_id, ingestion_run_id,
            decision, json.dumps(evidence, ensure_ascii=False), datetime.now(timezone.utc),
        ))
    return assertion_id
