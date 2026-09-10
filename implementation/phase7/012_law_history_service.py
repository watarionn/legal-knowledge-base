from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import re
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
PHASE5_DIR = HERE.parent / "phase5"
LAW_ID_RE = re.compile(r"^[0-9A-Z]{15}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TEMPORAL = _load("legal_kb_phase7_history_temporal", PHASE5_DIR / "003_temporal_resolver.py")
def parse_as_of_date(value: str | None, *, default_date: date | None = None) -> date:
    if value in (None, ""):
        return default_date or date.today()
    if not DATE_RE.fullmatch(value):
        raise ValueError("as_of_date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("as_of_date must be a valid calendar date") from exc
    return parsed


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def _content_status(document_count: int) -> str:
    if document_count == 0:
        return "missing"
    if document_count == 1:
        return "available"
    return "multiple"


def _fetch_law_meta(conn: Any, law_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.law_id, l.law_num,
                   latest.law_title, latest.abbrev, latest.law_type
            FROM legal_kb.law l
            LEFT JOIN LATERAL (
                SELECT law_title, abbrev, law_type
                FROM legal_kb.law_revision lr
                WHERE lr.law_id = l.law_id
                ORDER BY revision_sequence DESC NULLS LAST,
                         revision_id_effective_date DESC,
                         law_revision_id DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE l.law_id = %s
            """,
            (law_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        names = [column.name for column in cur.description]
    return dict(zip(names, row))
def _fetch_revision_rows(conn: Any, law_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT lr.law_revision_id,
                   lr.revision_sequence,
                   lr.revision_id_effective_date,
                   lr.valid_from,
                   lr.valid_to_exclusive,
                   lr.revision_date_kind,
                   lr.temporal_resolution_quality,
                   lr.current_revision_status,
                   lr.amendment_promulgate_date,
                   lr.amendment_enforcement_date,
                   lr.amendment_scheduled_enforcement_date,
                   lr.amendment_law_id,
                   lr.amendment_law_num,
                   lr.amendment_law_title,
                   lr.amendment_type,
                   docs.succeeded_document_count,
                   doc.document_pk,
                   doc.document_id,
                   doc.source_xml_sha256
            FROM legal_kb.law_revision lr
            LEFT JOIN LATERAL (
                SELECT count(*)::integer AS succeeded_document_count
                FROM legal_kb.law_document d
                WHERE d.law_revision_id = lr.law_revision_id
                  AND d.parse_status = 'succeeded'
            ) docs ON TRUE
            LEFT JOIN LATERAL (
                SELECT d.document_pk, d.document_id, d.source_xml_sha256
                FROM legal_kb.law_document d
                WHERE d.law_revision_id = lr.law_revision_id
                  AND d.parse_status = 'succeeded'
                ORDER BY d.document_pk
                LIMIT 1
            ) doc ON docs.succeeded_document_count = 1
            WHERE lr.law_id = %s
            ORDER BY lr.revision_sequence DESC NULLS LAST,
                     lr.revision_id_effective_date DESC,
                     lr.law_revision_id DESC
            """,
            (law_id,),
        )
        names = [column.name for column in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]
def build_history_response(
    law_meta: dict[str, Any],
    rows: list[dict[str, Any]],
    temporal_resolution: Any,
) -> dict[str, Any]:
    candidate_ids = {
        item.law_revision_id for item in temporal_resolution.candidates
    }
    selected_id = temporal_resolution.selected_revision_id
    revisions = []
    for row in rows:
        document_count = int(row.get("succeeded_document_count") or 0)
        revision_id = row["law_revision_id"]
        item = {
            key: _iso(value)
            for key, value in row.items()
            if key not in {"succeeded_document_count"}
        }
        item["content_status"] = _content_status(document_count)
        item["succeeded_document_count"] = document_count
        item["selected_for_as_of"] = revision_id == selected_id
        item["candidate_for_as_of"] = revision_id in candidate_ids
        revisions.append(item)
    return {
        "api_version": "1",
        "law": law_meta,
        "as_of_date": temporal_resolution.as_of_date.isoformat(),
        "temporal_resolution": temporal_resolution.to_dict(),
        "revision_count": len(revisions),
        "revisions": revisions,
        "source_truth": "phase3-phase4",
    }


def get_law_history(
    conn: Any,
    law_id: str,
    *,
    as_of_date: date,
) -> dict[str, Any] | None:
    if not LAW_ID_RE.fullmatch(law_id or ""):
        raise ValueError("law_id must be a 15-character e-Gov law ID")
    law_meta = _fetch_law_meta(conn, law_id)
    if law_meta is None:
        return None
    rows = _fetch_revision_rows(conn, law_id)
    temporal_resolution = TEMPORAL.resolve_as_of(conn, law_id, as_of_date)
    return build_history_response(law_meta, rows, temporal_resolution)
