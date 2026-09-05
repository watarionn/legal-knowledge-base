from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import re
from typing import Any, Iterable

LAW_ID_RE = re.compile(r"^[0-9A-Z]{15}$")
STRICT_QUALITIES = frozenset({"confirmed-api", "confirmed-revision-id"})


@dataclass(frozen=True)
class TemporalCandidate:
    law_revision_id: str
    valid_from: date | None
    valid_to_exclusive: date | None
    temporal_resolution_quality: str | None
    revision_sequence: int | None
    law_title: str | None
    succeeded_document_count: int
    document_pk: int | None
    document_id: str | None
    source_xml_sha256: str | None


@dataclass(frozen=True)
class TemporalResolution:
    law_id: str
    as_of_date: date
    status: str
    selected_revision_id: str | None
    content_status: str
    selected_document_pk: int | None
    selected_document_id: str | None
    source_xml_sha256: str | None
    candidates: tuple[TemporalCandidate, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["as_of_date"] = self.as_of_date.isoformat()
        for candidate in value["candidates"]:
            if candidate["valid_from"] is not None:
                candidate["valid_from"] = candidate["valid_from"].isoformat()
            if candidate["valid_to_exclusive"] is not None:
                candidate["valid_to_exclusive"] = candidate["valid_to_exclusive"].isoformat()
        return value


def _candidate(row: dict[str, Any]) -> TemporalCandidate:
    return TemporalCandidate(
        law_revision_id=row["law_revision_id"],
        valid_from=row.get("valid_from"),
        valid_to_exclusive=row.get("valid_to_exclusive"),
        temporal_resolution_quality=row.get("temporal_resolution_quality"),
        revision_sequence=row.get("revision_sequence"),
        law_title=row.get("law_title"),
        succeeded_document_count=int(row.get("succeeded_document_count") or 0),
        document_pk=row.get("document_pk"),
        document_id=row.get("document_id"),
        source_xml_sha256=row.get("source_xml_sha256"),
    )


def classify_candidates(
    law_id: str,
    as_of_date: date,
    rows: Iterable[dict[str, Any]],
) -> TemporalResolution:
    if not LAW_ID_RE.fullmatch(law_id or ""):
        raise ValueError(f"invalid law_id: {law_id!r}")
    if not isinstance(as_of_date, date):
        raise TypeError("as_of_date must be datetime.date")

    candidates = tuple(_candidate(row) for row in rows)

    if not candidates:
        return TemporalResolution(
            law_id=law_id,
            as_of_date=as_of_date,
            status="not-found",
            selected_revision_id=None,
            content_status="none",
            selected_document_pk=None,
            selected_document_id=None,
            source_xml_sha256=None,
            candidates=(),
            warnings=("NO_TEMPORAL_CANDIDATE",),
        )

    if len(candidates) > 1:
        return TemporalResolution(
            law_id=law_id,
            as_of_date=as_of_date,
            status="ambiguous",
            selected_revision_id=None,
            content_status="candidate-dependent",
            selected_document_pk=None,
            selected_document_id=None,
            source_xml_sha256=None,
            candidates=candidates,
            warnings=("TEMPORAL_MULTIPLE_CANDIDATES",),
        )

    candidate = candidates[0]
    if candidate.temporal_resolution_quality not in STRICT_QUALITIES:
        return TemporalResolution(
            law_id=law_id,
            as_of_date=as_of_date,
            status="unresolved",
            selected_revision_id=None,
            content_status="candidate-dependent",
            selected_document_pk=None,
            selected_document_id=None,
            source_xml_sha256=None,
            candidates=candidates,
            warnings=("TEMPORAL_QUALITY_NOT_STRICT",),
        )

    document_count = candidate.succeeded_document_count
    if document_count == 0:
        content_status = "missing"
        document_pk = None
        document_id = None
        source_xml_sha256 = None
        warnings = ("CONTENT_NOT_AVAILABLE",)
    elif document_count == 1:
        if (
            candidate.document_pk is None
            or candidate.document_id is None
            or candidate.source_xml_sha256 is None
        ):
            raise ValueError("single succeeded document is missing document provenance")
        content_status = "available"
        document_pk = candidate.document_pk
        document_id = candidate.document_id
        source_xml_sha256 = candidate.source_xml_sha256
        warnings = ()
    else:
        content_status = "multiple"
        document_pk = None
        document_id = None
        source_xml_sha256 = None
        warnings = ("MULTIPLE_SUCCEEDED_DOCUMENTS",)

    return TemporalResolution(
        law_id=law_id,
        as_of_date=as_of_date,
        status="resolved",
        selected_revision_id=candidate.law_revision_id,
        content_status=content_status,
        selected_document_pk=document_pk,
        selected_document_id=document_id,
        source_xml_sha256=source_xml_sha256,
        candidates=candidates,
        warnings=warnings,
    )


def resolve_as_of(conn, law_id: str, as_of_date: date) -> TemporalResolution:
    if not LAW_ID_RE.fullmatch(law_id or ""):
        raise ValueError(f"invalid law_id: {law_id!r}")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM legal_kb.law_revision_as_of_candidates(%s, %s)",
            (law_id, as_of_date),
        )
        names = [column.name for column in cur.description]
        rows = [dict(zip(names, values)) for values in cur.fetchall()]
    return classify_candidates(law_id, as_of_date, rows)
