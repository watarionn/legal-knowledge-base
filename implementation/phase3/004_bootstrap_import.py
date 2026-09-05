#!/usr/bin/env python3
"""Phase 3 bootstrap importer for the legal knowledge base.

Imports e-Gov Law API Version 2 law metadata and complete revision histories
into the PostgreSQL schema created by 001_law_history_schema.sql.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

BASE_URL = "https://laws.e-gov.go.jp/api/2"
LAW_ID_RE = re.compile(r"^[0-9A-Z]{15}$")
REVISION_ID_RE = re.compile(r"^([0-9A-Z]{15})_([0-9]{8})_([0-9A-Z]{15})$")
BASELINE_SUFFIX = "000000000000000"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
PARSER_VERSION = "phase3-bootstrap-1.0"

LAW_COLUMNS = (
    "law_id", "law_num", "law_type", "law_num_era", "law_num_year",
    "law_num_type", "law_num_num", "promulgation_date",
)
REVISION_SOURCE_COLUMNS = (
    "law_revision_id", "law_type", "law_title", "law_title_kana", "abbrev",
    "category", "updated", "amendment_promulgate_date",
    "amendment_enforcement_date", "amendment_enforcement_comment",
    "amendment_scheduled_enforcement_date", "amendment_law_id",
    "amendment_law_title", "amendment_law_title_kana", "amendment_law_num",
    "amendment_type", "repeal_status", "repeal_date", "remain_in_force",
    "mission", "current_revision_status",
)
REVISION_DERIVED_COLUMNS = (
    "revision_id_effective_date", "revision_id_amending_law_id",
    "revision_date_kind", "revision_sequence", "valid_from",
    "valid_to_exclusive", "temporal_resolution_quality", "api_revision_ordinal",
)


@dataclass(frozen=True)
class HttpPayload:
    url: str
    retrieved_at: datetime
    body: bytes
    data: dict[str, Any]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass(frozen=True)
class ParsedRevisionId:
    law_id: str
    effective_date: date
    amending_law_id: str


@dataclass(frozen=True)
class TemporalDerivation:
    revision_date_kind: str
    valid_from: date | None
    temporal_resolution_quality: str
    issues: tuple[dict[str, Any], ...]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_run_id() -> str:
    now = utcnow()
    return f"api-v2-bootstrap-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def parse_iso_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def json_ready(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    return value


def parse_revision_id(law_revision_id: str) -> ParsedRevisionId:
    match = REVISION_ID_RE.fullmatch(law_revision_id or "")
    if not match:
        raise ValueError(f"invalid law_revision_id: {law_revision_id!r}")
    law_id, yyyymmdd, amending_law_id = match.groups()
    try:
        effective_date = datetime.strptime(yyyymmdd, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"invalid date in law_revision_id: {law_revision_id!r}") from exc
    return ParsedRevisionId(law_id, effective_date, amending_law_id)


def derive_temporal(revision: dict[str, Any], parsed: ParsedRevisionId) -> TemporalDerivation:
    """Derive time fields without overwriting API source values."""
    if parsed.amending_law_id == BASELINE_SUFFIX:
        return TemporalDerivation("unknown", parsed.effective_date, "ambiguous", ())

    api_date = parse_iso_date(revision.get("amendment_enforcement_date"))
    if api_date is None:
        return TemporalDerivation(
            "amendment-enforcement", parsed.effective_date,
            "confirmed-revision-id", (),
        )
    if api_date == parsed.effective_date:
        return TemporalDerivation("amendment-enforcement", api_date, "confirmed-api", ())

    issue = {
        "field_name": "amendment_enforcement_date",
        "issue_code": "REVISION_EFFECTIVE_DATE_MISMATCH",
        "severity": "error",
        "observed_values": {
            "api_amendment_enforcement_date": api_date.isoformat(),
            "revision_id_effective_date": parsed.effective_date.isoformat(),
        },
    }
    return TemporalDerivation("amendment-enforcement", None, "ambiguous", (issue,))


def derive_intervals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            row["valid_from"] is None,
            row["valid_from"] or date.max,
            row["law_revision_id"],
        ),
    )
    for sequence, row in enumerate(ordered, start=1):
        row["revision_sequence"] = sequence

    dates = sorted({row["valid_from"] for row in rows if row["valid_from"] is not None})
    next_by_date = {
        current: dates[index + 1] if index + 1 < len(dates) else None
        for index, current in enumerate(dates)
    }
    counts = {day: sum(row["valid_from"] == day for row in rows) for day in dates}
    for row in rows:
        current = row["valid_from"]
        row["valid_to_exclusive"] = next_by_date.get(current) if current is not None else None
        if current is not None and counts[current] > 1:
            row["temporal_resolution_quality"] = "ambiguous"
    return rows


def same_day_groups(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[date, list[str]] = {}
    for row in rows:
        if row.get("valid_from") is not None:
            grouped.setdefault(row["valid_from"], []).append(row["law_revision_id"])
    return [
        {"valid_from": day, "revision_ids": sorted(ids)}
        for day, ids in sorted(grouped.items()) if len(ids) > 1
    ]


def build_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return url


def fetch_json(url: str, timeout: float, max_retries: int, retry_base: float) -> HttpPayload:
    attempt = 0
    while True:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "legal-kb-phase3-bootstrap/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"expected JSON object from {url}")
            return HttpPayload(url, utcnow(), body, data)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_HTTP_STATUS or attempt >= max_retries:
                raise
            try:
                retry_after = max(0.0, float(exc.headers.get("Retry-After")))
            except (TypeError, ValueError):
                retry_after = None
        except (urllib.error.URLError, TimeoutError):
            if attempt >= max_retries:
                raise
            retry_after = None
        delay = retry_after if retry_after is not None else retry_base * (2**attempt)
        time.sleep(delay + random.uniform(0, min(1.0, retry_base)))
        attempt += 1


def write_raw(raw_dir: Path | None, run_id: str, payload: HttpPayload, name: str) -> str | None:
    if raw_dir is None:
        return None
    path = raw_dir / run_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload.body)
    return str(path)


def import_psycopg():
    try:
        import psycopg  # type: ignore
        from psycopg.types.json import Jsonb  # type: ignore
    except ImportError as exc:
        raise SystemExit("Install psycopg 3 with: python -m pip install 'psycopg[binary]>=3.1'") from exc
    return psycopg, Jsonb


def assert_schema(conn: Any) -> None:
    required = {
        "ingestion_run", "source_file", "law", "law_revision",
        "source_assertion", "reconciliation_issue",
    }
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='legal_kb'")
        present = {row[0] for row in cur.fetchall()}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError(f"legal_kb schema incomplete: {', '.join(missing)}")


def insert_run(conn: Any, run_id: str, openapi_sha256: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO legal_kb.ingestion_run
               (ingestion_run_id, started_at, parser_version, openapi_sha256, result_status)
               VALUES (%s,%s,%s,%s,'running')""",
            (run_id, utcnow(), PARSER_VERSION, openapi_sha256),
        )
    conn.commit()


