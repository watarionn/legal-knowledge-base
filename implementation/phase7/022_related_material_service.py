from __future__ import annotations

from collections import Counter
from datetime import date
import importlib.util
from pathlib import Path
import re
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
PHASE5_DIR = HERE.parent / "phase5"
PHASE6_DIR = HERE.parent / "phase6"
LAW_ID_RE = re.compile(r"^[0-9A-Z]{15}$")
RELATION_ID_RE = re.compile(r"^[0-9a-f]{64}$")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

TEMPORAL = _load(
    "legal_kb_phase7_related_temporal",
    PHASE5_DIR / "003_temporal_resolver.py",
)
EXTERNAL = _load(
    "legal_kb_phase7_external_relation_retrieval",
    PHASE6_DIR / "033_external_relation_retrieval.py",
)


def _law_exists(conn: Any, law_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM legal_kb.law WHERE law_id = %s", (law_id,))
        return cur.fetchone() is not None


def _relation_payload(envelope: Any, target_id: str) -> dict[str, Any]:
    return {
        "source_relation_id": envelope.source_relation_id,
        "target_kind": envelope.target_kind,
        "target_id": target_id,
        "relation_kind": envelope.relation_kind,
        "effective_state": envelope.effective_state,
        "citation_ready": envelope.citation_ready,
    }


def _material_base(envelope: Any) -> dict[str, Any]:
    return {
        "external_document_id": envelope.external_document_id,
        "provider_code": envelope.provider_code,
        "source_family": envelope.source_family,
        "provider_document_id": envelope.provider_document_id,
        "document_kind": envelope.document_kind,
        "issued_on": envelope.issued_on.isoformat() if envelope.issued_on else None,
        "title": envelope.title,
        "canonical_url": envelope.canonical_url,
        "snapshot_id": envelope.snapshot_id,
        "source_file_id": envelope.source_file_id,
        "source_file_sha256": envelope.source_file_sha256,
        "relations": [],
    }


def _collect_target(
    conn: Any,
    *,
    target_kind: str,
    target_id: str,
    include_nonconfirmed: bool,
) -> tuple[Any, ...]:
    return EXTERNAL.fetch_external_source_envelopes(
        conn,
        target_kind=target_kind,
        target_id=target_id,
        include_nonconfirmed=include_nonconfirmed,
    )


def build_material_response(
    law_id: str,
    as_of_date: date,
    temporal_resolution: Any,
    envelopes_by_scope: list[tuple[str, str, tuple[Any, ...]]],
    *,
    include_nonconfirmed: bool,
) -> dict[str, Any]:
    materials: dict[str, dict[str, Any]] = {}
    state_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()

    for _scope_kind, target_id, envelopes in envelopes_by_scope:
        for envelope in envelopes:
            material = materials.setdefault(
                envelope.external_document_id,
                _material_base(envelope),
            )
            relation = _relation_payload(envelope, target_id)
            if not any(
                item["source_relation_id"] == relation["source_relation_id"]
                for item in material["relations"]
            ):
                material["relations"].append(relation)
                state_counts[relation["effective_state"]] += 1

    ordered = sorted(
        materials.values(),
        key=lambda item: (
            item["issued_on"] is None,
            item["issued_on"] or "",
            item["provider_code"],
            item["provider_document_id"],
        ),
    )
    family_counts = Counter(item["source_family"] for item in ordered)
    for material in ordered:
        material["relations"].sort(
            key=lambda item: (
                item["target_kind"],
                item["relation_kind"],
                item["source_relation_id"],
            )
        )
        material["citation_ready"] = any(
            relation["citation_ready"] for relation in material["relations"]
        )

    revision_id = (
        temporal_resolution.selected_revision_id
        if temporal_resolution.status == "resolved"
        else None
    )

    return {
        "api_version": "1",
        "law_id": law_id,
        "as_of_date": as_of_date.isoformat(),
        "temporal_resolution": temporal_resolution.to_dict(),
        "revision_scope_available": revision_id is not None,
        "selected_revision_id": revision_id,
        "include_nonconfirmed": include_nonconfirmed,
        "material_count": len(ordered),
        "relation_count": sum(state_counts.values()),
        "state_counts": dict(sorted(state_counts.items())),
        "source_family_counts": dict(sorted(family_counts.items())),
        "materials": ordered,
        "source_truth": "phase6-external-provenance",
        "law_text_truth": "phase3-phase4",
    }


def get_related_materials(
    conn: Any,
    law_id: str,
    *,
    as_of_date: date,
    include_nonconfirmed: bool = False,
) -> dict[str, Any] | None:
    if not LAW_ID_RE.fullmatch(law_id or ""):
        raise ValueError("law_id must be a 15-character e-Gov law ID")
    if not _law_exists(conn, law_id):
        return None

    temporal = TEMPORAL.resolve_as_of(conn, law_id, as_of_date)
    scopes: list[tuple[str, str, tuple[Any, ...]]] = []
    scopes.append((
        "law",
        law_id,
        _collect_target(
            conn,
            target_kind="law",
            target_id=law_id,
            include_nonconfirmed=include_nonconfirmed,
        ),
    ))
    if temporal.status == "resolved" and temporal.selected_revision_id:
        revision_id = temporal.selected_revision_id
        scopes.append((
            "law_revision",
            revision_id,
            _collect_target(
                conn,
                target_kind="law_revision",
                target_id=revision_id,
                include_nonconfirmed=include_nonconfirmed,
            ),
        ))
    return build_material_response(
        law_id,
        as_of_date,
        temporal,
        scopes,
        include_nonconfirmed=include_nonconfirmed,
    )


def get_relation_detail(conn: Any, source_relation_id: str) -> dict[str, Any] | None:
    if not RELATION_ID_RE.fullmatch(source_relation_id or ""):
        raise ValueError("source_relation_id must be a 64-character lowercase SHA-256")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source_relation_id, external_document_id, provider_code,
                   source_family, provider_document_id, document_kind,
                   issued_on, title, canonical_url, target_kind,
                   target_law_id, target_law_revision_id,
                   target_document_pk, target_document_order,
                   relation_kind, effective_state, citation_ready,
                   snapshot_id, source_file_id, source_file_sha256
            FROM legal_kb.external_relation_retrieval
            WHERE source_relation_id = %s
        """, (source_relation_id,))
        row = cur.fetchone()
    if row is None:
        return None

    target_kind = row[9]
    if target_kind == "law":
        target_id = row[10]
    elif target_kind == "law_revision":
        target_id = row[11]
    else:
        target_id = f"{row[12]}:{row[13]}"

    assertions = []
    for assertion in EXTERNAL.fetch_relation_assertions(conn, source_relation_id):
        item = dict(assertion)
        observed_at = item.get("observed_at")
        if observed_at is not None:
            item["observed_at"] = observed_at.isoformat()
        assertions.append(item)

    return {
        "source_relation_id": row[0],
        "external_document_id": row[1],
        "provider_code": row[2],
        "source_family": row[3],
        "provider_document_id": row[4],
        "document_kind": row[5],
        "issued_on": row[6].isoformat() if row[6] else None,
        "title": row[7],
        "canonical_url": row[8],
        "target_kind": target_kind,
        "target_id": target_id,
        "relation_kind": row[14],
        "effective_state": row[15],
        "citation_ready": row[16],
        "snapshot_id": row[17],
        "source_file_id": row[18],
        "source_file_sha256": row[19],
        "assertions": assertions,
        "source_truth": "phase6-external-provenance",
    }
