from __future__ import annotations

import argparse
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SERVICE = _load("legal_kb_phase7_runtime_query_service", "002_query_service.py")

DEFAULT_CASES = (
    ("construction-contract", "建設業法で請負契約に関係する規定を確認したい"),
    ("civil-code-article-90", "民法の第90条を確認したい"),
    ("labor-hours", "労働基準法で労働時間に関係する規定を確認したい"),
    (
        "personal-data",
        "個人情報の保護に関する法律で個人データに関係する規定を確認したい",
    ),
)


def _query_case(service: Any, conn: Any, *, name: str, question: str, as_of: date) -> dict[str, Any]:
    response = service.query(
        conn,
        {"question": question, "as_of_date": as_of.isoformat()},
    )
    evidence = response.get("evidence") or []
    law_resolution = response.get("law_resolution") or {}
    temporal = response.get("temporal_resolution") or {}
    retrieval = response.get("retrieval") or {}
    return {
        "name": name,
        "question": question,
        "as_of_date": as_of.isoformat(),
        "status": response.get("status"),
        "law_resolution_status": law_resolution.get("status"),
        "law_id": law_resolution.get("selected_law_id"),
        "law_title": law_resolution.get("selected_law_title"),
        "temporal_status": temporal.get("status"),
        "content_status": temporal.get("content_status"),
        "law_revision_id": temporal.get("selected_revision_id"),
        "retrieval_status": retrieval.get("status"),
        "retrieval_query_text": retrieval.get("query_text"),
        "channel_counts": retrieval.get("channel_counts"),
        "evidence_count": len(evidence),
        "citation_truth": (
            evidence[0].get("citation_truth") if evidence else None
        ),
        "source_sha_count": len(
            {item.get("source_xml_sha256") for item in evidence if item.get("source_xml_sha256")}
        ),
        "timing_ms": response.get("timing_ms") or {},
        "warnings": response.get("warnings") or [],
    }


def _find_ambiguous_case(conn: Any, as_of: date) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT lr.law_id, max(lr.law_title) AS law_title, lr.valid_from,
                   count(*) AS candidate_count
            FROM legal_kb.law_revision lr
            WHERE lr.temporal_resolution_quality='ambiguous'
              AND lr.valid_from IS NOT NULL
              AND lr.valid_from <= %s
              AND (lr.valid_to_exclusive IS NULL OR %s < lr.valid_to_exclusive)
            GROUP BY lr.law_id, lr.valid_from
            HAVING count(*) > 1
            ORDER BY lr.valid_from DESC, lr.law_id
            LIMIT 1
            """,
            (as_of, as_of),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "law_id": str(row[0]),
        "law_title": row[1],
        "as_of_date": as_of.isoformat(),
        "candidate_count": int(row[3]),
    }


def _validate_ambiguous(service: Any, conn: Any, case: dict[str, Any]) -> dict[str, Any]:
    response = service.query(
        conn,
        {
            "question": "この法令の該当時点を確認したい",
            "as_of_date": case["as_of_date"],
            "law_id": case["law_id"],
        },
    )
    temporal = response.get("temporal_resolution") or {}
    return {
        **case,
        "status": response.get("status"),
        "temporal_status": temporal.get("status"),
        "selected_revision_id": temporal.get("selected_revision_id"),
        "reported_candidate_count": len(temporal.get("candidates") or []),
        "passed": (
            response.get("status") == "blocked-temporal"
            and temporal.get("status") == "ambiguous"
            and temporal.get("selected_revision_id") is None
        ),
    }


def run(database_url: str, *, as_of: date) -> dict[str, Any]:
    import psycopg

    service = SERVICE.QueryService()
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
        cases = [
            _query_case(
                service,
                conn,
                name=name,
                question=question,
                as_of=as_of,
            )
            for name, question in DEFAULT_CASES
        ]
        ambiguous_source = _find_ambiguous_case(conn, as_of)
        ambiguous = (
            _validate_ambiguous(service, conn, ambiguous_source)
            if ambiguous_source is not None
            else None
        )

    successful = [case for case in cases if case["status"] == "evidence-only"]
    total_timings = [
        float(case["timing_ms"]["total"])
        for case in cases
        if case["timing_ms"].get("total") is not None
    ]
    evidence_integrity = all(
        case["citation_truth"] == "phase3-phase4"
        and case["source_sha_count"] == 1
        and case["evidence_count"] > 0
        for case in successful
    )
    expected_success = all(
        case["law_resolution_status"] == "resolved"
        and case["temporal_status"] == "resolved"
        and case["content_status"] == "available"
        and case["retrieval_status"] == "ok"
        and case["evidence_count"] > 0
        for case in cases
    )
    result = {
        "schema_version": "1.0",
        "runner": "011_runtime_query_validation.py",
        "as_of_date": as_of.isoformat(),
        "database_url_recorded": False,
        "answer_provider_required": False,
        "case_count": len(cases),
        "evidence_only_case_count": len(successful),
        "cases": cases,
        "ambiguous_case": ambiguous,
        "checks": {
            "all_named_cases_resolved_with_evidence": expected_success,
            "evidence_preserves_phase3_phase4_truth": evidence_integrity,
            "ambiguous_case_found": ambiguous is not None,
            "ambiguous_case_blocked_without_guessing": (
                bool(ambiguous and ambiguous["passed"])
            ),
        },
        "timing_ms": {
            "median_total": (
                round(statistics.median(total_timings), 3)
                if total_timings else None
            ),
            "max_total": round(max(total_timings), 3) if total_timings else None,
        },
    }
    result["status"] = (
        "passed"
        if all(result["checks"].values())
        else "needs-review"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Phase 7 against named real-law questions and a real ambiguous temporal case"
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("LEGAL_KB_DATABASE_URL")
        or os.environ.get("LEGAL_KB_DSN")
        or os.environ.get("DATABASE_URL"),
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit(
            "LEGAL_KB_DATABASE_URL, LEGAL_KB_DSN, DATABASE_URL, or --database-url is required"
        )
    result = run(args.database_url, as_of=args.as_of)
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