def finish_run(conn: Any, run_id: str, status: str, warnings: int, errors: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE legal_kb.ingestion_run SET completed_at=%s, result_status=%s,
               warnings_count=%s, errors_count=%s WHERE ingestion_run_id=%s""",
            (utcnow(), status, warnings, errors, run_id),
        )
    conn.commit()


def upsert_fixed(conn: Any, table: str, key: str, columns: Sequence[str], row: dict[str, Any], run_id: str) -> None:
    names = list(columns) + ["first_seen_run_id", "last_seen_run_id"]
    placeholders = ",".join(["%s"] * len(names))
    updates = ",".join(f"{col}=EXCLUDED.{col}" for col in columns if col != key)
    updates += ",last_seen_run_id=EXCLUDED.last_seen_run_id,updated_at=now()"
    sql = (
        f"INSERT INTO legal_kb.{table} ({','.join(names)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({key}) DO UPDATE SET {updates}"
    )
    values = [row.get(col) for col in columns] + [run_id, run_id]
    with conn.cursor() as cur:
        cur.execute(sql, values)


def upsert_law(conn: Any, law_info: dict[str, Any], run_id: str) -> None:
    law_id = law_info.get("law_id")
    if not LAW_ID_RE.fullmatch(law_id or ""):
        raise ValueError(f"invalid law_id: {law_id!r}")
    if not law_info.get("law_type"):
        raise ValueError(f"law_type is required for {law_id}")
    upsert_fixed(conn, "law", "law_id", LAW_COLUMNS, law_info, run_id)


def store_source_file(conn: Any, run_id: str, source_id: str, payload: HttpPayload, stored_path: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO legal_kb.source_file
               (source_file_id,source_family,source_url,provider_file_id,stored_path,
                retrieved_at,media_type,byte_size,sha256,immutable,ingestion_run_id)
               VALUES (%s,'api-v2-json',%s,%s,%s,%s,'application/json',%s,%s,%s,%s)
               ON CONFLICT (source_file_id) DO UPDATE SET
                 source_url=EXCLUDED.source_url,stored_path=EXCLUDED.stored_path,
                 retrieved_at=EXCLUDED.retrieved_at,byte_size=EXCLUDED.byte_size,
                 sha256=EXCLUDED.sha256,immutable=EXCLUDED.immutable,
                 ingestion_run_id=EXCLUDED.ingestion_run_id""",
            (
                source_id, payload.url, source_id, stored_path, payload.retrieved_at,
                len(payload.body), payload.sha256, stored_path is not None, run_id,
            ),
        )


