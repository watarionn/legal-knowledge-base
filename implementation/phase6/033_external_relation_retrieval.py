from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExternalSourceEnvelope:
    source_relation_id: str
    external_document_id: str
    provider_code: str
    source_family: str
    provider_document_id: str
    document_kind: str
    issued_on: Any
    title: str | None
    canonical_url: str | None
    target_kind: str
    relation_kind: str
    effective_state: str
    citation_ready: bool
    snapshot_id: str | None
    source_file_id: str | None
    source_file_sha256: str | None


def _target_clause(target_kind: str, target_id: str) -> tuple[str, tuple[Any, ...]]:
    if target_kind == "law":
        return "target_law_id = %s", (target_id,)
    if target_kind == "law_revision":
        return "target_law_revision_id = %s", (target_id,)
    if target_kind == "provision_node":
        try:
            document_pk_text, document_order_text = target_id.split(":", 1)
            document_pk = int(document_pk_text)
            document_order = int(document_order_text)
        except (ValueError, TypeError) as exc:
            raise ValueError("provision_node target_id must be document_pk:document_order") from exc
        if document_pk <= 0 or document_order <= 0:
            raise ValueError("provision_node identifiers must be positive")
        return "target_document_pk = %s AND target_document_order = %s", (document_pk, document_order)
    raise ValueError("unsupported target_kind")

def fetch_external_source_envelopes(
    conn,
    *,
    target_kind: str,
    target_id: str,
    include_nonconfirmed: bool = False,
) -> tuple[ExternalSourceEnvelope, ...]:
    clause, params = _target_clause(target_kind, target_id)
    state_clause = "" if include_nonconfirmed else "AND effective_state = 'confirmed'"
    sql = f"""
        SELECT source_relation_id, external_document_id, provider_code,
               source_family, provider_document_id, document_kind,
               issued_on, title, canonical_url, target_kind, relation_kind,
               effective_state, citation_ready, snapshot_id,
               source_file_id, source_file_sha256
        FROM legal_kb.external_relation_retrieval
        WHERE {clause}
          {state_clause}
        ORDER BY issued_on NULLS LAST, provider_code,
                 provider_document_id, source_relation_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return tuple(ExternalSourceEnvelope(*row) for row in rows)


def fetch_relation_assertions(conn, source_relation_id: str) -> tuple[dict[str, Any], ...]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT relation_assertion_id, assertion_basis, assertion_status,
                   snapshot_id, source_locator, evidence_jsonb, observed_at
            FROM legal_kb.source_relation_assertion
            WHERE source_relation_id = %s
            ORDER BY observed_at, relation_assertion_id
        """, (source_relation_id,))
        rows = cur.fetchall()
    return tuple({
        "relation_assertion_id": row[0],
        "assertion_basis": row[1],
        "assertion_status": row[2],
        "snapshot_id": row[3],
        "source_locator": row[4],
        "evidence": row[5],
        "observed_at": row[6],
    } for row in rows)