def add_assertions(
    conn: Any, Jsonb: Any, *, entity_type: str, entity_id: str,
    values: dict[str, Any], fields: Iterable[str], source_kind: str,
    source_file_id: str, run_id: str, locator: str, observed_at: datetime,
    reason: str,
) -> None:
    rows = [
        (
            entity_type, entity_id, field, source_kind, source_file_id, run_id,
            f"{locator}:{field}", observed_at, Jsonb(json_ready(values.get(field))), reason,
        )
        for field in fields if field in values
    ]
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO legal_kb.source_assertion
               (entity_type,entity_id,field_name,source_kind,source_file_id,
                ingestion_run_id,source_locator,observed_at,value_jsonb,
                selected_as_canonical,selection_reason)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s)""",
            rows,
        )


def record_issue(
    conn: Any, Jsonb: Any, *, entity_type: str, entity_id: str,
    field_name: str | None, issue_code: str, severity: str,
    observed_values: Any, run_id: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT reconciliation_issue_id FROM legal_kb.reconciliation_issue
               WHERE entity_type=%s AND entity_id=%s AND field_name IS NOT DISTINCT FROM %s
                 AND issue_code=%s AND resolved_at IS NULL
               ORDER BY reconciliation_issue_id LIMIT 1""",
            (entity_type, entity_id, field_name, issue_code),
        )
        found = cur.fetchone()
        payload = Jsonb(json_ready(observed_values))
        if found:
            cur.execute(
                """UPDATE legal_kb.reconciliation_issue SET severity=%s,
                   observed_values_jsonb=%s,last_seen_run_id=%s,updated_at=now()
                   WHERE reconciliation_issue_id=%s""",
                (severity, payload, run_id, found[0]),
            )
        else:
            cur.execute(
                """INSERT INTO legal_kb.reconciliation_issue
                   (entity_type,entity_id,field_name,issue_code,severity,
                    observed_values_jsonb,first_seen_run_id,last_seen_run_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (entity_type, entity_id, field_name, issue_code, severity, payload, run_id, run_id),
            )


def build_revision_row(revision: dict[str, Any], law_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    revision_id = revision.get("law_revision_id")
    parsed = parse_revision_id(revision_id)
    if parsed.law_id != law_id:
        raise ValueError(f"revision law_id mismatch: {revision_id} vs {law_id}")
    temporal = derive_temporal(revision, parsed)
    issues = list(temporal.issues)
    amendment_law_id = revision.get("amendment_law_id")
    if (
        parsed.amending_law_id != BASELINE_SUFFIX and amendment_law_id
        and amendment_law_id != parsed.amending_law_id
    ):
        issues.append({
            "field_name": "amendment_law_id",
            "issue_code": "AMENDMENT_LAW_ID_MISMATCH",
            "severity": "error",
            "observed_values": {
                "api_amendment_law_id": amendment_law_id,
                "revision_id_amending_law_id": parsed.amending_law_id,
            },
        })
    row = dict(revision)
    row.update({
        "law_id": law_id,
        "revision_id_effective_date": parsed.effective_date,
        "revision_id_amending_law_id": parsed.amending_law_id,
        "revision_date_kind": temporal.revision_date_kind,
        "revision_sequence": None,
        "valid_from": temporal.valid_from,
        "valid_to_exclusive": None,
        "temporal_resolution_quality": temporal.temporal_resolution_quality,
    })
    return row, issues


def upsert_revision(conn: Any, row: dict[str, Any], run_id: str) -> None:
    if not row.get("law_type"):
        raise ValueError(f"law_type is required for {row.get('law_revision_id')}")
    columns = ("law_revision_id", "law_id") + REVISION_SOURCE_COLUMNS[1:] + REVISION_DERIVED_COLUMNS
    upsert_fixed(conn, "law_revision", "law_revision_id", columns, row, run_id)


def fetch_laws(args: argparse.Namespace, conn: Any, run_id: str, Jsonb: Any) -> list[str]:
    law_ids: list[str] = []
    seen: set[str] = set()
    offset = 0
    while True:
        payload = fetch_json(
            build_url(args.base_url, "/laws", {
                "limit": args.page_size, "offset": offset, "order": "law_info.law_id",
                "omit_current_revision_info": "true", "response_format": "json",
            }),
            args.timeout, args.max_retries, args.retry_base_seconds,
        )
        source_id = f"{run_id}:laws:{offset}"
        stored_path = write_raw(args.raw_dir, run_id, payload, f"laws/offset-{offset}.json")
        store_source_file(conn, run_id, source_id, payload, stored_path)
        items = payload.data.get("laws")
        if not isinstance(items, list):
            raise ValueError("/laws response missing laws[]")
        for index, item in enumerate(items):
            if args.max_laws is not None and len(law_ids) >= args.max_laws:
                break
            if not isinstance(item, dict) or not isinstance(item.get("law_info"), dict):
                raise ValueError(f"invalid /laws item at offset {offset + index}")
            info = item["law_info"]
            upsert_law(conn, info, run_id)
            law_id = info["law_id"]
            add_assertions(
                conn, Jsonb, entity_type="law", entity_id=law_id, values=info,
                fields=LAW_COLUMNS, source_kind="api-v2", source_file_id=source_id,
                run_id=run_id, locator=f"laws[{index}].law_info",
                observed_at=payload.retrieved_at,
                reason="official-api-v2-structured-value",
            )
            if law_id not in seen:
                seen.add(law_id)
                law_ids.append(law_id)
        conn.commit()
        if args.max_laws is not None and len(law_ids) >= args.max_laws:
            return law_ids
        next_offset = payload.data.get("next_offset")
        if next_offset is None:
            return law_ids
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise ValueError(f"invalid next_offset: {next_offset!r}")
        offset = next_offset


def import_revisions(args: argparse.Namespace, conn: Any, run_id: str, law_id: str, Jsonb: Any) -> int:
    payload = fetch_json(
        build_url(args.base_url, f"/law_revisions/{urllib.parse.quote(law_id, safe='')}", {"response_format": "json"}),
        args.timeout, args.max_retries, args.retry_base_seconds,
    )
    source_id = f"{run_id}:law-revisions:{law_id}"
    stored_path = write_raw(args.raw_dir, run_id, payload, f"law_revisions/{law_id}.json")
    store_source_file(conn, run_id, source_id, payload, stored_path)

    law_info = payload.data.get("law_info")
    revisions = payload.data.get("revisions")
    if not isinstance(law_info, dict) or law_info.get("law_id") != law_id:
        raise ValueError(f"/law_revisions/{law_id} returned invalid law_info")
    if not isinstance(revisions, list):
        raise ValueError(f"/law_revisions/{law_id} missing revisions[]")
    upsert_law(conn, law_info, run_id)
    add_assertions(
        conn, Jsonb, entity_type="law", entity_id=law_id, values=law_info,
        fields=LAW_COLUMNS, source_kind="api-v2", source_file_id=source_id,
        run_id=run_id, locator="law_info", observed_at=payload.retrieved_at,
        reason="official-api-v2-structured-value",
    )

    with conn.cursor() as cur:
        cur.execute("SELECT law_revision_id FROM legal_kb.law_revision WHERE law_id=%s", (law_id,))
        previous = {row[0] for row in cur.fetchall()}
        cur.execute("UPDATE legal_kb.law_revision SET revision_sequence=NULL WHERE law_id=%s", (law_id,))

    rows: list[dict[str, Any]] = []
    issues: list[tuple[str, dict[str, Any]]] = []
    for ordinal, revision in enumerate(revisions, start=1):
        if not isinstance(revision, dict):
            raise ValueError(f"invalid revision at ordinal {ordinal} for {law_id}")
        row, row_issues = build_revision_row(revision, law_id)
        row["api_revision_ordinal"] = ordinal
        if law_info.get("law_type") and row.get("law_type") != law_info.get("law_type"):
            row_issues.append({
                "field_name": "law_type", "issue_code": "LAW_TYPE_MISMATCH", "severity": "warning",
                "observed_values": {"law_info": law_info.get("law_type"), "revision_info": row.get("law_type")},
            })
        rows.append(row)
        issues.extend((row["law_revision_id"], issue) for issue in row_issues)

    derive_intervals(rows)
    current = {row["law_revision_id"] for row in rows}
    for row in rows:
        upsert_revision(conn, row, run_id)
        ordinal = row["api_revision_ordinal"]
        source_revision = revisions[ordinal - 1]
        add_assertions(
            conn, Jsonb, entity_type="law_revision", entity_id=row["law_revision_id"],
            values=source_revision, fields=REVISION_SOURCE_COLUMNS, source_kind="api-v2",
            source_file_id=source_id, run_id=run_id, locator=f"revisions[{ordinal - 1}]",
            observed_at=payload.retrieved_at, reason="official-api-v2-structured-value",
        )
        add_assertions(
            conn, Jsonb, entity_type="law_revision", entity_id=row["law_revision_id"],
            values=row, fields=REVISION_DERIVED_COLUMNS, source_kind="derived",
            source_file_id=source_id, run_id=run_id, locator="derive",
            observed_at=payload.retrieved_at, reason="phase3-ingestion-contract",
        )

    for revision_id, issue in issues:
        record_issue(
            conn, Jsonb, entity_type="law_revision", entity_id=revision_id,
            field_name=issue["field_name"], issue_code=issue["issue_code"],
            severity=issue["severity"], observed_values=issue["observed_values"], run_id=run_id,
        )
    for group in same_day_groups(rows):
        record_issue(
            conn, Jsonb, entity_type="law", entity_id=law_id, field_name="valid_from",
            issue_code="SAME_DAY_REVISION_GROUP", severity="warning",
            observed_values={
                "valid_from": group["valid_from"].isoformat(), "revision_ids": group["revision_ids"],
            },
            run_id=run_id,
        )
    for missing in sorted(previous - current):
        record_issue(
            conn, Jsonb, entity_type="law_revision", entity_id=missing,
            field_name="law_revision_id", issue_code="REVISION_NOT_OBSERVED_IN_CURRENT_API_HISTORY",
            severity="warning",
            observed_values={
                "law_id": law_id, "missing_revision_id": missing,
                "current_api_revision_count": len(current),
            },
            run_id=run_id,
        )
    conn.commit()
    return len(rows)


def record_unresolved_refs(conn: Any, run_id: str, Jsonb: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT r.law_revision_id,r.amendment_law_id FROM legal_kb.law_revision r
               LEFT JOIN legal_kb.law a ON a.law_id=r.amendment_law_id
               WHERE r.amendment_law_id IS NOT NULL AND a.law_id IS NULL
               ORDER BY r.law_revision_id"""
        )
        rows = cur.fetchall()
    for revision_id, amendment_law_id in rows:
        record_issue(
            conn, Jsonb, entity_type="law_revision", entity_id=revision_id,
            field_name="amendment_law_id", issue_code="UNRESOLVED_AMENDMENT_LAW_ID",
            severity="warning", observed_values={"amendment_law_id": amendment_law_id}, run_id=run_id,
        )
    conn.commit()
    return len(rows)


def run_manifest_hash(conn: Any, run_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_file_id,sha256 FROM legal_kb.source_file WHERE ingestion_run_id=%s ORDER BY source_file_id",
            (run_id,),
        )
        rows = cur.fetchall()
    digest = hashlib.sha256()
    for source_id, sha256 in rows:
        digest.update(f"{source_id}\t{sha256 or ''}\n".encode())
    value = digest.hexdigest()
    with conn.cursor() as cur:
        cur.execute("UPDATE legal_kb.ingestion_run SET input_manifest_sha256=%s WHERE ingestion_run_id=%s", (value, run_id))
    conn.commit()
    return value


def issue_counts(conn: Any, run_id: str) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT severity,count(*) FROM legal_kb.reconciliation_issue
               WHERE last_seen_run_id=%s AND resolved_at IS NULL GROUP BY severity""",
            (run_id,),
        )
        counts = dict(cur.fetchall())
    return int(counts.get("warning", 0)), int(counts.get("error", 0))


def database_counts(conn: Any) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM legal_kb.law")
        laws = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM legal_kb.law_revision")
        revisions = cur.fetchone()[0]
        cur.execute(
            """SELECT count(*) FROM (
                 SELECT law_id,valid_from FROM legal_kb.law_revision WHERE valid_from IS NOT NULL
                 GROUP BY law_id,valid_from HAVING count(*)>1
               ) x"""
        )
        same_day = cur.fetchone()[0]
        cur.execute(
            """SELECT count(DISTINCT r.amendment_law_id) FROM legal_kb.law_revision r
               LEFT JOIN legal_kb.law a ON a.law_id=r.amendment_law_id
               WHERE r.amendment_law_id IS NOT NULL AND a.law_id IS NULL"""
        )
        unresolved = cur.fetchone()[0]
    return {
        "law_count": int(laws), "law_revision_count": int(revisions),
        "same_day_group_count": int(same_day),
        "unresolved_amendment_law_id_count": int(unresolved),
    }


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if path is None:
        print(text, end="")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"report: {path}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap legal_kb law/revision metadata from e-Gov API v2")
    parser.add_argument("--dsn", default=os.getenv("LEGAL_KB_DSN"))
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-base-seconds", type=float, default=1.0)
    parser.add_argument("--max-laws", type=int, help="smoke-test cap; makes the run partial")
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--openapi-sha256")
    args = parser.parse_args(argv)
    if not args.dsn:
        parser.error("--dsn or LEGAL_KB_DSN is required")
    if args.page_size < 1 or args.max_retries < 0:
        parser.error("invalid page/retry settings")
    if args.max_laws is not None and args.max_laws < 1:
        parser.error("--max-laws must be >= 1")
    if args.openapi_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", args.openapi_sha256):
        parser.error("--openapi-sha256 must be 64 hexadecimal characters")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    psycopg, Jsonb = import_psycopg()
    run_id = make_run_id()
    started_at = utcnow()
    failed: dict[str, str] = {}
    revisions_seen = 0

    with psycopg.connect(args.dsn) as conn:
        assert_schema(conn)
        insert_run(conn, run_id, args.openapi_sha256)
        try:
            law_ids = fetch_laws(args, conn, run_id, Jsonb)
            for index, law_id in enumerate(law_ids, start=1):
                try:
                    revisions_seen += import_revisions(args, conn, run_id, law_id, Jsonb)
                except Exception as exc:
                    conn.rollback()
                    failed[law_id] = f"{type(exc).__name__}: {exc}"
                if index % 100 == 0 or index == len(law_ids):
                    print(f"revisions: {index}/{len(law_ids)} laws processed", file=sys.stderr)

            for law_id in list(failed):
                time.sleep(max(args.retry_base_seconds, 1.0))
                try:
                    revisions_seen += import_revisions(args, conn, run_id, law_id, Jsonb)
                    failed.pop(law_id, None)
                except Exception as exc:
                    conn.rollback()
                    failed[law_id] = f"{type(exc).__name__}: {exc}"

            partial_by_cap = args.max_laws is not None
            unresolved_rows = 0 if partial_by_cap else record_unresolved_refs(conn, run_id, Jsonb)
            manifest_sha256 = run_manifest_hash(conn, run_id)
            warnings, errors = issue_counts(conn, run_id)
            status = "partial" if partial_by_cap or failed else "succeeded"
            finish_run(conn, run_id, status, warnings, errors + len(failed))
            report = {
                "schema_version": "1.0", "run_id": run_id,
                "parser_version": PARSER_VERSION, "base_url": args.base_url,
                "started_at": started_at.isoformat(), "completed_at": utcnow().isoformat(),
                "result_status": status, "requested_law_count": len(law_ids),
                "revision_observations_processed": revisions_seen,
                "failed_law_ids": sorted(failed), "failure_messages": failed,
                "unresolved_amendment_reference_rows": unresolved_rows,
                "warning_issue_count": warnings, "error_issue_count": errors,
                "database_counts": database_counts(conn), "smoke_test_cap": args.max_laws,
                "raw_dir": str(args.raw_dir) if args.raw_dir else None,
                "openapi_sha256": args.openapi_sha256,
                "input_manifest_sha256": manifest_sha256,
            }
            write_report(args.report, report)
            return 0 if not failed else 2
        except Exception as exc:
            conn.rollback()
            finish_run(conn, run_id, "failed", 0, 1)
            write_report(args.report, {
                "schema_version": "1.0", "run_id": run_id,
                "parser_version": PARSER_VERSION, "base_url": args.base_url,
                "started_at": started_at.isoformat(), "completed_at": utcnow().isoformat(),
                "result_status": "failed", "fatal_error": f"{type(exc).__name__}: {exc}",
            })
            raise


if __name__ == "__main__":
    raise SystemExit(main())
